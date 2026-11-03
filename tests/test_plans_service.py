"""计划/任务 service 单元测试（隔离临时库，PRD §2.6）。"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from alembic.config import Config

from app.db import Base
from app.exceptions import DomainError, NotFoundError
from app.models import DailyTask, LongTermPlan
from app.services import plans_service, tasks_service


@pytest.fixture()
def session(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'unit.db'}"
    import os
    from pathlib import Path

    os.environ["PH_DATABASE_URL"] = db_url
    command.upgrade(Config(str(Path(__file__).resolve().parent.parent / "alembic.ini")), "head")
    engine = create_engine(db_url)
    factory = sessionmaker(bind=engine)
    with factory() as s:
        yield s
    engine.dispose()


def _make_plan(session, title="P1"):
    return plans_service.create_plan(session, title=title)


def _make_task(session, date="2026-11-03", title="T", plan_id=None):
    return tasks_service.create_task(session, task_date=date, title=title, plan_id=plan_id)


# ---------- 计划 ----------

def test_plan_crud_and_progress(session):
    plan = _make_plan(session)
    assert plan["progress"] == 0.0  # 无任务 = 0

    _make_task(session, plan_id=plan["id"])
    _make_task(session, plan_id=plan["id"])
    assert plans_service.get_plan(session, plan["id"])["progress"] == 0.0

    tasks = session.execute(select(DailyTask)).scalars().all()
    tasks_service.update_task(session, tasks[0].id, {"done": True})
    assert plans_service.get_plan(session, plan["id"])["progress"] == 0.5


def test_update_plan(session):
    plan = _make_plan(session)
    updated = plans_service.update_plan(
        session, plan["id"], {"status": "completed", "target_date": "2026-12-31"}
    )
    assert updated["status"] == "completed"
    assert updated["target_date"] == "2026-12-31"


def test_delete_plan_keeps_tasks_with_null_plan(session):
    plan = _make_plan(session)
    task = _make_task(session, plan_id=plan["id"])
    plans_service.delete_plan(session, plan["id"])
    with pytest.raises(NotFoundError):
        plans_service.get_plan(session, plan["id"])
    remaining = tasks_service.list_daily(session, task["task_date"])
    assert len(remaining) == 1
    assert remaining[0]["plan_id"] is None


def test_plan_not_found(session):
    with pytest.raises(NotFoundError):
        plans_service.get_plan(session, 9999)
    with pytest.raises(NotFoundError):
        plans_service.delete_plan(session, 9999)


# ---------- 任务 ----------

def test_task_ordering_and_reorder(session):
    a = _make_task(session, title="A")
    b = _make_task(session, title="B")
    c = _make_task(session, title="C")
    assert [t["id"] for t in tasks_service.list_daily(session, "2026-11-03")] == [
        a["id"], b["id"], c["id"],
    ]
    result = tasks_service.reorder_tasks(session, "2026-11-03", [c["id"], a["id"], b["id"]])
    assert [t["id"] for t in result] == [c["id"], a["id"], b["id"]]


def test_reorder_rejects_foreign_ids(session):
    a = _make_task(session, title="A")
    other = _make_task(session, date="2026-11-04", title="X")
    with pytest.raises(DomainError) as exc_info:
        tasks_service.reorder_tasks(session, "2026-11-03", [a["id"], other["id"]])
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "reorder_mismatch"


def test_move_task_semantics(session):
    task = _make_task(session, date="2026-11-03", title="T")
    moved = tasks_service.move_task(session, task["id"], "2026-11-04")
    assert moved["task_date"] == "2026-11-04"
    assert moved["moved_from_date"] == "2026-11-03"  # 溯源，不复制副本
    assert tasks_service.list_daily(session, "2026-11-03") == []
    assert len(tasks_service.list_daily(session, "2026-11-04")) == 1


def test_move_to_same_date_noop(session):
    task = _make_task(session)
    moved = tasks_service.move_task(session, task["id"], "2026-11-03")
    assert moved["moved_from_date"] is None


def test_task_done_toggle(session):
    task = _make_task(session)
    updated = tasks_service.update_task(session, task["id"], {"done": True})
    assert updated["done"] is True
    updated = tasks_service.update_task(session, task["id"], {"done": False})
    assert updated["done"] is False
