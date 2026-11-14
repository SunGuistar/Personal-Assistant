"""启动诊断只写临时日志，不启动真实服务。"""
import json
import logging
import pytest


def test_stage_records_start_finish_and_failure(tmp_path, monkeypatch):
    from app import startup_timing as timing
    target = tmp_path / "startup.jsonl"
    monkeypatch.setenv("PH_STARTUP_TRACE", str(target))
    with timing.stage("测试初始化"):
        pass
    with pytest.raises(ValueError):
        with timing.stage("失败阶段"):
            raise ValueError("private body must not be logged")
    events = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]
    assert [e["status"] for e in events] == ["running", "success", "running", "failed"]
    assert events[1]["duration_s"] >= 0
    assert events[3]["error_type"] == "ValueError"
    assert "private body" not in target.read_text(encoding="utf-8")


def test_launcher_reports_stages_and_total(monkeypatch, tmp_path, caplog):
    from launcher import launch
    monkeypatch.setattr(launch.logger, "disabled", False)
    monkeypatch.setattr(launch.logger, "handlers", [caplog.handler])
    elapsed = [0.0]
    monkeypatch.setattr(launch.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(launch, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(launch, "service_ready", lambda url: elapsed[0] >= 3)
    def resolve():
        elapsed[0] += 1
        return ["fake"]
    monkeypatch.setattr(launch, "resolve_python_cmd", resolve)
    monkeypatch.setattr(launch, "start_service", lambda *a: type("Process", (), {"poll": lambda s: None})())
    monkeypatch.setattr(launch.time, "sleep", lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds))
    with caplog.at_level(logging.INFO):
        launch.ensure_service()
    assert "解释器检测" in caplog.text
    assert "启动总耗时" in caplog.text
    assert "3.00" in caplog.text


def test_trace_reader_keeps_partial_line_and_reports_failure(tmp_path, caplog, monkeypatch):
    from launcher import launch
    monkeypatch.setattr(launch.logger, "disabled", False)
    monkeypatch.setattr(launch.logger, "handlers", [caplog.handler])
    target = tmp_path / "trace.jsonl"
    event = json.dumps(dict(stage="test", status="failed", duration_s=1.25)).encode()
    target.write_bytes(event)
    assert launch.read_startup_events(target, 0) == 0
    with target.open("ab") as output:
        output.write(b"\n")
    with caplog.at_level(logging.INFO):
        assert launch.read_startup_events(target, 0) == len(event) + 1
    assert "test" in caplog.text and "1.25" in caplog.text


def test_backend_trace_is_passed_only_to_child(tmp_path, monkeypatch):
    import os
    from launcher import launch
    monkeypatch.setattr(launch, "ROOT_DIR", tmp_path)
    ready = iter([False, True])
    monkeypatch.setattr(launch, "service_ready", lambda url: next(ready))
    monkeypatch.setattr(launch, "resolve_python_cmd", lambda: ["fake"])
    monkeypatch.setenv("PH_STARTUP_TRACE", "original")
    def start(*args):
        assert args[0] == tmp_path / "launcher" / "logs"
        trace = os.environ["PH_STARTUP_TRACE"]
        assert trace != "original"
        assert str(tmp_path) in trace
        return type("Process", (), {"poll": lambda s: None})()
    monkeypatch.setattr(launch, "start_service", start)
    launch.ensure_service()
    assert os.environ["PH_STARTUP_TRACE"] == "original"


def test_backend_hooks_emit_timing(app_settings, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from conftest import _run_alembic_upgrade
    from app.main import create_app
    _run_alembic_upgrade(app_settings.db_url)
    target = tmp_path / "backend.jsonl"
    monkeypatch.setenv("PH_STARTUP_TRACE", str(target))
    app = create_app(app_settings, defer_modules=False)
    with TestClient(app) as restarted:
        assert restarted.get("/api/health").status_code == 200
    app.state.engine.dispose()
    events = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]
    completed = [e for e in events if e["status"] == "success"]
    assert len(completed) >= 4
    assert all(e["duration_s"] >= 0 for e in completed)


def test_progress_window_runs_operation_without_real_service(monkeypatch):
    import tkinter as tk
    from launcher.progress_window import run_with_progress
    original = tk.Tk
    def hidden_window():
        root = original()
        root.withdraw()
        root.after(500, root.destroy)
        return root
    monkeypatch.setattr(tk, "Tk", hidden_window)
    assert run_with_progress(lambda: 0) == 0
