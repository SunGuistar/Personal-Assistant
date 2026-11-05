"""清理审核业务编排（阶段 5，D4）。

生命周期：ensure_review（周日触发/补发，幂等）→ generate_candidates（只读扫描）
→ confirm（复检 + 生成删除计划，明细落库，仍不删数据）→ execute（后台 job，
逐项状态机，断点可续）→ 审计。

安全要点（对应批准的调整）：
- 删除计划持久化消息区间/计数/chunk ID 与处置，执行不依赖"删完再查"；
- chunk 一律保守处置（全命中才删；混合/保护/未知一律保留并记录原因）；
- 执行前逐组重新校验目标记录、保护日期与一致性；
- rag_state 以归一化库/Chroma 实际剩余数回写（与 incremental_index 判定兼容）；
- 与 wechat.sync 互斥（双向），重启后靠明细状态与陈旧任务清理恢复，不依赖进程内锁。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..exceptions import DomainError, NotFoundError
from ..models import (
    CleanupAudit,
    CleanupCandidate,
    CleanupDeleteItem,
    CleanupReview,
    Task,
)
from ..models.cleanup import CANDIDATE_STATES, ITEM_STATES, REVIEW_STATUS
from . import chroma_access, db_access
from .chroma_access import CHUNK_KIND_DELETE
from .db_access import normalized_db_path
from .protection import (
    day_bounds,
    is_cleanup_age,
    is_protected_date,
    week_sunday,
)
from ..wechat_agent.data_api.message_store import DEFAULT_DB_PATH as SNAPSHOT_DB_PATH

logger = logging.getLogger(__name__)

CHROMA_DIR = Path(__file__).resolve().parent.parent.parent / "GetWechatInfo" / "VectorStore" / "chroma_db"
KEEP_DAYS = 7


@dataclass
class CleanupPaths:
    snapshot: Path = SNAPSHOT_DB_PATH
    normalized: Path | None = None  # None → 经 WECHAT_AGENT_DB 约定解析
    chroma: Path = CHROMA_DIR

    def resolved(self) -> "CleanupPaths":
        return CleanupPaths(
            snapshot=self.snapshot,
            normalized=self.normalized or normalized_db_path(),
            chroma=self.chroma,
        )


# ---------- 审核周期 ----------

def ensure_review(
    session: Session,
    *,
    today: date,
    protected: list[str],
    paths: CleanupPaths | None = None,
    keep_days: int = KEEP_DAYS,
) -> CleanupReview | None:
    """周日（或错过周日后的首次启动）生成本周审核记录；同一 week_id 幂等。

    不覆盖此前尚未处理的审核周期：只补缺，不改动既有记录。
    """

    paths = (paths or CleanupPaths()).resolved()
    sunday = week_sunday(today)
    week_id = sunday.isoformat()
    existing = session.execute(
        select(CleanupReview).where(CleanupReview.week_id == week_id)
    ).scalars().first()
    if existing is not None:
        return existing

    # 真实聊天库不存在时（测试/新环境）不生成审核，避免空周期骚扰
    if not paths.normalized.exists():
        return None

    review = CleanupReview(week_id=week_id, status="pending")
    session.add(review)
    session.commit()
    session.refresh(review)
    generate_candidates(session, review, protected=protected, paths=paths, today=today, keep_days=keep_days)
    return review


def generate_candidates(
    session: Session,
    review: CleanupReview,
    *,
    protected: list[str],
    today: date,
    paths: CleanupPaths,
    keep_days: int = KEEP_DAYS,
) -> int:
    """只读扫描两库 + Chroma，按 (chat, date) 生成候选分组。无副作用。"""

    normalized_conn = db_access.connect_rw(paths.normalized)
    snapshot_conn = db_access.connect_rw(paths.snapshot) if paths.snapshot.exists() else None
    client = chroma_access.chroma_client(paths.chroma)
    chat_names: dict[str, str] = {}
    try:
        norm_groups = db_access.scan_message_groups(
            normalized_conn, table="messages", ts_column="timestamp", text_column="text"
        )
        snap_groups = (
            db_access.scan_message_groups(snapshot_conn, table="messages", ts_column="create_time")
            if snapshot_conn is not None
            else {}
        )
        chat_names = db_access.list_chats(normalized_conn)

        # 跨周去重：任何已生成过的 (chat_id, msg_date) 不重复进入新审核
        prior = session.execute(
            select(CleanupCandidate.chat_id, CleanupCandidate.msg_date)
        ).all()
        prior_keys = {(row.chat_id, row.msg_date) for row in prior}

        all_keys = sorted(set(norm_groups) | set(snap_groups))
        created = 0
        for chat_id, msg_date in all_keys:
            if is_protected_date(msg_date, protected):
                continue  # 保护日期整组不出现在候选中
            if not is_cleanup_age(msg_date, today, keep_days):
                continue
            if (chat_id, msg_date) in prior_keys:
                continue
            start, end = day_bounds(msg_date)
            dispositions = chroma_access.load_chunk_dispositions(
                client,
                chat_id=chat_id,
                msg_date=msg_date,
                day_start=start,
                day_end=end,
                normalized_connection=normalized_conn,
                protected=protected,
            )
            deletable = [d for d in dispositions if d.action == CHUNK_KIND_DELETE]
            kept = [d for d in dispositions if d.action != CHUNK_KIND_DELETE]
            norm_info = norm_groups.get((chat_id, msg_date), {"count": 0})
            snap_info = snap_groups.get((chat_id, msg_date), {"count": 0})
            candidate = CleanupCandidate(
                review_id=review.id,
                chat_id=chat_id,
                chat_name=chat_names.get(chat_id, ""),
                msg_date=msg_date,
                snapshot_count=int(snap_info["count"]),
                normalized_count=int(norm_info["count"]),
                chunk_delete_count=len(deletable),
                chunk_keep_count=len(kept),
                keep_reasons=json.dumps(
                    [{"chunk_id": d.chunk_id, "reason": d.reason} for d in kept], ensure_ascii=False
                ),
                size_estimate=int(norm_info.get("size", 0)),
                state="pending",
            )
            session.add(candidate)
            created += 1
        session.commit()
        return created
    finally:
        normalized_conn.close()
        if snapshot_conn is not None:
            snapshot_conn.close()


def list_reviews(session: Session) -> list[dict]:
    reviews = session.execute(
        select(CleanupReview).order_by(CleanupReview.week_id.desc())
    ).scalars().all()
    return [review_to_dict(session, review) for review in reviews]


def review_to_dict(session: Session, review: CleanupReview) -> dict:
    candidates = session.execute(
        select(CleanupCandidate).where(CleanupCandidate.review_id == review.id)
    ).scalars().all()
    return {
        "id": review.id,
        "week_id": review.week_id,
        "status": review.status,
        "confirmed_at": review.confirmed_at,
        "reviewed_at": review.reviewed_at,
        "candidates": [candidate_to_dict(c) for c in candidates],
    }


def candidate_to_dict(candidate: CleanupCandidate) -> dict:
    return {
        "id": candidate.id,
        "review_id": candidate.review_id,
        "chat_id": candidate.chat_id,
        "chat_name": candidate.chat_name,
        "msg_date": candidate.msg_date,
        "snapshot_count": candidate.snapshot_count,
        "normalized_count": candidate.normalized_count,
        "chunk_delete_count": candidate.chunk_delete_count,
        "chunk_keep_count": candidate.chunk_keep_count,
        "keep_reasons": json.loads(candidate.keep_reasons or "[]"),
        "size_estimate": candidate.size_estimate,
        "state": candidate.state,
        "error": candidate.error,
    }


def get_review(session: Session, review_id: int) -> CleanupReview:
    review = session.get(CleanupReview, review_id)
    if review is None:
        raise NotFoundError(f"审核记录不存在: {review_id}")
    return review


def dismiss_review(session: Session, review_id: int) -> dict:
    """稍后：仅隐藏提醒，不影响进入审核页，不结束周期。"""

    review = get_review(session, review_id)
    if review.status == "pending":
        review.status = "dismissed"
        session.commit()
    return review_to_dict(session, review)


def skip_review(session: Session, review_id: int) -> dict:
    review = get_review(session, review_id)
    if review.status in ("pending", "dismissed"):
        review.status = "skipped"
        from datetime import datetime

        review.reviewed_at = datetime.now().isoformat(timespec="seconds")
        session.commit()
    return review_to_dict(session, review)


def _audit(session: Session, review_id: int, item_type: str, count: int, status: str, error: str = "") -> None:
    session.add(
        CleanupAudit(review_id=review_id, item_type=item_type, count=count, status=status, error=error[:300])
    )
    session.commit()


# ---------- 确认与删除计划 ----------

def confirm_review(
    session: Session,
    review_id: int,
    candidate_ids: list[int],
    *,
    protected: list[str],
    paths: CleanupPaths | None = None,
) -> dict:
    """用户勾选 + 二次确认后：逐组复检并生成删除计划（明细落库，不删数据）。"""

    paths = (paths or CleanupPaths()).resolved()
    review = get_review(session, review_id)
    if not candidate_ids:
        raise DomainError("未选择任何候选分组", code="no_candidates", status_code=400)
    if review.confirmed_at:
        raise DomainError("该审核已确认，不能重复提交", code="review_conflicted", status_code=409)

    candidates = session.execute(
        select(CleanupCandidate).where(
            CleanupCandidate.review_id == review.id, CleanupCandidate.id.in_(candidate_ids)
        )
    ).scalars().all()
    if len(candidates) != len(candidate_ids):
        raise DomainError("候选分组与审核记录不一致", code="candidate_mismatch", status_code=409)

    normalized_conn = db_access.connect_rw(paths.normalized)
    client = chroma_access.chroma_client(paths.chroma)
    try:
        for candidate in candidates:
            _pre_execute_validate(candidate, normalized_conn, client, protected)
            start, end = day_bounds(candidate.msg_date)
            session.add(CleanupDeleteItem(
                review_id=review.id, candidate_id=candidate.id, kind="normalized",
                ref_id=f"{candidate.chat_id}:{candidate.msg_date}",
                detail=json.dumps({"start": start, "end": end, "expected": candidate.normalized_count}),
            ))
            session.add(CleanupDeleteItem(
                review_id=review.id, candidate_id=candidate.id, kind="snapshot",
                ref_id=f"{candidate.chat_id}:{candidate.msg_date}",
                detail=json.dumps({"start": start, "end": end, "expected": candidate.snapshot_count}),
            ))
            for d in _recompute_dispositions(candidate, normalized_conn, client, protected):
                if d.action == CHUNK_KIND_DELETE:
                    session.add(CleanupDeleteItem(
                        review_id=review.id, candidate_id=candidate.id, kind="chunk",
                        ref_id=d.chunk_id,
                        detail=json.dumps({"msg_count": d.msg_count, "date": candidate.msg_date}),
                    ))
        from datetime import datetime

        review.confirmed_at = datetime.now().isoformat(timespec="seconds")
        session.commit()
    finally:
        normalized_conn.close()
    return review_to_dict(session, review)


def _recompute_dispositions(candidate, normalized_conn, client, protected):
    start, end = day_bounds(candidate.msg_date)
    return chroma_access.load_chunk_dispositions(
        client,
        chat_id=candidate.chat_id,
        msg_date=candidate.msg_date,
        day_start=start,
        day_end=end,
        normalized_connection=normalized_conn,
        protected=protected,
    )


def _pre_execute_validate(candidate, normalized_conn, client, protected) -> None:
    """确认与执行前的双重校验：保护日期、记录一致性。"""

    if is_protected_date(candidate.msg_date, protected):
        candidate.state = "failed_protected"
        candidate.error = "该日期属于永久保护日期，拒绝删除"
        raise DomainError(candidate.error, code="protected_date", status_code=409)
    start, end = day_bounds(candidate.msg_date)
    live_norm = db_access.count_range(normalized_conn, "messages", candidate.chat_id, start, end)
    if live_norm != candidate.normalized_count:
        raise DomainError(
            f"候选数据已变化（归一化 {candidate.normalized_count} → {live_norm}），请重新生成候选",
            code="candidate_stale",
            status_code=409,
        )


def _validate_chunk_items(session, candidate, normalized_conn, client, protected) -> None:
    """执行前 chunk 逐项复检（此时归一化数据仍在，可精确解析归属）→ validated。"""

    dispositions = {d.chunk_id: d for d in _recompute_dispositions(candidate, normalized_conn, client, protected)}
    items = session.execute(
        select(CleanupDeleteItem).where(
            CleanupDeleteItem.candidate_id == candidate.id, CleanupDeleteItem.kind == "chunk"
        )
    ).scalars().all()
    collection = client.get_collection("chat_chunks")
    for item in items:
        if item.state in ("validated", "done"):
            continue
        live = collection.get(ids=[item.ref_id], include=["metadatas"])
        if not live["ids"]:
            raise DomainError(f"chunk {item.ref_id} 已不存在，数据不一致", code="chunk_missing", status_code=409)
        disposition = dispositions.get(item.ref_id)
        if disposition is None or disposition.action != CHUNK_KIND_DELETE:
            raise DomainError(
                f"chunk {item.ref_id} 处置结论变化（{disposition.reason if disposition else '不在范围内'}），已中止该组",
                code="chunk_changed",
                status_code=409,
            )
        item.state = "validated"
        item.detail = json.dumps({"msg_count": disposition.msg_count, "date": candidate.msg_date})
    session.commit()


# ---------- 执行（状态机，断点可续） ----------

def execute_review(
    session: Session,
    review_id: int,
    *,
    protected: list[str],
    paths: CleanupPaths | None = None,
) -> dict:
    review = get_review(session, review_id)
    if not review.confirmed_at:
        raise DomainError("该审核未经确认，拒绝执行删除", code="review_not_confirmed", status_code=409)

    paths = (paths or CleanupPaths()).resolved()
    normalized_conn = db_access.connect_rw(paths.normalized)
    snapshot_conn = db_access.connect_rw(paths.snapshot) if paths.snapshot.exists() else None
    client = chroma_access.chroma_client(paths.chroma)

    deleted = failed = 0
    try:
        # 只处理经确认（已有删除计划明细）的候选，未勾选的组绝不触碰
        confirmed_ids = session.execute(
            select(CleanupDeleteItem.candidate_id.distinct()).where(
                CleanupDeleteItem.review_id == review.id
            )
        ).scalars().all()
        candidates = session.execute(
            select(CleanupCandidate)
            .where(CleanupCandidate.id.in_(confirmed_ids or [0]))
            .order_by(CleanupCandidate.id)
        ).scalars().all()
        for candidate in candidates:
            if candidate.state == "deleted":
                deleted += 1
                continue
            try:
                _execute_candidate(session, candidate, normalized_conn, snapshot_conn, client, protected)
                deleted += 1
            except Exception as exc:  # 单组失败不扩大范围，继续其余组
                failed += 1
                message = f"{type(exc).__name__}: {exc}"[:300]
                if candidate.state != "failed_protected":
                    candidate.state = "failed"
                candidate.error = message
                session.commit()
                logger.warning("cleanup candidate %s failed: %s", candidate.id, message)

        from datetime import datetime

        review.status = "done"
        review.reviewed_at = datetime.now().isoformat(timespec="seconds")
        session.commit()
    finally:
        normalized_conn.close()
        if snapshot_conn is not None:
            snapshot_conn.close()

    result = {"deleted_groups": deleted, "failed_groups": failed}
    _audit(session, review.id, "execute", deleted, "success" if failed == 0 else "partial")
    if failed:
        _audit(session, review.id, "execute_failed", failed, "failed", "部分分组失败，可重试")
    return result


def _execute_candidate(session, candidate, normalized_conn, snapshot_conn, client, protected) -> None:
    """单组三层删除：validate → 归一化 → Chroma → 快照 → rag_state → done。幂等可续。"""

    if candidate.state != "validated":
        _pre_execute_validate(candidate, normalized_conn, client, protected)
        _validate_chunk_items(session, candidate, normalized_conn, client, protected)
        candidate.state = "validated"
        session.commit()

    start, end = day_bounds(candidate.msg_date)

    # ① 归一化（事务提交后立即落 item 状态；重试时 DELETE 幂等、计数校验容忍已删）
    norm_item = _layer_item(session, candidate, "normalized")
    if norm_item.state != "done":
        detail = json.loads(norm_item.detail or "{}")
        db_access.delete_range(normalized_conn, "messages", candidate.chat_id, start, end)
        remaining = db_access.count_range(normalized_conn, "messages", candidate.chat_id, start, end)
        if remaining not in (0,):
            raise DomainError(f"归一化删除校验失败：剩余 {remaining} 条", code="verify_failed", status_code=500)
        norm_item.state = "done"
        session.commit()

    # ② Chroma（仅删计划内且已 validated 的 chunk；保守策略无重建）
    chunk_items = session.execute(
        select(CleanupDeleteItem).where(
            CleanupDeleteItem.candidate_id == candidate.id, CleanupDeleteItem.kind == "chunk"
        )
    ).scalars().all()
    pending_chunks = [item.ref_id for item in chunk_items if item.state != "done"]
    if pending_chunks:
        if any(item.state != "validated" for item in chunk_items if item.ref_id in pending_chunks):
            raise DomainError("存在未复检的 chunk，拒绝删除", code="chunk_not_validated", status_code=409)
        chroma_access.delete_chunks(client, pending_chunks)
        for item in chunk_items:
            if item.ref_id in pending_chunks:
                item.state = "done"
        session.commit()

    # ③ 原始快照
    snap_item = _layer_item(session, candidate, "snapshot")
    if snap_item.state != "done" and snapshot_conn is not None:
        db_access.delete_range(snapshot_conn, "messages", candidate.chat_id, start, end, ts_column="create_time")
        snap_item.state = "done"
        session.commit()

    # ④ rag_state 以实际剩余数回写（与 incremental_index 的减少重建判定兼容）
    total_remaining = int(
        normalized_conn.execute(
            "select count(*) from messages where chat_id = ?", (candidate.chat_id,)
        ).fetchone()[0]
    )
    chroma_access.update_rag_state(client, chat_id=candidate.chat_id, total_msgs=total_remaining)

    candidate.state = "deleted"
    candidate.error = ""
    session.commit()
    _audit(session, candidate.review_id, "group_deleted", 1, "success",
           f"{candidate.chat_id} {candidate.msg_date} norm={candidate.normalized_count} chunks={len(chunk_items)}")


def _layer_item(session, candidate, kind: str) -> CleanupDeleteItem:
    item = session.execute(
        select(CleanupDeleteItem).where(
            CleanupDeleteItem.candidate_id == candidate.id, CleanupDeleteItem.kind == kind
        )
    ).scalars().first()
    if item is None:
        raise DomainError(f"删除计划缺少 {kind} 明细", code="plan_incomplete", status_code=500)
    return item


def retry_candidates(session, review_id: int, candidate_ids: list[int]) -> dict:
    """失败组重置（幂等重试需再次提交 execute）。

    已越过校验检查点（chunk 明细 validated）的组恢复到 validated 直接续跑，
    避免"数据已删 → 复检必然报 stale"的死锁；未越过校验的回到 pending 全量复检。
    """

    review = get_review(session, review_id)
    candidates = session.execute(
        select(CleanupCandidate).where(
            CleanupCandidate.review_id == review.id,
            CleanupCandidate.id.in_(candidate_ids),
            CleanupCandidate.state == "failed",
        )
    ).scalars().all()
    for candidate in candidates:
        validated = session.execute(
            select(CleanupDeleteItem.id).where(
                CleanupDeleteItem.candidate_id == candidate.id,
                CleanupDeleteItem.state == "validated",
            ).limit(1)
        ).first()
        candidate.state = "validated" if validated else "pending"
        candidate.error = ""
    session.commit()
    return {"reset": len(candidates)}


# ---------- 互斥与状态 ----------

ACTIVE_TASK_KINDS_BLOCKING_CLEANUP = ("wechat.sync",)
CLEANUP_TASK_KIND = "cleanup.execute"


def active_task_exists(session: Session, kinds: list[str]) -> bool:
    row = session.execute(
        select(Task.id).where(Task.kind.in_(kinds), Task.status.in_(["pending", "running"])).limit(1)
    ).first()
    return row is not None


def cleanup_status(session: Session) -> dict:
    reviews = session.execute(
        select(CleanupReview).order_by(CleanupReview.week_id.desc())
    ).scalars().all()
    latest = reviews[0] if reviews else None
    banner = None
    if latest is not None and latest.status in ("pending", "dismissed"):
        pending_count = session.execute(
            select(CleanupCandidate).where(
                CleanupCandidate.review_id == latest.id, CleanupCandidate.state == "pending"
            )
        ).scalars().all()
        banner = {
            "review_id": latest.id,
            "week_id": latest.week_id,
            "status": latest.status,
            "candidate_groups": len(pending_count),
        }
    return {
        "banner": banner,
        "reviews": [review_to_dict(session, r) for r in reviews[:5]],
    }
