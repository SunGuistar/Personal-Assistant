# -*- coding: utf-8 -*-
"""阶段 1 验收：晨报独立库迁移、Memory CRUD API、hub 只读上下文、hub 零写入。"""

from __future__ import annotations

from sqlalchemy import inspect, select, text

from app.morning_report import db as mr_db
from app.morning_report.models import Memory, RunRecord

CORE_TABLES = {
    "run_records", "run_logs", "news_items", "event_groups", "report_versions",
    "evaluations", "memories", "stage_cache", "embedding_cache", "index_state",
    "token_usage", "personal_event_snapshots",
}


def test_mr_migrations_create_all_tables(fclient):
    engine = fclient.app.state.mr_engine
    assert mr_db.current_version(engine) == len(mr_db.MIGRATIONS)  # v1 核心表 + v2 run_stages
    tables = set(inspect(engine).get_table_names())
    assert CORE_TABLES <= tables and "run_stages" in tables
    # 幂等：再跑一次不报错、不产生新版本
    assert mr_db.run_migrations(engine) == []
    assert mr_db.current_version(engine) == len(mr_db.MIGRATIONS)


def test_mr_db_isolated_from_hub(fclient):
    hub_engine = fclient.app.state.engine
    mr_engine = fclient.app.state.mr_engine
    assert mr_engine.url.database != hub_engine.url.database
    with mr_engine.connect() as conn:
        rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).all()
    names = {r[0] for r in rows}
    assert "long_term_plans" not in names  # hub 表不出现在晨报库


def test_memory_crud_api(fclient):
    created = fclient.post("/api/morning/memory", json={"kind": "interest", "content": "关注 AI Agent 框架"})
    assert created.status_code == 201
    mid = created.json()["id"]

    listed = fclient.get("/api/morning/memory").json()
    assert any(m["id"] == mid and m["kind"] == "interest" for m in listed)

    patched = fclient.patch(f"/api/morning/memory/{mid}", json={"enabled": False})
    assert patched.json()["enabled"] is False

    assert fclient.delete(f"/api/morning/memory/{mid}").status_code == 204
    assert fclient.get("/api/morning/memory").json() == []
    assert fclient.patch(f"/api/morning/memory/{mid}", json={"enabled": True}).status_code == 404
    assert fclient.post("/api/morning/memory", json={"kind": "bad_kind", "content": "x"}).status_code == 422


def test_status_endpoint(fclient):
    res = fclient.get("/api/morning/status")
    assert res.status_code == 200
    body = res.json()
    assert body["db_ok"] is True
    assert body["today_run"] is None
    assert body["news_counts"] == {"domestic": 0, "international": 0, "ai": 0}


def _hub_bytes(fclient):
    path = fclient.app.state.settings.db_url.replace("sqlite:///", "")
    with open(path, "rb") as fh:
        return fh.read()


def test_hub_readonly_context_and_zero_write(fclient):
    """hub 只读：写入测试数据后经晨报 API 读取，hub 库文件字节不变。"""

    factory = fclient.app.state.session_factory
    with factory() as s:
        s.execute(text(
            "INSERT INTO long_term_plans (title, description, goal, status, is_important, sort_order, created_at, updated_at)"
            " VALUES ('晨跑计划', 'desc', NULL, 'in_progress', 1, 0, '2026-11-01T00:00:00', '2026-11-01T00:00:00')"
        ))
        s.execute(text(
            "INSERT INTO daily_tasks (task_date, title, content, task_type, done, sort_order, is_important, created_at, updated_at)"
            " VALUES ('2026-11-09', '读论文', NULL, 'daily', 1, 0, 0, '2026-11-09T08:30:00', '2026-11-09T08:30:00')"
        ))
        s.commit()

    before = _hub_bytes(fclient)
    res = fclient.get("/api/morning/personal_context", params={"report_date": "2026-11-10"})
    assert res.status_code == 200
    body = res.json()
    assert body["window_start"] == "2026-11-09T08:00:00"
    assert body["window_end"] == "2026-11-10T08:00:00"
    assert any(p["title"] == "晨跑计划" for p in body["longterm_highlight"])
    # completed_at 为 NULL → 不算窗口内完成（无时间证据不推断）
    assert body["daily_done"] == []
    after = _hub_bytes(fclient)
    assert before == after, "hub.db 发生了写变化（晨报模块必须只读）"


def test_window_for_helper():
    from app.morning_report.services.hub_readonly import window_for

    start, end = window_for("2026-11-10")
    assert (start, end) == ("2026-11-09T08:00:00", "2026-11-10T08:00:00")
