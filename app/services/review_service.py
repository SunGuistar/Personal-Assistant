"""每周回顾业务状态机（阶段一）。

weekly_reviews:   draft → confirmed（单向；同周正式周报由部分唯一索引保证唯一，不可覆盖/撤销/删除）
weekly_review_suggestions: pending → accepted | modified | rejected（确认前可改判）

人工确认原则（已批准决策）：Agent 只读分析；建议必须逐条人工处置后才能确认；
确认只落周报，不写任何业务模块。

建议生成：
- 同一草稿并发安全由进程内 per-review 非阻塞锁保证（409）；
- 已有人工处置过的建议时禁止重新生成（不得无提示覆盖）；全部 pending 时可重新生成（pending 被替换）；
- 依据（basis）后端校验：记录必须存在 + 理由非空 + 任务类依据须与回顾周期对应；
  校验通过的依据回填事实摘要（fact）；无效依据整条剔除——建议 basis 为空数组时
  按"一般性建议"保留展示，但绝不允许编造来源。
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..exceptions import DomainError, NotFoundError
from ..models import (
    Book,
    BookNote,
    DailyTask,
    ImportantInfo,
    LongTermPlan,
    Memo,
    WeeklyReview,
    WeeklyReviewMessage,
    WeeklyReviewSuggestion,
)
from ..models.review import BASIS_SOURCE_TYPES
from . import llm_usage, review_stats

logger = logging.getLogger(__name__)

SUGGESTION_ACTIONS = ("accept", "modify", "reject")

# 建议生成并发锁（per review；非阻塞获取，冲突即 409，不依赖前端按钮禁用）
_locks_guard = threading.Lock()
_gen_locks: dict[int, threading.Lock] = {}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _gen_lock(review_id: int) -> threading.Lock:
    with _locks_guard:
        return _gen_locks.setdefault(review_id, threading.Lock())


# ---------- 查询与草稿生命周期 ----------


def get_review(session: Session, review_id: int) -> WeeklyReview:
    review = session.get(WeeklyReview, review_id)
    if review is None:
        raise NotFoundError(f"回顾不存在: {review_id}")
    return review


def ensure_editable(review: WeeklyReview) -> None:
    """正式周报只读：对话、生成建议、编辑正文、处置建议一律 409。"""
    if review.status == "confirmed":
        raise DomainError(
            "该周已有正式周报，不可修改或重新生成",
            code="review_confirmed",
            status_code=409,
        )


def get_or_create_review(session: Session, week_start: str | None = None) -> WeeklyReview:
    """按自然周获取或创建回顾草稿（幂等）；该周已有草稿/正式周报时原样返回。"""
    week = week_start or review_stats.default_review_week()
    start, end = review_stats.week_bounds(week)
    existing = session.execute(
        select(WeeklyReview).where(WeeklyReview.week_start == start)
    ).scalars().first()
    if existing is not None:
        return existing
    review = WeeklyReview(
        week_start=start,
        week_end=end,
        status="draft",
        stats_json=json.dumps(review_stats.weekly_stats(session, start), ensure_ascii=False),
    )
    session.add(review)
    session.commit()
    session.refresh(review)
    return review


def list_reviews(session: Session) -> list[dict]:
    rows = session.execute(
        select(WeeklyReview).order_by(WeeklyReview.week_start.desc())
    ).scalars().all()
    if not rows:
        return []
    counts = dict(
        session.execute(
            select(WeeklyReviewSuggestion.review_id, func.count())
            .where(
                WeeklyReviewSuggestion.review_id.in_([row.id for row in rows]),
                WeeklyReviewSuggestion.status == "pending",
            )
            .group_by(WeeklyReviewSuggestion.review_id)
        ).all()
    )
    result = []
    for review in rows:
        item = review_to_dict(review)
        item["pending_suggestions"] = counts.get(review.id, 0)
        result.append(item)
    return result


def review_to_dict(review: WeeklyReview) -> dict:
    try:
        stats = json.loads(review.stats_json or "{}")
    except json.JSONDecodeError:
        stats = {}
    return {
        "id": review.id,
        "week_start": review.week_start,
        "week_end": review.week_end,
        "status": review.status,
        "stats": stats,
        "analysis_md": review.analysis_md,
        "user_notes": review.user_notes,
        "has_report": bool(review.report_md),
        "confirmed_at": review.confirmed_at,
        "created_at": review.created_at,
        "updated_at": review.updated_at,
    }


def list_messages(session: Session, review_id: int) -> list[dict]:
    get_review(session, review_id)  # 404 兜底
    rows = session.execute(
        select(WeeklyReviewMessage)
        .where(WeeklyReviewMessage.review_id == review_id)
        .order_by(WeeklyReviewMessage.id)
    ).scalars().all()
    return [
        {"id": row.id, "role": row.role, "content": row.content, "created_at": row.created_at}
        for row in rows
    ]


def add_message(session: Session, review_id: int, role: str, content: str) -> None:
    session.add(WeeklyReviewMessage(review_id=review_id, role=role, content=content))
    session.commit()


def update_draft(
    session: Session,
    review_id: int,
    *,
    analysis_md: str | None = None,
    user_notes: str | None = None,
) -> dict:
    review = get_review(session, review_id)
    ensure_editable(review)
    if analysis_md is not None:
        review.analysis_md = analysis_md
    if user_notes is not None:
        review.user_notes = user_notes
    session.commit()
    return review_to_dict(review)


# ---------- 依据校验 ----------


def _task_fact(task: DailyTask) -> str:
    state = "已完成" if task.done else "未完成"
    completed = f"，完成于 {task.completed_at[:10]}" if task.completed_at else ""
    return f"任务「{task.title}」（{task.task_date}，{state}{completed}）"


def validate_basis(session: Session, review: WeeklyReview, item: dict) -> dict | None:
    """校验单条依据：记录存在 + 理由非空 + 与周期对应（任务类）。

    返回带事实摘要的依据字典；无效返回 None（调用方剔除，不得进入建议列表）。
    """
    source_type = str(item.get("source_type") or "").strip()
    if source_type not in BASIS_SOURCE_TYPES:
        return None
    try:
        source_id = int(item.get("source_id"))
    except (TypeError, ValueError):
        return None
    reason = str(item.get("reason") or "").strip()
    if not reason:
        return None

    start, end = review.week_start, review.week_end
    start_ts, end_ts = f"{start}T00:00:00", f"{end}T23:59:59"
    fact = ""
    if source_type == "daily_task":
        task = session.get(DailyTask, source_id)
        if task is None:
            return None
        in_week = (start <= task.task_date <= end) or bool(
            task.completed_at and start_ts <= task.completed_at <= end_ts
        )
        if not in_week:
            return None  # 任务依据必须与回顾周期有交集，否则视为错配剔除
        fact = _task_fact(task)
    elif source_type == "long_term_plan":
        plan = session.get(LongTermPlan, source_id)
        if plan is None:
            return None
        fact = f"长期计划「{plan.title}」（{plan.status}，目标 {plan.target_date or '未设'}）"
    elif source_type == "memo":
        memo = session.get(Memo, source_id)
        if memo is None:
            return None
        fact = f"随手备忘「{memo.title}」（更新于 {(memo.updated_at or '')[:10]}）"
    elif source_type == "important_info":
        info = session.get(ImportantInfo, source_id)
        if info is None:
            return None
        fact = f"重要信息「{info.title}」"
    elif source_type == "book":
        book = session.get(Book, source_id)
        if book is None:
            return None
        fact = f"书籍「{book.title}」（{book.status}）"
    else:  # book_note
        note = session.get(BookNote, source_id)
        if note is None:
            return None
        book = session.get(Book, note.book_id)
        fact = f"《{book.title if book else '?'}》的笔记 {note.filename}"

    return {"source_type": source_type, "source_id": source_id, "reason": reason[:500], "fact": fact}


# ---------- 建议生成（LLM 结构化输出 + 后端校验） ----------

SUGGEST_PROMPT = """你是个人每周回顾助手。基于以下材料生成本周回顾分析与下周行动建议。

