# -*- coding: utf-8 -*-
"""阶段 1 验收：晨报独立库迁移、已移除的 Memory API 与历史兼容、hub 只读上下文、hub 零写入。"""

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


def test_memory_api_removed_without_erasing_legacy_records(fclient):
    with fclient.app.state.mr_session_factory() as mr:
        legacy = Memory(kind="interest", content="历史偏好", enabled=True, confirmed=True)
        mr.add(legacy)
        mr.commit()
        memory_id = legacy.id
    for method, path, payload in (
        ("GET", "/api/morning/memory", None),
        ("POST", "/api/morning/memory", {"kind": "interest", "content": "新偏好"}),
        ("PATCH", f"/api/morning/memory/{memory_id}", {"enabled": False}),
        ("DELETE", f"/api/morning/memory/{memory_id}", None),
    ):
        # API 路由已移除；全站仅 GET 的 SPA 回退对其他方法返回 405。
        assert fclient.request(method, path, json=payload).status_code == (404 if method == "GET" else 405)
    with fclient.app.state.mr_session_factory() as mr:
        assert mr.get(Memory, memory_id).content == "历史偏好"
        assert mr.get(Memory, memory_id).enabled is True


def test_status_endpoint(fclient):
    res = fclient.get("/api/morning/status")
    assert res.status_code == 200
    body = res.json()
    assert body["db_ok"] is True
    from app.morning_report.db import current_version
    with fclient.app.state.mr_session_factory() as mr:
        assert body["mr_schema_version"] == current_version(mr.get_bind())
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
