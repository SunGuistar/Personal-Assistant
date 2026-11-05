"""阶段 5：周日提醒/补提醒、周期去重、稍后/跳过、启动陈旧任务清理、同步互斥。"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.cleanup import service
from app.models import CleanupReview, Task

from cleanup_ref import CHAT, OLD_DATE, PROTECTED_DATE, build_env, make_messages

PROTECTED = [PROTECTED_DATE]


@pytest.fixture()
def hub(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'hub.db'}"
    os.environ["PH_DATABASE_URL"] = db_url
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config(str(Path(__file__).resolve().parent.parent / "alembic.ini")), "head")
    engine = create_engine(db_url)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        yield session
    engine.dispose()


@pytest.fixture()
def env(hub, tmp_path):
    messages = make_messages(CHAT, OLD_DATE, 3) + make_messages(CHAT, PROTECTED_DATE, 2)
    return build_env(tmp_path, messages)


# ---------- 周日触发与补提醒 ----------

def test_sunday_creates_review(hub, env):
    review = service.ensure_review(hub, today=date(2026, 11, 1), protected=PROTECTED, paths=env.paths)  # 周日
    assert review is not None and review.week_id == "2026-11-01" and review.status == "pending"


def test_same_week_idempotent(hub, env):
    r1 = service.ensure_review(hub, today=date(2026, 11, 1), protected=PROTECTED, paths=env.paths)
    r2 = service.ensure_review(hub, today=date(2026, 11, 7), protected=PROTECTED, paths=env.paths)  # 周六同一周
    assert r1.id == r2.id
    assert hub.execute(select(CleanupReview)).scalars().all().__len__() == 1


def test_missed_sunday_backfilled_on_next_start(hub, env):
    """周日未启动 → 下周三启动补发上一个周日的审核。"""
    review = service.ensure_review(hub, today=date(2026, 11, 4), protected=PROTECTED, paths=env.paths)  # 周三
    assert review.week_id == "2026-11-01"  # 最近周日（11-01 是周日，11-02 周一）


def test_no_duplicate_when_already_reviewed(hub, env):
    service.ensure_review(hub, today=date(2026, 11, 1), protected=PROTECTED, paths=env.paths)
    again = service.ensure_review(hub, today=date(2026, 11, 2), protected=PROTECTED, paths=env.paths)  # 周一，回到同一周日
    assert again.week_id == "2026-11-01"  # 同一周期不重复创建
    assert len(hub.execute(select(CleanupReview)).scalars().all()) == 1


def test_missed_sunday_only_creates_latest(hub, env):
    """周四启动：只为最近错过的周日补发，不补更早周期。"""
    r1 = service.ensure_review(hub, today=date(2026, 11, 4), protected=PROTECTED, paths=env.paths)
    assert r1.week_id == "2026-11-01"
    r2 = service.ensure_review(hub, today=date(2026, 11, 6), protected=PROTECTED, paths=env.paths)
    assert r2.id == r1.id  # 同一 missed 周日不重复（周五、周六都指向 11-01）


def test_does_not_overwrite_prior_pending_review(hub, env):
    old = service.ensure_review(hub, today=date(2026, 11, 1), protected=PROTECTED, paths=env.paths)
    new = service.ensure_review(hub, today=date(2026, 11, 8), protected=PROTECTED, paths=env.paths)
    assert old.id != new.id
    assert hub.get(CleanupReview, old.id).status == "pending"  # 旧周期未被覆盖
    assert hub.get(CleanupReview, new.id).week_id == "2026-11-08"


def test_no_review_when_normalized_db_missing(hub, tmp_path):
    result = service.ensure_review(
        hub, today=date(2026, 11, 1), protected=PROTECTED,
        paths=service.CleanupPaths(snapshot=tmp_path / "none.sqlite3", normalized=tmp_path / "none2.sqlite3", chroma=tmp_path / "c"),
    )
    assert result is None


# ---------- 稍后 / 跳过 / 状态 ----------

def test_dismiss_only_hides(hub, env):
    review = service.ensure_review(hub, today=date(2026, 11, 1), protected=PROTECTED, paths=env.paths)
    service.dismiss_review(hub, review.id)
    assert hub.get(CleanupReview, review.id).status == "dismissed"
    status = service.cleanup_status(hub)
    assert status["banner"]["review_id"] == review.id  # 稍后仍可进入审核页
    assert status["banner"]["status"] == "dismissed"


def test_skip_ends_cycle(hub, env):
    review = service.ensure_review(hub, today=date(2026, 11, 1), protected=PROTECTED, paths=env.paths)
    service.skip_review(hub, review.id)
    assert hub.get(CleanupReview, review.id).status == "skipped"
    assert service.cleanup_status(hub)["banner"] is None


def test_banner_shows_pending(hub, env):
    review = service.ensure_review(hub, today=date(2026, 11, 1), protected=PROTECTED, paths=env.paths)
    banner = service.cleanup_status(hub)["banner"]
    assert banner["review_id"] == review.id and banner["status"] == "pending"


def test_no_banner_when_zero_candidates(hub, tmp_path):
    """候选为 0（全部受保护/无过期数据）→ 不下发横幅；审核页仍可手动进入。"""
    messages = make_messages(CHAT, PROTECTED_DATE, 3)  # 全部受保护日期
    environment = build_env(tmp_path, messages)
    review = service.ensure_review(hub, today=date(2026, 11, 1), protected=PROTECTED, paths=environment.paths)
    status = service.cleanup_status(hub)
    assert status["banner"] is None
    # 审核记录仍在列表中（保留手动查看入口）
    assert any(r["id"] == review.id for r in status["reviews"])


def test_next_cycle_reevaluates_banner(hub, tmp_path):
    """跨周期重新评估：新日期达标进入新审核周期时横幅重新出现。

    （旧周期已出现过的 ref 按跨周去重不重复生成，已有专测覆盖。）
    """
    messages = make_messages(CHAT, PROTECTED_DATE, 2) + make_messages(CHAT, "2026-10-31", 3)
    environment = build_env(tmp_path, messages)

    # 第一周（11-01 周日）：10-31 的消息尚未满 7 天 → 无候选 → 无横幅
    first = service.ensure_review(hub, today=date(2026, 11, 1), protected=PROTECTED, paths=environment.paths)
    assert service.cleanup_status(hub)["banner"] is None

    # 第二周（11-08 周日）：10-31 已满 7 天（严格早于 11-01 边界）→ 新周期出现候选 → 重新提醒
    second = service.ensure_review(hub, today=date(2026, 11, 8), protected=PROTECTED, paths=environment.paths)
    banner = service.cleanup_status(hub)["banner"]
    assert banner is not None and banner["review_id"] == second.id and banner["status"] == "pending"
    assert first.id != second.id


# ---------- 启动陈旧任务清理（重启安全） ----------

def test_startup_marks_stale_tasks_failed(fclient):
    """进程重启后，遗留 running 任务被标记 failed，同 kind 不再被永久 409。"""
    with fclient.app.state.session_factory() as session:
        session.add(Task(kind="cleanup.execute", status="running", payload_json="{}", progress=50))
        session.commit()

    from fastapi.testclient import TestClient

    with TestClient(fclient.app):  # 再次进入启动钩子
        pass

    with fclient.app.state.session_factory() as session:
        task = session.execute(select(Task).where(Task.kind == "cleanup.execute")).scalar_one()
        assert task.status == "failed"
        assert "重启" in task.error


# ---------- 同步互斥 ----------

def _confirmed_review(fclient):
    with fclient.app.state.session_factory() as session:
        review = service.ensure_review(
            session, today=date.today(), protected=PROTECTED
        )
        review.confirmed_at = "2026-11-01T00:00:00"
        session.commit()
        return review.id


def test_execute_requires_confirm(fclient):
    with fclient.app.state.session_factory() as session:
        review = service.ensure_review(session, today=date.today(), protected=PROTECTED)
        rid = review.id
    response = fclient.post("/api/cleanup/execute", json={"review_id": rid})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "review_not_confirmed"


def test_execute_conflicts_with_running_sync(fclient):
    rid = _confirmed_review(fclient)
    with fclient.app.state.session_factory() as session:
        session.add(Task(kind="wechat.sync", status="running", payload_json="{}", progress=10))
        session.commit()
    response = fclient.post("/api/cleanup/execute", json={"review_id": rid})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "sync_conflict"


def test_wechat_sync_conflicts_with_running_cleanup(fclient):
    with fclient.app.state.session_factory() as session:
        session.add(Task(kind="cleanup.execute", status="running", payload_json="{}", progress=10))
        session.commit()
    response = fclient.post(
        "/api/wechat/sync",
        json={"chat_id": CHAT, "display_name": "x", "start": "2026-11-01", "end": "2026-11-02"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "cleanup_conflict"


def test_cleanup_status_endpoint(fclient):
    response = fclient.get("/api/cleanup/status")
    assert response.status_code == 200
    body = response.json()
    assert "banner" in body and "reviews" in body