【回顾周期】{week_start} 至 {week_end}（自然周）

【本周期确定性统计】
{stats}

【对话历史（用户补充信息以用户消息为准）】
{dialogue}

【相关业务事实】
{facts}

要求：
1. 先输出 analysis：对本周的客观分析（进展、阻碍、变化），只基于上述材料，不要编造；
   数据不足以判断的地方明确指出"信息不足"。
2. 再输出 suggestions：3-6 条下周行动建议，每条必须给出依据 basis 数组——
   每条依据含 source_type（daily_task / long_term_plan / memo / important_info / book / book_note）、
   source_id（整数，来自统计或事实中的 id）、reason（该记录为何支持这条建议）。
   依据必须真实存在于材料中；确实无具体记录支撑的建议，basis 留空数组（将标记为一般性建议）。
3. 输出必须是 JSON 对象：{{"analysis": "...", "suggestions": [{{"content": "...", "basis": [...]}}]}}"""


def _build_facts(session: Session, review: WeeklyReview) -> str:
    """建议生成的"相关业务事实"：重新读取当前业务状态（不只用会话文本）。"""
    start, end = review.week_start, review.week_end
    lines: list[str] = []

    active_plans = session.execute(
        select(LongTermPlan).where(LongTermPlan.status != "completed")
    ).scalars().all()
    lines.append("当前活动长期计划：")
    for plan in active_plans:
        lines.append(
            f"- [long_term_plan:{plan.id}] {plan.title}（目标: {plan.goal or '无'}，"
            f"目标日期: {plan.target_date or '未设'}，{'重要' if plan.is_important else '普通'}）"
        )
    if not active_plans:
        lines.append("- 无")

    memos = session.execute(select(Memo).order_by(Memo.id)).scalars().all()
    lines.append("随手备忘（缓冲池）：")
    for memo in memos[:20]:
        lines.append(f"- [memo:{memo.id}] {memo.title}（更新于 {(memo.updated_at or '')[:10]}）")

    overdue = review_stats.weekly_task_stats(session, start)["overdue_at_week_end"]
    lines.append(f"周末仍逾期/积压任务（共 {overdue['total']} 条）：")
    for item in overdue["items"][:20]:
        lines.append(f"- [daily_task:{item['id']}] {item['title']}（{item['task_date']}，未完成）")

    reading = review_stats.reading_snapshot(session, start)
    if reading["reading"]:
        lines.append("正在读的书：")
        for book in reading["reading"]:
            lines.append(f"- [book:{book['id']}] {book['title']}（笔记 {book['note_count']} 份）")
    return "\n".join(lines)


def _extract_json_object(content: str) -> dict:
    """从模型输出中提取 JSON 对象（容忍 ```json 围栏；参照 news_translation 的提取策略）。"""
    text = (content or "").strip()
    if "```" in text:
        fence = text.split("```")[1]
        if fence.startswith("json"):
            fence = fence[4:]
        text = fence.strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("模型输出不含 JSON 对象")
    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("模型输出不是 JSON 对象")
    return parsed


