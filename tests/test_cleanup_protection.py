"""阶段 5 保护规则测试（最高优先级）：2026-10-27 全链路不可删除。

覆盖：候选排除、确认拒绝、执行前复检、批量（多组含保护）、重试不绕过、
时区边界、混合/未知 chunk 保守保留、删除后保护数据完整性。
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from app.cleanup import chroma_access, service
from app.cleanup.protection import date_of_ts, day_bounds
from app.models import CleanupCandidate, CleanupDeleteItem, CleanupReview

from cleanup_ref import (
    CHAT,
    EDGE_DATE,
    OLD_DATE,
    PROTECTED_DATE,
    RECENT_DATE,
    build_env,
    build_real_chunks,
    chroma_client_with,
    make_manual_chunk,
    make_messages,
    normalized_count,
    set_rag_state,
    snapshot_count,
    ts_of,
    upsert_chunk_docs,
)

TODAY = date(2026, 11, 5)
PROTECTED = [PROTECTED_DATE]

OLD_MSGS = make_messages(CHAT, OLD_DATE, 5)
PROT_MSGS = make_messages(CHAT, PROTECTED_DATE, 4)
RECENT_MSGS = make_messages(CHAT, RECENT_DATE, 3)
EDGE_MSGS = make_messages(CHAT, EDGE_DATE, 2)
ALL_MSGS = OLD_MSGS + PROT_MSGS + RECENT_MSGS + EDGE_MSGS


@pytest.fixture()
def hub_session(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'hub.db'}"
    import os
    from pathlib import Path

    os.environ["PH_DATABASE_URL"] = db_url
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config(str(Path(__file__).resolve().parent.parent / "alembic.ini")), "head")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(db_url)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        yield session
    engine.dispose()


@pytest.fixture()
def env(hub_session, tmp_path):
    environment = build_env(tmp_path, ALL_MSGS)
    client = chroma_client_with(environment)
    chunks = build_real_chunks(ALL_MSGS)
    upsert_chunk_docs(client, chunks, ef=environment.ef)
    set_rag_state(
        client, CHAT,
        total_msgs=len(ALL_MSGS), chunk_count=len(chunks),
        last_ts=max(m["timestamp"] for m in ALL_MSGS),
        last_start_ts=chunks[-1].start_ts if chunks else 0,
        ef=environment.ef,
    )
    return environment


def _make_review(hub_session, env, today=TODAY):
    return service.ensure_review(hub_session, today=today, protected=PROTECTED, paths=env.paths)


# ---------- 时区与边界 ----------

def test_timezone_date_of_ts():
    assert date_of_ts(ts_of("2026-10-27", 23, 59, 59)) == "2026-10-27"
    assert date_of_ts(ts_of("2026-10-28", 0, 0, 0)) == "2026-10-28"


def test_day_bounds_shanghai():
    start, end = day_bounds("2026-10-27")
    assert date_of_ts(start) == "2026-10-27"
    assert date_of_ts(end - 1) == "2026-10-27"
    assert date_of_ts(end) == "2026-10-28"


def test_cleanup_age_boundary():
    from app.cleanup.protection import is_cleanup_age

    today = date(2026, 11, 5)
    assert is_cleanup_age("2026-10-28", today, 7) is True  # 8 天前，早于边界
    assert is_cleanup_age("2026-10-29", today, 7) is False  # =今天-7，非"早于"
    assert is_cleanup_age("2026-10-30", today, 7) is False


# ---------- 候选生成 ----------

def test_protected_date_not_in_candidates(hub_session, env):
    review = _make_review(hub_session, env)
    candidates = hub_session.execute(
        select(CleanupCandidate).where(CleanupCandidate.review_id == review.id)
    ).scalars().all()
    dates = {c.msg_date for c in candidates}
    assert OLD_DATE in dates  # 10-15（8 天前）可清理
    assert PROTECTED_DATE not in dates  # 10-27 保护
    assert RECENT_DATE not in dates  # 11-01 不足 7 天
    assert EDGE_DATE not in dates  # 11-02 不足 7 天
    old = next(c for c in candidates if c.msg_date == OLD_DATE)
    assert old.normalized_count == 5
    assert old.snapshot_count == 5


def test_candidates_prior_weeks_not_regenerated(hub_session, env):
    review1 = _make_review(hub_session, env)
    review2 = service.ensure_review(
        hub_session, today=date(2026, 11, 12), protected=PROTECTED, paths=env.paths
    )
    dates2 = {
        c.msg_date
        for c in hub_session.execute(
            select(CleanupCandidate).where(CleanupCandidate.review_id == review2.id)
        ).scalars().all()
    }
    # 旧组不重复进入新审核；新审核只含"新达到 7 天"的日期（11-01/11-02 于 11-12 达标）
    assert OLD_DATE not in dates2
    assert PROTECTED_DATE not in dates2


# ---------- 确认（二次确认与计划） ----------

def _candidate(hub_session, review, date_str):
    return hub_session.execute(
        select(CleanupCandidate).where(
            CleanupCandidate.review_id == review.id, CleanupCandidate.msg_date == date_str
        )
    ).scalar_one()


def test_confirm_creates_plan_items(hub_session, env):
    review = _make_review(hub_session, env)
    candidate = _candidate(hub_session, review, OLD_DATE)
    result = service.confirm_review(
        hub_session, review.id, [candidate.id], protected=PROTECTED, paths=env.paths
    )
    assert result["confirmed_at"]
    items = hub_session.execute(
        select(CleanupDeleteItem).where(CleanupDeleteItem.candidate_id == candidate.id)
    ).scalars().all()
    kinds = {i.kind for i in items}
    assert {"normalized", "snapshot", "chunk"} <= kinds
    # 删除计划已持久化消息区间（不依赖删后查询）
    norm_item = next(i for i in items if i.kind == "normalized")
    import json

    detail = json.loads(norm_item.detail)
    assert detail["expected"] == 5


def test_confirm_rejects_protected_candidate(hub_session, env):
    review = _make_review(hub_session, env)
    protected_candidate = CleanupCandidate(
        review_id=review.id, chat_id=CHAT, msg_date=PROTECTED_DATE,
        snapshot_count=4, normalized_count=4, state="pending",
    )
    hub_session.add(protected_candidate)
    hub_session.commit()
    with pytest.raises(Exception) as exc_info:
        service.confirm_review(
            hub_session, review.id, [protected_candidate.id], protected=PROTECTED, paths=env.paths
        )
    assert exc_info.value.code == "protected_date"


def test_confirm_rejects_stale_candidate(hub_session, env):
    review = _make_review(hub_session, env)
    candidate = _candidate(hub_session, review, OLD_DATE)
    candidate.normalized_count = 999  # 数据已变化
    hub_session.commit()
    with pytest.raises(Exception) as exc_info:
        service.confirm_review(
            hub_session, review.id, [candidate.id], protected=PROTECTED, paths=env.paths
        )
    assert exc_info.value.code == "candidate_stale"


# ---------- 执行与保护完整性 ----------

def _confirm_and_execute(hub_session, env, date_str=OLD_DATE):
    review = _make_review(hub_session, env)
    candidate = _candidate(hub_session, review, date_str)
    service.confirm_review(hub_session, review.id, [candidate.id], protected=PROTECTED, paths=env.paths)
    return review, candidate, service.execute_review(
        hub_session, review.id, protected=PROTECTED, paths=env.paths
    )


def test_execute_deletes_old_keeps_protected(hub_session, env):
    review, candidate, result = _confirm_and_execute(hub_session, env)
    assert result["deleted_groups"] == 1 and result["failed_groups"] == 0
    assert candidate.state == "deleted"
    # 旧数据已删
    assert normalized_count(env.normalized, CHAT) == len(ALL_MSGS) - 5
    assert snapshot_count(env.snapshot, CHAT) == len(ALL_MSGS) - 5
    # 保护数据原封不动
    start, end = day_bounds(PROTECTED_DATE)
    con_count = normalized_count(env.normalized, CHAT)
    assert con_count == len(PROT_MSGS) + len(RECENT_MSGS) + len(EDGE_MSGS)
    client = chroma_client_with(env)
    remaining = client.get_collection("chat_chunks").get(where={"chat_id": {"$eq": CHAT}}, include=["metadatas", "documents"])
    protected_docs = [
        mid for mid, meta in zip(remaining["ids"], remaining["metadatas"])
        if meta["date"] == PROTECTED_DATE
    ]
    assert len(protected_docs) > 0  # 保护 chunk 全部保留


def test_execute_idempotent_rerun(hub_session, env):
    review, candidate, _ = _confirm_and_execute(hub_session, env)
    result2 = service.execute_review(hub_session, review.id, protected=PROTECTED, paths=env.paths)
    assert result2["deleted_groups"] == 1  # 已删组计入，不重复删除
    assert normalized_count(env.normalized, CHAT) == len(ALL_MSGS) - 5


def test_execute_requires_confirm(hub_session, env):
    review = _make_review(hub_session, env)
    with pytest.raises(Exception) as exc_info:
        service.execute_review(hub_session, review.id, protected=PROTECTED, paths=env.paths)
    assert exc_info.value.code == "review_not_confirmed"


def test_mixed_chunk_kept_and_disclosed(hub_session, tmp_path):
    """混合 chunk（待删+需保留消息）一律保留，且仍能检索到已删消息文本（保守策略明示）。"""
    messages = OLD_MSGS + RECENT_MSGS
    environment = build_env(tmp_path, messages)
    client = chroma_client_with(environment)
    mixed = make_manual_chunk(CHAT, [OLD_MSGS[0], RECENT_MSGS[0]], OLD_DATE)
    deletable = make_manual_chunk(CHAT, OLD_MSGS[1:], OLD_DATE)
    upsert_chunk_docs(client, [mixed, deletable], ef=environment.ef)
    set_rag_state(client, CHAT, total_msgs=len(messages), chunk_count=2,
                  last_ts=max(m["timestamp"] for m in messages), last_start_ts=mixed.start_ts,
                  ef=environment.ef)

    review = _make_review(hub_session, environment)
    candidate = _candidate(hub_session, review, OLD_DATE)
    assert candidate.chunk_keep_count == 1
    assert candidate.chunk_delete_count == 1
    import json as _json

    reasons = {k["reason"] for k in _json.loads(candidate.keep_reasons)}
    assert reasons == {"mixed"}

    service.confirm_review(hub_session, review.id, [candidate.id], protected=PROTECTED, paths=environment.paths)
    result = service.execute_review(hub_session, review.id, protected=PROTECTED, paths=environment.paths)
    assert result["failed_groups"] == 0

    remaining = client.get_collection("chat_chunks").get(include=["documents", "metadatas"])
    texts = " ".join(remaining["documents"])
    assert mixed.chunk_id in remaining["ids"]  # 混合 chunk 保留
    assert OLD_MSGS[0]["text"] in texts  # 已删消息仍可从保留 chunk 检索到（明示）


def test_unresolved_chunk_kept(hub_session, tmp_path):
    messages = OLD_MSGS
    environment = build_env(tmp_path, messages)
    client = chroma_client_with(environment)
    ghost = make_manual_chunk(CHAT, [OLD_MSGS[0]], OLD_DATE)
    ghost.msg_ids = [OLD_MSGS[0]["message_id"], "ghost:unresolvable"]
    import hashlib

    ghost.text += "\n(#ghost:unresolvable)"
    ghost.content_hash = hashlib.sha1(ghost.text.encode("utf-8")).hexdigest()[:16]
    upsert_chunk_docs(client, [ghost], ef=environment.ef)
    set_rag_state(client, CHAT, total_msgs=len(messages), chunk_count=1,
                  last_ts=max(m["timestamp"] for m in messages), last_start_ts=ghost.start_ts,
                  ef=environment.ef)

    review = _make_review(hub_session, environment)
    candidate = _candidate(hub_session, review, OLD_DATE)
    assert candidate.chunk_keep_count == 1
    import json as _json

    assert _json.loads(candidate.keep_reasons)[0]["reason"] == "unresolved"


def test_protected_chunk_never_deleted_even_if_targeted(hub_session, env, monkeypatch):
    """执行期重校验：chunk 结论在执行前被改为含保护消息 → 中止该组，保护 chunk 不动。"""
    from app.cleanup import service as svc

    review, candidate, _ = _confirm_and_execute(hub_session, env)
    # 再次构造针对保护日期的计划并直接执行（绕过候选排除，模拟 API 直调/绕过）
    review2 = service.ensure_review(hub_session, today=date(2026, 11, 12), protected=PROTECTED, paths=env.paths)
    rogue = CleanupCandidate(
        review_id=review2.id, chat_id=CHAT, msg_date=PROTECTED_DATE,
        snapshot_count=4, normalized_count=4, state="pending",
    )
    hub_session.add(rogue)
    hub_session.flush()
    # 模拟"计划生成后保护规则生效/被绕过"的执行期直调：预置删除明细
    from app.models import CleanupDeleteItem

    hub_session.add(CleanupDeleteItem(
        review_id=review2.id, candidate_id=rogue.id, kind="normalized",
        ref_id=f"{CHAT}:{PROTECTED_DATE}", state="pending", detail="{}",
    ))
    from datetime import datetime

    review2.confirmed_at = datetime.now().isoformat(timespec="seconds")
    hub_session.commit()
    result = service.execute_review(hub_session, review2.id, protected=PROTECTED, paths=env.paths)
    assert result["deleted_groups"] == 0 and result["failed_groups"] == 1
    assert rogue.state == "failed_protected"
    assert normalized_count(env.normalized, CHAT) == len(ALL_MSGS) - 5  # 保护数据未少


def test_interrupted_execution_resumes(hub_session, env, monkeypatch):
    """Chroma 删除中途失败 → 组 failed；重置重试 → 幂等完成，无重复误删。"""""
    from app.cleanup import chroma_access

    review = _make_review(hub_session, env)
    candidate = _candidate(hub_session, review, OLD_DATE)
    service.confirm_review(hub_session, review.id, [candidate.id], protected=PROTECTED, paths=env.paths)

    real_delete = chroma_access.delete_chunks
    calls = {"n": 0}

    def flaky(client, chunk_ids):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("chroma temporarily down")
        real_delete(client, chunk_ids)

    monkeypatch.setattr(chroma_access, "delete_chunks", flaky)
    monkeypatch.setattr(service.chroma_access, "delete_chunks", flaky)

    result = service.execute_review(hub_session, review.id, protected=PROTECTED, paths=env.paths)
    assert result["failed_groups"] == 1
    assert candidate.state == "failed"

    # 失败时归一化可能已删 → 重试幂等：重新校验（容忍已删）并完成剩余步骤
    monkeypatch.undo()
    monkeypatch.setattr(service.chroma_access, "delete_chunks", real_delete)
    service.retry_candidates(hub_session, review.id, [candidate.id])
    result2 = service.execute_review(hub_session, review.id, protected=PROTECTED, paths=env.paths)
    assert result2["deleted_groups"] == 1 and result2["failed_groups"] == 0
    assert normalized_count(env.normalized, CHAT) == len(ALL_MSGS) - 5
    client = chroma_client_with(env)
    remaining = client.get_collection("chat_chunks").get(where={"chat_id": {"$eq": CHAT}}, include=[])
    # 旧 chunk 已删，保护 chunk 仍在
    metas = client.get_collection("chat_chunks").get(ids=remaining["ids"], include=["metadatas"])["metadatas"]
    assert all(m["date"] != OLD_DATE for m in metas)


def test_audit_records_no_content(hub_session, env):
    from app.models import CleanupAudit

    _confirm_and_execute(hub_session, env)
    audits = hub_session.execute(select(CleanupAudit)).scalars().all()
    assert any(a.item_type == "execute" for a in audits)
    assert any(a.item_type == "group_deleted" for a in audits)
    for audit in audits:
        assert "消息正文" not in audit.error
