"""计划/任务 service 单元测试（隔离临时库，PRD §2.6）。"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from alembic.config import Config

from app.db import Base
from app.exceptions import DomainError, NotFoundError
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


def _make_task(session, date="2026-11-03", title="T"):
    return tasks_service.create_task(session, task_date=date, title=title)


# ---------- 计划 ----------

def test_plan_crud(session):
    plan = _make_plan(session)
    assert plan["status"] == "in_progress"
    assert plan["goal"] is None
    assert plans_service.get_plan(session, plan["id"])["id"] == plan["id"]


def test_plan_goal_clear(session):
    plan = plans_service.create_plan(session, title="英语", goal="每天阅读 20 分钟")
    assert plan["goal"] == "每天阅读 20 分钟"
    cleared = plans_service.update_plan(session, plan["id"], {"goal": ""})
    assert cleared["goal"] is None


def test_update_plan(session):
    plan = _make_plan(session)
    updated = plans_service.update_plan(
        session, plan["id"], {"status": "completed", "target_date": "2026-12-31"}
    )
    assert updated["status"] == "completed"
    assert updated["target_date"] == "2026-12-31"


def test_delete_plan_independent_from_tasks(session):
    """两模块完全独立：删除计划不涉及任何任务操作。"""
    plan = _make_plan(session)
    task = _make_task(session)
    plans_service.delete_plan(session, plan["id"])
    with pytest.raises(NotFoundError):
        plans_service.get_plan(session, plan["id"])
    assert len(tasks_service.list_daily(session, task["task_date"])) == 1


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


def test_unfinished_task_carries_over(session):
    """未完成任务在后续日期持续显示；已完成任务不跨日期（PRD §2.3）。"""

    overdue = _make_task(session, date="2026-11-02", title="逾期")
    done_prev = _make_task(session, date="2026-11-02", title="已完成")
    today = _make_task(session, date="2026-11-03", title="今日")
    tasks_service.update_task(session, done_prev["id"], {"done": True})

    daily = tasks_service.list_daily(session, "2026-11-03")
    assert [t["id"] for t in daily] == [overdue["id"], today["id"]]

    tasks_service.update_task(session, overdue["id"], {"done": True})
    assert [t["id"] for t in tasks_service.list_daily(session, "2026-11-03")] == [today["id"]]
    # 历史日期仍显示当日全部任务
    assert len(tasks_service.list_daily(session, "2026-11-02")) == 2


def test_task_done_toggle_clears_completed_at(session):
    """完成 ↔ 未完成可反复切换：完成记时间，取消完成清除并回到未完成区。"""
    task = _make_task(session)
    updated = tasks_service.update_task(session, task["id"], {"done": True})
    assert updated["done"] is True and updated["completed_at"]
    undone = tasks_service.update_task(session, task["id"], {"done": False})
    assert undone["done"] is False and undone["completed_at"] is None


def test_done_tasks_sort_to_bottom(session):
    """已完成置底：重要已完成也排在未完成的普通任务之后。"""
    normal = _make_task(session, title="普通")
    important_done = _make_task(session, title="重要已完成")
    tasks_service.update_task(session, important_done["id"], {"done": True, "is_important": True})
    daily = tasks_service.list_daily(session, "2026-11-03")
    assert daily[-1]["id"] == important_done["id"]
    assert daily[0]["id"] == normal["id"]