def generate_suggestions(session: Session, review_id: int, llm: Any | None = None) -> list[dict]:
    """生成/重新生成建议（草稿态）。并发安全（per-review 非阻塞锁）；失败不破坏已有数据。

    - 已有人工处置（accepted/modified/rejected）的建议 → 409，不得无提示覆盖；
    - 仅全部 pending（或没有）时允许重新生成：pending 行被替换；
    - basis 逐条后端校验（validate_basis），无效依据剔除；全部无效 → 一般性建议（空 basis）。
    """
    review = get_review(session, review_id)
    ensure_editable(review)

    lock = _gen_lock(review.id)
    if not lock.acquire(blocking=False):
        raise DomainError(
            "建议生成正在进行中，请等待完成",
            code="suggestion_generating",
            status_code=409,
        )
    try:
        dispositioned = [
            row for row in _list_suggestion_rows(session, review.id) if row.status != "pending"
        ]
        if dispositioned:
            raise DomainError(
                "已有建议被人工处置，不可重新生成（避免覆盖人工结论）",
                code="suggestions_dispositioned",
                status_code=409,
            )

        messages = list_messages(session, review.id)
        dialogue = "\n".join(
            f"{'用户' if m['role'] == 'user' else '助手'}: {m['content'][:500]}" for m in messages[-30:]
        ) or "（无对话，仅基于统计数据生成）"
        stats = json.loads(review.stats_json or "{}")
        facts = _build_facts(session, review)
        prompt = SUGGEST_PROMPT.format(
            week_start=review.week_start,
            week_end=review.week_end,
            stats=json.dumps(stats, ensure_ascii=False, indent=1)[:6000],
            dialogue=dialogue[:4000],
            facts=facts[:4000],
        )

        if llm is None:
            from ..wechat_agent.llm_config import build_llm

            llm = build_llm(max_tokens=4096, temperature=0.2)

        response = llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        parsed = _extract_json_object(content)
        analysis = str(parsed.get("analysis") or "").strip()
        raw_suggestions = parsed.get("suggestions")
        if not isinstance(raw_suggestions, list):
            raise ValueError("模型输出缺少 suggestions 数组")
        llm_usage.record_usage(
            session, llm, response, ref=f"weekly_review:suggest:{review.id}"
        )

        # 仅替换未处置的 pending（此处已保证无 dispositioned 行）
        for row in _list_suggestion_rows(session, review.id):
            session.delete(row)

        saved: list[dict] = []
        for seq, raw in enumerate(raw_suggestions):
            if not isinstance(raw, dict):
                continue
            content_text = str(raw.get("content") or "").strip()
            if not content_text:
                continue
            basis_raw = raw.get("basis")
            basis: list[dict] = []
            if isinstance(basis_raw, list):
                for item in basis_raw:
                    if not isinstance(item, dict):
                        continue
                    validated = validate_basis(session, review, item)
                    if validated is not None:
                        basis.append(validated)
            row = WeeklyReviewSuggestion(
                review_id=review.id,
                seq=seq,
                content=content_text[:2000],
                basis_json=json.dumps(basis, ensure_ascii=False),
                status="pending",
            )
            session.add(row)
            session.flush()
            saved.append(suggestion_to_dict(row))
        if analysis:
            review.analysis_md = analysis
        session.commit()
        return saved
    finally:
        lock.release()


