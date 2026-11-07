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

def test_task_ordering(session):
    a = _make_task(session, title="A")
    b = _make_task(session, title="B")
    c = _make_task(session, title="C")
    assert [t["id"] for t in tasks_service.list_daily(session, "2026-11-03")] == [
        a["id"], b["id"], c["id"],
    ]





def test_unfinished_task_carries_over(session):
    """未完成延续显示；逾期任务在后续日期勾选完成后，在完成日视图置底展示（不消失）。

    规则（PRD §2.3）：某日视图 = 当日全部 + 更早日期未完成 + 更早日期但"本日完成"
    的任务——完成动作发生在视图日，避免"勾完就从列表消失"。
    """

    from datetime import date, timedelta

    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    overdue = _make_task(session, date=yesterday, title="逾期")
    today_task = _make_task(session, date=today, title="今日")

    daily = tasks_service.list_daily(session, today)
    assert [t["id"] for t in daily] == [overdue["id"], today_task["id"]]

    # 逾期任务今日完成：留在今日视图置底（而非消失进历史）
    tasks_service.update_task(session, overdue["id"], {"done": True})
    daily = tasks_service.list_daily(session, today)
    assert [t["id"] for t in daily] == [today_task["id"], overdue["id"]]
    assert daily[-1]["done"] is True
    # 归属日期视图同样可见（当日全部任务口径）
    assert overdue["id"] in [t["id"] for t in tasks_service.list_daily(session, yesterday)]

    # 取消完成 → 回到未完成区，作为逾期延续排在最前
    tasks_service.update_task(session, overdue["id"], {"done": False})
    daily = tasks_service.list_daily(session, today)
    assert daily[0]["id"] == overdue["id"] and daily[0]["done"] is False


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
