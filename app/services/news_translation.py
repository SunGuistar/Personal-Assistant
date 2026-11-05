"""热门资讯中文翻译（批量、缓存、异步）。

规则（与 PRD §2.2 评分解耦）：
- 新闻获取、评分沿用现有确定性逻辑，LLM 仅用于中文翻译，不参与评分；
- 仅对最终进入 TOP 10 且缺少有效翻译（translate_status=''）的资讯发起翻译；
- 一次性批量翻译（一次 API 调用翻译至多 10 条），结果落库复用，
  刷新页面/重复抓取/定时刷新均不重复调用 LLM；
- 已是中文的资讯直接回填原文（不计翻译、不调 LLM）；无摘要的资讯只翻译标题，
  不得凭标题编造摘要；
- 翻译失败标记 failed，前端回退展示原文，不影响资讯页面运行；
- 每次 LLM 调用经 token_usage 记录成本（AGENTS §9）。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import NewsItem, TokenUsage

logger = logging.getLogger(__name__)

TRANSLATE_KIND = "news.translate"

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

_PROMPT_TEMPLATE = """你是技术资讯翻译助手。把下面的英文技术资讯标题和摘要翻译成中文。

要求：
1. 保留原意，不得编造来源未提供的信息；
2. 必要技术术语保留原文，如 LangGraph、MCP、Python、Transformer 等；
3. 摘要为空字符串时，对应 summary_zh 必须为空字符串，不得凭标题编造内容；
4. 只输出 JSON 数组，不要输出其他内容。数组长度与输入一致，按输入顺序对应，每项格式：
   {{"title_zh": "中文标题", "summary_zh": "中文摘要"}}

待翻译资讯（JSON 数组）：
{items}"""


def is_chinese(text: str) -> bool:
    """是否含中文字符（判"已是中文，无需翻译"）。"""

    return bool(_CJK_RE.search(text or ""))


def pending_top_items(session: Session, *, limit: int = 10) -> list[NewsItem]:
    """当前 TOP 10 中缺少有效翻译的资讯（翻译队列候选）。"""

    from .news_scoring import rank_top_items

    rows = session.execute(select(NewsItem).order_by(NewsItem.published_at.desc())).scalars().all()
    candidates = [
        {
            "id": row.id,
            "title": row.title,
            "url": row.url,
            "source": row.source,
            "topic": row.topic,
            "published_at": row.published_at,
            "raw_summary": row.raw_summary or "",
            "norm_heat": row.norm_heat,
            "score": row.score,
            "is_favorite": bool(row.is_favorite),
            "is_read": bool(row.is_read),
        }
        for row in rows
    ]
    top_ids = {item["id"] for item in rank_top_items(candidates, limit=limit)}
    if not top_ids:
        return []
    queue = session.execute(
        select(NewsItem)
        .where(NewsItem.id.in_(top_ids), NewsItem.translate_status == "")
        .order_by(NewsItem.id)
    ).scalars().all()
    return list(queue)


def _extract_json_array(content: str) -> list[Any]:
    """从模型输出中提取 JSON 数组（容忍 markdown 代码围栏）。"""

    text = (content or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        raise ValueError("模型输出不含 JSON 数组")
    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, list):
        raise ValueError("模型输出不是 JSON 数组")
    return parsed


def _record_usage(session: Session, llm: Any, response: Any, item_count: int) -> None:
    """LLM 调用成本落 token_usage（AGENTS §9）。"""

    usage = getattr(response, "usage_metadata", None) or {}
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    model = (
        getattr(llm, "model_name", None)
        or getattr(llm, "model", None)
        or ""
    )
    session.add(
        TokenUsage(
            kind="llm",
            model=str(model)[:64],
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_estimate=0.0,
            ref=f"{TRANSLATE_KIND}:{item_count}条",
        )
    )


def translate_pending(session: Session, llm: Any | None = None, *, limit: int = 10) -> dict:
    """翻译当前 TOP 10 中缺少有效翻译的资讯（批量一次调用）。

    - llm 可注入（测试用 FakeLLM）；为 None 时经统一出口 build_llm 构造；
    - 已是中文的资讯直接回填原文；无摘要资讯只翻译标题（summary_zh 置空）；
    - 任一异常 → 本次涉及的资讯全部标记 failed（前端回退原文，下次不再自动重试）。
    """

    queue = pending_top_items(session, limit=limit)
    if not queue:
        return {"translated": 0, "skipped_chinese": 0, "failed": 0}

    # 已是中文的资讯：回填原文，不调用 LLM
    chinese_ids = {item.id for item in queue if is_chinese(item.title)}
    for item in queue:
        if item.id in chinese_ids:
            item.title_zh = item.title
            item.summary_zh = item.raw_summary or ""
            item.translate_status = "done"
    todo = [item for item in queue if item.id not in chinese_ids]
    if not todo:
        session.commit()
        return {"translated": 0, "skipped_chinese": len(chinese_ids), "failed": 0}

    payload = [
        {"index": index, "title": item.title, "summary": item.raw_summary or ""}
        for index, item in enumerate(todo)
    ]
    failed = 0
    try:
        if llm is None:
            from ..wechat_agent.llm_config import build_llm

            llm = build_llm(max_tokens=4096, temperature=0.1)
        response = llm.invoke(_PROMPT_TEMPLATE.format(items=json.dumps(payload, ensure_ascii=False)))
        content = response.content if hasattr(response, "content") else str(response)
        results = _extract_json_array(content)
        if len(results) != len(todo) or not all(isinstance(r, dict) for r in results):
            raise ValueError("模型输出与输入条数不一致")
        for item, result in zip(todo, results):
            title_zh = str(result.get("title_zh") or "").strip()
            if not title_zh:
                raise ValueError("模型输出缺少 title_zh")
            item.title_zh = title_zh[:512]
            # 无摘要资讯：summary_zh 必须为空，不得编造
            item.summary_zh = str(result.get("summary_zh") or "").strip()[:4000] if item.raw_summary else ""
            item.translate_status = "done"
        _record_usage(session, llm, response, len(todo))
    except Exception as exc:  # 翻译失败回退原文：标记 failed，不影响资讯页面
        failed = len(todo)
        message = f"{type(exc).__name__}: {exc}"[:200]
        logger.warning("news translate failed: %s", message)
        for item in todo:
            item.translate_status = "failed"
    session.commit()
    return {"translated": len(todo) - failed, "skipped_chinese": len(chinese_ids), "failed": failed}
