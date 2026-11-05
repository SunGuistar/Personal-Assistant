"""确定性周统计单元测试（隔离临时库）：周期边界、完成时间 vs 归属日期、逾期口径。"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import Book, BookNote, DailyTask, ImportantInfo, LongTermPlan, Memo
from app.services import review_stats

# 2026-06-01 是周一：本周 06-01(一) ~ 06-07(日)
WEEK = "2026-06-01"
WEEK_END = "2026-06-07"


@pytest.fixture()
def session(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'stats.db'}"
    os.environ["PH_DATABASE_URL"] = db_url
    command.upgrade(Config(str(Path(__file__).resolve().parent.parent / "alembic.ini")), "head")
    engine = create_engine(db_url)
    factory = sessionmaker(bind=engine)
    with factory() as s:
        yield s
    engine.dispose()


def _task(session, task_date, title, *, done=0, completed_at=None, task_type="daily",
          is_important=0, created_at=None, moved_from_date=None):
    task = DailyTask(
        task_date=task_date,
        title=title,
        task_type=task_type,
        done=done,
        completed_at=completed_at,
        is_important=is_important,
        created_at=created_at or f"{task_date}T09:00:00",
        moved_from_date=moved_from_date,
    )
    session.add(task)
    session.flush()
    return task


# ---------- 周期边界 ----------


def test_week_bounds_normalizes_to_monday():
    assert review_stats.week_bounds("2026-06-03") == ("2026-06-01", "2026-06-07")
    assert review_stats.week_bounds("2026-06-07") == ("2026-06-01", "2026-06-07")


def test_week_bounds_cross_month():
    # 2026-06-29 周一，跨 6 月/7 月
    assert review_stats.week_bounds("2026-06-30") == ("2026-06-29", "2026-07-05")


def test_week_bounds_cross_year():
    # 2025-12-29 周一，跨 2025/2026
    assert review_stats.week_bounds("2026-01-01") == ("2025-12-29", "2026-01-04")


def test_default_review_week():
    # 周三（本周未结束）→ 上一个完整周
    assert review_stats.default_review_week(date(2026, 6, 3)) == "2026-05-25"
    # 周日（本周当天才结束，尚未完整）→ 上一个完整周
    assert review_stats.default_review_week(date(2026, 6, 7)) == "2026-05-25"
    # 下周一 → 刚结束的这一周
    assert review_stats.default_review_week(date(2026, 6, 8)) == "2026-06-01"


# ---------- 任务统计口径 ----------


def test_done_in_week_uses_completed_at_not_task_date(session):
    # 归属上周，但本周才标记完成 → 计入"本周完成"，不算本周归属任务
    _task(session, "2026-05-28", "上周遗留", done=1, completed_at="2026-06-02T10:00:00")
    # 归属本周且本周完成
    _task(session, WEEK, "本周任务", done=1, completed_at="2026-06-03T10:00:00")
    # 归属本周，完成时间缺失（存量脏数据）→ 不计入完成周统计
    _task(session, WEEK, "未知完成时间", done=1, completed_at=None)

    stats = review_stats.weekly_task_stats(session, WEEK)
    assert stats["belonging"]["total"] == 2
    assert stats["belonging"]["done"] == 2  # done 标志位仍在
    assert stats["done_in_week"]["total"] == 2  # NULL completed_at 不算
    assert stats["done_in_week"]["belonging_to_week"] == 1
    carried = stats["done_in_week"]["carried_in_done"]
    assert carried["total"] == 1 and carried["items"][0]["title"] == "上周遗留"


def test_overdue_at_week_end_snapshot(session):
    # 周日结束时未完成 → 逾期（含历史积压）
    _task(session, "2026-05-20", "历史积压", done=0)
    _task(session, WEEK, "本周未办", done=0)
    # 本周任务但下周一才完成 → 周末快照口径仍算逾期
    _task(session, WEEK, "拖到下周完成", done=1, completed_at="2026-06-08T09:00:00")
    # 本周内完成 → 不逾期
    _task(session, WEEK, "按时完成", done=1, completed_at="2026-06-05T18:00:00")
    # 未来周任务 → 不参与
    _task(session, "2026-06-15", "未来任务", done=0)

    overdue = review_stats.weekly_task_stats(session, WEEK)["overdue_at_week_end"]
    titles = {item["title"] for item in overdue["items"]}
    assert overdue["total"] == 3
    assert titles == {"历史积压", "本周未办", "拖到下周完成"}


def test_belonging_breakdown_by_type_and_important(session):
    _task(session, WEEK, "a", done=1, completed_at="2026-06-02T10:00:00")
    _task(session, WEEK, "b", task_type="feature_add")
    _task(session, WEEK, "c", task_type="idea", is_important=1)
    stats = review_stats.weekly_task_stats(session, WEEK)
    assert stats["belonging"]["by_type"]["daily"] == {"total": 1, "done": 1}
    assert stats["belonging"]["by_type"]["feature_add"] == {"total": 1, "done": 0}
    assert stats["belonging"]["important"] == {"total": 1, "done": 0}


def test_created_in_week(session):
    _task(session, WEEK, "新建", created_at="2026-06-04T12:00:00")
    _task(session, WEEK, "旧建", created_at="2026-05-01T12:00:00")
    assert review_stats.weekly_task_stats(session, WEEK)["created_in_week"] == 1


# ---------- 计划 / 备忘 / 重要信息 / 阅读 ----------


def test_plan_snapshot(session):
    active = LongTermPlan(title="进行中计划", goal="做出 MVP", target_date=WEEK_END)
    paused = LongTermPlan(title="搁置计划", status="on_hold")
    done = LongTermPlan(title="本周完成计划", status="completed", completed_at="2026-06-05T20:00:00")
    session.add_all([active, paused, done])
    session.commit()

    snapshot = review_stats.weekly_plan_snapshot(session, WEEK)
    assert snapshot["active"]["total"] == 2
    assert len(snapshot["target_date_in_week"]) == 1
    assert snapshot["target_date_in_week"][0]["title"] == "进行中计划"
    assert [p["title"] for p in snapshot["completed_in_week"]] == ["本周完成计划"]


def test_memo_stale_flag(session):
    fresh = Memo(title="新备忘", content="", updated_at="2026-06-03T10:00:00")
    stale = Memo(title="旧备忘", content="", updated_at="2026-05-01T10:00:00")
    session.add_all([fresh, stale])
    session.commit()

    snapshot = review_stats.memo_snapshot(session, WEEK)
    by_title = {item["title"]: item["stale"] for item in snapshot["items"]["items"]}
    assert by_title == {"新备忘": False, "旧备忘": True}
    assert snapshot["stale"] == 1


def test_important_info_titles(session):
    session.add_all([ImportantInfo(title="设计原则"), ImportantInfo(title="英语目标")])
    session.commit()
    snapshot = review_stats.important_info_snapshot(session)
    assert snapshot["total"] == 2
    assert snapshot["titles"] == ["设计原则", "英语目标"]


def test_reading_snapshot(session):
    reading = Book(title="在读", status="reading", updated_at="2026-06-03T10:00:00")
    done_book = Book(title="已读", status="done")
    todo = Book(title="待读", status="todo")
    session.add_all([reading, done_book, todo])
    session.flush()
    session.add(BookNote(book_id=reading.id, filename="n.png", path="reading_notes/1/n.png",
                         created_at="2026-06-04T10:00:00"))

    snapshot = review_stats.reading_snapshot(session, WEEK)
    assert snapshot["by_status"] == {"reading": 1, "done": 1, "todo": 1}
    assert [b["title"] for b in snapshot["reading"]] == ["在读"]
    assert snapshot["reading"][0]["note_count"] == 1
    assert snapshot["notes_added_in_week"] == 1
    assert [b["title"] for b in snapshot["updated_in_week"]] == ["在读"]


def test_weekly_stats_aggregates(session):
    _task(session, WEEK, "任务")
    session.add(LongTermPlan(title="计划"))
    session.commit()
    stats = review_stats.weekly_stats(session, WEEK)
    assert stats["week_start"] == WEEK and stats["week_end"] == WEEK_END
    assert stats["tasks"]["belonging"]["total"] == 1
    assert stats["plans"]["active"]["total"] == 1