def _list_suggestion_rows(session: Session, review_id: int) -> list[WeeklyReviewSuggestion]:
    return session.execute(
        select(WeeklyReviewSuggestion)
        .where(WeeklyReviewSuggestion.review_id == review_id)
        .order_by(WeeklyReviewSuggestion.seq, WeeklyReviewSuggestion.id)
    ).scalars().all()


def suggestion_to_dict(row: WeeklyReviewSuggestion) -> dict:
    try:
        basis = json.loads(row.basis_json or "[]")
    except json.JSONDecodeError:
        basis = []
    return {
        "id": row.id,
        "review_id": row.review_id,
        "seq": row.seq,
        "content": row.content,
        "basis": basis,
        "is_general": not basis,  # 无有效依据 = 一般性建议（展示标记）
        "status": row.status,
        "final_content": row.final_content,
        "reject_reason": row.reject_reason,
        "resolved_at": row.resolved_at,
    }


def list_suggestions(session: Session, review_id: int) -> list[dict]:
    get_review(session, review_id)
    return [suggestion_to_dict(row) for row in _list_suggestion_rows(session, review_id)]


def resolve_suggestion(
    session: Session,
    suggestion_id: int,
    action: str,
    *,
    final_content: str | None = None,
    reject_reason: str = "",
) -> dict:
    """建议人工处置：accept（终稿=原文）/ modify（终稿必填）/ reject（可附理由）。"""
    if action not in SUGGESTION_ACTIONS:
        raise DomainError(f"非法处置动作: {action}", code="invalid_action", status_code=400)
    row = session.get(WeeklyReviewSuggestion, suggestion_id)
    if row is None:
        raise NotFoundError(f"建议不存在: {suggestion_id}")
    review = get_review(session, row.review_id)
    ensure_editable(review)

    if action == "accept":
        row.status = "accepted"
        row.final_content = row.content
        row.reject_reason = ""
    elif action == "modify":
        text = (final_content or "").strip()
        if not text:
            raise DomainError("修改后的建议内容不能为空", code="empty_final", status_code=422)
        row.status = "modified"
        row.final_content = text[:2000]
        row.reject_reason = ""
    else:
        row.status = "rejected"
        row.final_content = None
        row.reject_reason = (reject_reason or "").strip()[:500]
    row.resolved_at = _now()
    session.commit()
    return suggestion_to_dict(row)


