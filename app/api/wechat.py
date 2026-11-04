"""微信聊天助手 API：数据源状态、同步（任务化）、数据范围、总结报告。

职责边界（D2 + 用户调整三）：本层只做接入与编排——问答/总结全部由
Agent 工作流完成（见 /api/wechat/chat，阶段 3.7）；同步是确定性数据
管道（本文件）；后台状态统一走 jobs 表与 /api/jobs/{id}。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..adapters.wechat_source import WechatSourceAdapter
from ..exceptions import DomainError, NotFoundError
from ..schemas.plan import IsoDate
from ..services import wechat_service
from .deps import get_session, get_settings, get_task_runner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wechat", tags=["wechat"])

OUTPUT_ROOT = Path(__file__).resolve().parent.parent.parent / "Output"
REPORT_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})_群聊总结(?:_\d{12})?\.html$")


class SyncRequest(BaseModel):
    chat_id: str | None = None
    display_name: str = ""
    start: IsoDate | None = None
    end: IsoDate | None = None


def _make_adapter(request: Request) -> WechatSourceAdapter:
    settings = get_settings(request)
    return WechatSourceAdapter(exe_path=settings.wechat_analysis_exe)


@router.get("/source/status")
def source_status(request: Request) -> dict:
    return _make_adapter(request).status()


@router.get("/data-range")
def data_range() -> list[dict[str, Any]]:
    return wechat_service.data_range()


@router.post("/sync")
def start_sync(
    payload: SyncRequest,
    request: Request,
    runner=Depends(get_task_runner),
    session=Depends(get_session),
) -> dict[str, Any]:
    """提交同步任务；同 kind 未完成任务会被拒绝（防重复提交）。"""

    if (payload.start is None) != (payload.end is None):
        raise DomainError("start 与 end 必须成对提供", code="invalid_range", status_code=422)
    if payload.start and payload.end and payload.end < payload.start:
        raise DomainError("end 不能早于 start", code="invalid_range", status_code=422)

    adapter = _make_adapter(request)
    session_factory = request.app.state.session_factory

    def job(progress_cb):
        adapter.ensure_running()  # 未运行则按配置启动并等待就绪（任务线程内执行）
        with session_factory() as job_session:
            return wechat_service.run_sync_job(
                job_session,
                adapter.client,
                chat_id=payload.chat_id,
                display_name=payload.display_name,
                start=payload.start,
                end=payload.end,
                progress_cb=progress_cb,
            )

    task = runner.submit(
        "wechat.sync",
        payload.model_dump(),
        job,
    )
    return {"task_id": task.id, "status": task.status}


# ---------- 历史总结报告（扫描 Output/ 元数据，不落库） ----------

def _scan_reports() -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    if not OUTPUT_ROOT.is_dir():
        return reports
    for directory in sorted(OUTPUT_ROOT.iterdir()):
        if not directory.is_dir():
            continue
        for file in directory.iterdir():
            match = REPORT_PATTERN.match(file.name)
            if match:
                reports.append(
                    {
                        "chat_name": directory.name,
                        "date": match.group(1),
                        "filename": file.name,
                        "created_at": file.stat().st_mtime,
                        "size": file.stat().st_size,
                    }
                )
    reports.sort(key=lambda item: item["created_at"], reverse=True)
    for index, item in enumerate(reports):
        item["seq"] = index
    return reports


@router.get("/reports")
def list_reports() -> list[dict[str, Any]]:
    return _scan_reports()


@router.get("/reports/{seq}/file")
def report_file(seq: int) -> FileResponse:
    reports = _scan_reports()
    if seq < 0 or seq >= len(reports):
        raise NotFoundError(f"报告不存在: {seq}")
    # 路径防穿越：只能返回扫描到的白名单文件
    target = OUTPUT_ROOT / reports[seq]["chat_name"] / reports[seq]["filename"]
    if not target.is_file():
        raise NotFoundError(f"报告文件缺失: {reports[seq]['filename']}")
    return FileResponse(target, media_type="text/html", filename=target.name)


# ---------- 对话（SSE 流式；问答与总结统一经 Agent 工作流，D2） ----------

import json

from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, Field
from sqlalchemy import select as sql_select

from ..models import ChatMessage, ChatSession
from ..services import wechat_jobs


class ChatRequest(BaseModel):
    session_id: int | None = None
    message: str = Field(min_length=1, max_length=4000)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _load_history(session: Session, session_id: int) -> list:
    rows = session.execute(
        sql_select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.id)
    ).scalars().all()
    messages = []
    for row in rows:
        cls = HumanMessage if row.role == "user" else AIMessage
        messages.append(cls(row.content))
    return messages


@router.get("/chat/history")
def chat_history(session_id: int, session: Session = Depends(get_session)) -> dict:
    rows = session.execute(
        sql_select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.id)
    ).scalars().all()
    return {
        "session_id": session_id,
        "messages": [
            {"role": row.role, "content": row.content, "created_at": row.created_at} for row in rows
        ],
    }


@router.post("/chat")
async def chat(
    payload: ChatRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> StreamingResponse:
    """SSE 流式对话。总结请求由 Agent 决策调用 summarize_chat 工具，
    工具提交后台 job 并在回复中携带 SUMMARY_JOB_ID 标记，本层解析后
    向前端推送 summary_job 事件（前端轮询 /api/jobs/{id}）。"""

    # 会话：复用或新建；用户消息先持久化
    if payload.session_id:
        chat_session = session.get(ChatSession, payload.session_id)
        if chat_session is None:
            raise NotFoundError(f"会话不存在: {payload.session_id}")
    else:
        chat_session = ChatSession(title=payload.message[:20])
        session.add(chat_session)
        session.flush()
    session.add(
        ChatMessage(session_id=chat_session.id, role="user", content=payload.message)
    )
    session.commit()
    session_id = chat_session.id

    history = _load_history(session, session_id)
    history.append(HumanMessage(payload.message))

    from app.wechat_agent.agent import build_agent

    agent = build_agent()

    async def event_stream():
        collected: list[str] = []
        try:
            async for event in agent.astream_events({"messages": history}, version="v2"):
                kind = event.get("event")
                if kind == "on_chat_model_stream":
                    content = event["data"]["chunk"].content or ""
                    if isinstance(content, str) and content:
                        collected.append(content)
                        yield _sse({"type": "token", "text": content})
                elif kind == "on_tool_end":
                    output = str(event["data"].get("output") or "")
                    marker = wechat_jobs.JOB_MARKER
                    if marker in output:
                        try:
                            job_id = int(output.split(marker, 1)[1].split()[0])
                            yield _sse({"type": "summary_job", "task_id": job_id})
                        except (ValueError, IndexError):
                            logger.warning("无法解析总结任务标记: %s", output[:120])
            full_text = "".join(collected)
            session.add(
                ChatMessage(session_id=session_id, role="assistant", content=full_text)
            )
            session.commit()
            yield _sse({"type": "done", "session_id": session_id})
        except Exception as exc:  # SSE 内异常必须落事件，避免前端无声卡死
            logger.exception("chat turn failed")
            yield _sse({"type": "error", "message": f"{type(exc).__name__}: {exc}"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
