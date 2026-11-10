"""晨报助手对话（V0.6 §4.5）：偏好/Memory/目标补充；Memory 提议须经用户确认才写入。

设计：助手回复中出现 [MEMORY_PROPOSAL]{json}[/MEMORY_PROPOSAL] 块 = 待确认提议；
前端展示确认/忽略按钮，确认后调 POST /memory（source=chat）写入。
SSE 流式输出；LLM 走 DashScope 开发模型。
"""

from __future__ import annotations

import json
import logging
import os
import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.orm import Session

from ..config import get_mr_settings
from .deps import get_mr_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assistant")

PROPOSAL_RE = re.compile(r"\[MEMORY_PROPOSAL\](\{.*?\})\[/MEMORY_PROPOSAL\]", re.S)

SYSTEM = """你是晨报助手，负责帮助用户管理资讯偏好、行动建议偏好、补充目标和 Memory。
规则：
- 你可以提出候选偏好（kind: interest/action_pref/supplement_goal/other），但必须用
  [MEMORY_PROPOSAL] 块（内含 kind/content 的 JSON）显式给出，等用户确认后才写入。
- 不得静默推断并持久化；用户查看/修改/删除 Memory 的请求要准确执行。
- 不提供通用新闻追问或开放式深度研究。
当前已确认 Memory：{memory}"""


class ChatIn(BaseModel):
    message: str
    history: list[dict] = []


@router.post("/chat")
def assistant_chat(body: ChatIn, mr: Session = Depends(get_mr_session)):
    from ..models import Memory
    from sqlalchemy import select as sa_select

    settings = get_mr_settings()
    memory_rows = mr.execute(sa_select(Memory).where(Memory.enabled.is_(True))).scalars().all()
    memory_txt = "；".join(f"[{m.kind}] {m.content}" for m in memory_rows) or "（无）"

    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not key:
        def err_stream():
            yield {"data": json.dumps({"delta": "助手暂不可用：DASHSCOPE_API_KEY 未配置", "done": True},
                                      ensure_ascii=False)}
        return EventSourceResponse(err_stream())

    from openai import OpenAI

    client = OpenAI(base_url=settings.dashscope_base_url, api_key=key, timeout=90)
    messages = [{"role": "system", "content": SYSTEM.format(memory=memory_txt)}]
    for h in body.history[-10:]:
        if h.get("role") in ("user", "assistant"):
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": body.message})

    def stream():
        full = ""
        try:
            resp = client.chat.completions.create(
                model=settings.dashscope_model, messages=messages, stream=True)
            for chunk in resp:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    full += delta
                    yield {"data": json.dumps({"delta": delta, "done": False}, ensure_ascii=False)}
        except Exception as exc:
            logger.warning("助手对话失败: %s", f"{type(exc).__name__}: {exc}"[:150])
            yield {"data": json.dumps({"delta": "", "error": "助手调用失败", "done": True},
                                      ensure_ascii=False)}
            return
        proposals = [
            json.loads(m.group(1)) for m in PROPOSAL_RE.finditer(full)
        ]
        visible = PROPOSAL_RE.sub("", full).strip()
        yield {"data": json.dumps(
            {"delta": "", "done": True, "content": visible, "proposals": proposals},
            ensure_ascii=False)}

    return EventSourceResponse(stream())