# ---------- 确认保存（正式周报） ----------


def build_report_md(review: WeeklyReview, suggestions: list[WeeklyReviewSuggestion]) -> str:
    """周报正文由确定性代码组装：统计快照 + 分析正文 + 用户补充 + 已处置建议。"""
    try:
        stats = json.loads(review.stats_json or "{}")
    except json.JSONDecodeError:
        stats = {}
    tasks = stats.get("tasks", {})
    belonging = tasks.get("belonging", {})
    lines = [
        f"# 每周回顾（{review.week_start} ~ {review.week_end}）",
        "",
        "## 本周事实统计",
        f"- 本周归属任务：{belonging.get('total', 0)} 项，完成 {belonging.get('done', 0)} 项",
        f"- 本周标记完成任务：{tasks.get('done_in_week', {}).get('total', 0)} 项"
        f"（含清掉的历史任务 {tasks.get('done_in_week', {}).get('carried_in_done', {}).get('total', 0)} 项）",
        f"- 周末仍逾期/积压：{tasks.get('overdue_at_week_end', {}).get('total', 0)} 项",
        f"- 本周新建任务：{tasks.get('created_in_week', 0)} 项",
        f"- 长期计划：活动 {stats.get('plans', {}).get('active', {}).get('total', 0)} 项，"
        f"本周完成 {len(stats.get('plans', {}).get('completed_in_week', []))} 项",
        f"- 随手备忘：{stats.get('memos', {}).get('total', 0)} 条（搁置 {stats.get('memos', {}).get('stale', 0)} 条）",
        f"- 阅读：在读 {len(stats.get('reading', {}).get('reading', []))} 本，"
        f"本周新增笔记 {stats.get('reading', {}).get('notes_added_in_week', 0)} 份",
        "",
        "## 分析",
        review.analysis_md or "（无）",
        "",
        "## 用户补充",
        review.user_notes or "（无）",
        "",
        "## 下周建议（已处置）",
    ]
    accepted = [s for s in suggestions if s.status in ("accepted", "modified")]
    rejected = [s for s in suggestions if s.status == "rejected"]
    for index, row in enumerate(accepted, start=1):
        marker = "（已修改）" if row.status == "modified" else ""
        lines.append(f"{index}. {row.final_content or row.content}{marker}")
    if rejected:
        lines.append("")
        lines.append("### 未采纳的建议")
        for row in rejected:
            reason = f"——拒绝理由：{row.reject_reason}" if row.reject_reason else ""
            lines.append(f"- {row.content}{reason}")
    return "\n".join(lines)


def confirm_review(
    session: Session,
    review_id: int,
    *,
    analysis_md: str | None = None,
    user_notes: str | None = None,
) -> dict:
    """确认保存正式周报。校验：草稿态 + 全部建议已处置（无 pending）。

    同周重复确认由部分唯一索引兜底（IntegrityError → 409）。
    """
    review = get_review(session, review_id)
    ensure_editable(review)
    if analysis_md is not None:
        review.analysis_md = analysis_md
    if user_notes is not None:
        review.user_notes = user_notes

    suggestions = _list_suggestion_rows(session, review.id)
    pending = [row for row in suggestions if row.status == "pending"]
    if pending:
        raise DomainError(
            f"还有 {len(pending)} 条建议未处置（接受/修改/拒绝）后才能确认周报",
            code="suggestions_pending",
            status_code=409,
        )

    review.report_md = build_report_md(review, suggestions)
    review.status = "confirmed"
    review.confirmed_at = _now()
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise DomainError(
            f"{review.week_start} 本周已有正式周报，不可覆盖",
            code="confirmed_week_exists",
            status_code=409,
        ) from None
    return review_to_dict(review)
