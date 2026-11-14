"""启动分阶段：隔离数据库、阻塞假模块，禁止启动真实服务。"""
import threading
import time

from fastapi.testclient import TestClient


def test_real_morning_module_reaches_ready_and_serves_api(fclient):
    status = fclient.get("/api/startup").json()
    assert status["modules"]["morning"]["status"] == "ready", status
    response = fclient.get("/api/morning/status")
    assert response.status_code == 200, response.text


def test_home_available_while_module_loads_then_routes_publish(app_settings, monkeypatch):
    from conftest import _run_alembic_upgrade
    _run_alembic_upgrade(app_settings.db_url)
    from app import main
    from fastapi import FastAPI
    release = threading.Event()
    entered = threading.Event()

    def build(name, app, settings, session_factory):
        staged = FastAPI()
        if name == "morning":
            entered.set()
            assert release.wait(10)
            @staged.get("/api/morning/probe")
            def probe():
                return {"ok": True}
        return staged

    monkeypatch.setattr(main, "_build_optional_module", build)
    app = main.create_app(app_settings)
    try:
        with TestClient(app) as client:
            try:
                assert entered.wait(5)
                assert client.get("/api/health").status_code == 200
                assert client.get("/api/plans").status_code == 200
                assert client.get("/api/morning/probe").status_code == 503
                status = client.get("/api/startup").json()
                assert status["home_ready"] is True
                assert status["modules"]["morning"]["status"] == "loading"
            finally:
                release.set()
            for _ in range(200):
                if client.get("/api/startup").json()["modules"]["morning"]["status"] == "ready":
                    break
                time.sleep(.01)
            assert client.get("/api/morning/probe").json() == {"ok": True}
    finally:
        release.set()
        app.state.engine.dispose()


def test_failed_module_does_not_break_home(app_settings, monkeypatch):
    from conftest import _run_alembic_upgrade
    _run_alembic_upgrade(app_settings.db_url)
    from app import main
    from fastapi import FastAPI
    def build(name, *args):
        if name == "morning":
            raise ValueError("private error body")
        return FastAPI()
    monkeypatch.setattr(main, "_build_optional_module", build)
    app = main.create_app(app_settings, defer_modules=False)
    with TestClient(app) as client:
        status = client.get("/api/startup").json()
        assert status["modules"]["morning"]["status"] == "failed"
        assert "private error body" not in str(status)
        response = client.get("/api/morning/report")
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "module_failed"
        assert client.get("/api/health").status_code == 200
    app.state.engine.dispose()
