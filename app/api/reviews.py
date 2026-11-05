"""每周回顾 API（阶段一）：草稿/对话（SSE）/建议生成与处置/确认保存/历史。

职责边界：薄路由层——校验 → review_service → 出 dict。
- 对话与建议生成经 SSE 流式返回（事件协议与微信问答一致：token/done/error，
  建议生成额外有 step 事件标注阶段）；
- 只读与门禁由 review_service 保证（正式周报只读、建议全处置才能确认、
  同周唯一正式周报）。
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, Field

from ..exceptions import DomainError
from ..schemas.plan import IsoDate
from ..services import llm_usage, review_service
from .deps import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reviews", tags=["reviews"])


class ReviewCreateIn(BaseModel):
    week_start: IsoDate | None = None  # 任意日期，归一化到所在自然周；缺省=上一个完整周


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class SuggestResolveIn(BaseModel):
    action: str  # accept / modify / reject
    final_content: str | None = None  # modify 必填
    reject_reason: str = ""


class DraftPatchIn(BaseModel):
    analysis_md: str | None = None
    user_notes: str | None = None


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# ---------- 草稿与查询 ----------


@router.post("")
def create_or_get_review(payload: ReviewCreateIn, session=Depends(get_session)) -> dict:
    review = review_service.get_or_create_review(session, payload.week_start)
    return review_service.review_to_dict(review)


@router.get("")
def list_reviews(session=Depends(get_session)) -> list[dict]:
    return review_service.list_reviews(session)


@router.get("/{review_id}")
def get_review_detail(review_id: int, session=Depends(get_session)) -> dict:
    review = review_service.get_review(session, review_id)
    detail = review_service.review_to_dict(review)
    detail["suggestions"] = review_service.list_suggestions(session, review_id)
    return detail


@router.get("/{review_id}/messages")
def get_review_messages(review_id: int, session=Depends(get_session)) -> dict:
    return {"messages": review_service.list_messages(session, review_id)}


@router.get("/{review_id}/report")
def get_review_report(review_id: int, session=Depends(get_session)) -> dict:
    review = review_service.get_review(session, review_id)
    return {"status": review.status, "report_md": review.report_md}


# ---------- 对话（SSE，LangGraph Agent 只读分析） ----------


def _history_as_lc_messages(session, review_id: int) -> list:
    messages = []
    for row in review_service.list_messages(session, review_id):
        cls = HumanMessage if row["role"] == "user" else AIMessage
        messages.append(cls(row["content"]))
    return messages


@router.post("/{review_id}/chat")
def chat(review_id: int, payload: ChatIn, session=Depends(get_session)) -> StreamingResponse:
    """SSE 流式多轮对话。用户消息先持久化；Agent 只读分析；
    模型用量按轮落 token_usage。正式周报只读（409）。"""
    review = review_service.get_review(session, review_id)
    review_service.ensure_editable(review)

    review_service.add_message(session, review_id, "user", payload.message)
    history = _history_as_lc_messages(session, review_id)

    from app.review_agent import build_agent

    agent = build_agent(session, review.week_start, review.week_end)

    async def event_stream():
        collected: list[str] = []
        usage_calls: list[dict] = []
        try:
            async for event in agent.astream_events({"messages": history}, version="v2"):
                kind = event.get("event")
                if kind == "on_chat_model_stream":
                    content = event["data"]["chunk"].content or ""
                    if isinstance(content, str) and content:
                        collected.append(content)
                        yield _sse({"type": "token", "text": content})
                elif kind == "on_chat_model_end":
                    output = event["data"].get("output")
                    usage = getattr(output, "usage_metadata", None)
                    if usage:
                        usage_calls.append(
                            {
                                "input_tokens": int(usage.get("input_tokens") or 0),
                                "output_tokens": int(usage.get("output_tokens") or 0),
                            }
                        )
            full_text = "".join(collected)
            if full_text:
                review_service.add_message(session, review_id, "assistant", full_text)
            if usage_calls:
                from ..wechat_agent.llm_config import get_model_name

                llm_usage.record_turn_usage(
                    session,
                    usage_calls,
                    model=get_model_name(),
                    ref=f"weekly_review:chat:{review_id}",
                )
            yield _sse({"type": "done"})
        except Exception as exc:  # SSE 内异常必须落事件，避免前端无声卡死
            logger.exception("review chat turn failed")
            yield _sse({"type": "error", "message": f"{type(exc).__name__}: {exc}"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------- 建议生成（SSE）与处置 ----------


@router.post("/{review_id}/suggestions/generate")
def generate_suggestions(review_id: int, session=Depends(get_session)) -> StreamingResponse:
    """SSE 生成/重新生成建议（草稿态）。并发与覆盖规则由 service 保证：
    生成中 409、已处置建议禁止重生成。失败保留已有草稿与建议。"""
    review = review_service.get_review(session, review_id)
    review_service.ensure_editable(review)

    async def event_stream():
        try:
            yield _sse({"type": "step", "step": "collecting", "text": "汇总对话与统计数据…"})
            suggestions = review_service.generate_suggestions(session, review_id)
            yield _sse({"type": "step", "step": "validating", "text": "校验建议依据…"})
            yield _sse({"type": "done", "suggestions": suggestions})
        except DomainError as exc:
            yield _sse({"type": "error", "code": exc.code, "message": str(exc)})
        except Exception as exc:
            logger.exception("suggestion generation failed")
            yield _sse({"type": "error", "message": f"{type(exc).__name__}: {exc}"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.put("/suggestions/{suggestion_id}")
def resolve_suggestion(suggestion_id: int, payload: SuggestResolveIn, session=Depends(get_session)) -> dict:
    return review_service.resolve_suggestion(
        session,
        suggestion_id,
        payload.action,
        final_content=payload.final_content,
        reject_reason=payload.reject_reason,
    )


# ---------- 草稿编辑与确认 ----------


@router.put("/{review_id}")
def update_draft(review_id: int, payload: DraftPatchIn, session=Depends(get_session)) -> dict:
    return review_service.update_draft(
        session, review_id, analysis_md=payload.analysis_md, user_notes=payload.user_notes
    )


@router.post("/{review_id}/confirm")
def confirm_review(review_id: int, payload: DraftPatchIn, session=Depends(get_session)) -> dict:
    """确认保存正式周报：校验全部建议已处置；同周唯一（DB 部分唯一索引兜底）。"""
    return review_service.confirm_review(
        session, review_id, analysis_md=payload.analysis_md, user_notes=payload.user_notes
    )
