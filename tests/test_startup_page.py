"""临时回环启动页测试，不启动业务应用或浏览器。"""
import json
import logging
from urllib.request import urlopen
from urllib.error import HTTPError
import pytest

from launcher.startup_page import StartupPage


def test_page_streams_progress_and_only_redirects_after_home_ready():
    logger = logging.getLogger("startup_page_test")
    logger.disabled = False
    logger.setLevel(logging.INFO)
    page = StartupPage(logger, "http://127.0.0.1:18620/")
    try:
        with urlopen(page.url, timeout=2) as response:
            assert "text/html" in response.headers["Content-Type"]
            assert b"location.replace" in response.read()
        logger.info("test phase complete")
        with urlopen(page.status_url, timeout=2) as response:
            status = json.load(response)
        assert status["status"] == "loading"
        assert "home_url" not in status
        assert "test phase complete" in status["messages"][-1]
        with pytest.raises(HTTPError) as error:
            urlopen(page.url.rsplit("/", 1)[0] + "/status", timeout=2)
        assert error.value.code == 404
        page.finish()
        with urlopen(page.status_url, timeout=2) as response:
            status = json.load(response)
        assert status["status"] == "ready"
        assert status["home_url"] == "http://127.0.0.1:18620/"
    finally:
        page.close()


def test_failed_startup_is_visible_without_redirect():
    page = StartupPage(logging.getLogger("startup_page_test"), "http://127.0.0.1:18620/")
    try:
        page.finish(error="test failure")
        with urlopen(page.status_url, timeout=2) as response:
            status = json.load(response)
        assert status["status"] == "failed"
        assert status["error"] == "test failure"
        assert "home_url" not in status
    finally:
        page.close()


def test_launcher_opens_startup_page_before_start_and_signals_ready(monkeypatch):
    import sys
    from launcher import launch, startup_page
    calls = []
    class FakePage:
        url = "http://127.0.0.1:12345/startup/test"
        def __init__(self, logger, home_url, **kwargs):
            assert home_url.startswith("http://127.0.0.1:")
        def finish(self, error=None):
            calls.append("failed" if error else "ready")
    monkeypatch.setattr(startup_page, "StartupPage", FakePage)
    monkeypatch.setattr(sys, "argv", ["launch.py", "--action", "restart"])
    monkeypatch.setattr(launch.webbrowser, "open", lambda url: calls.append("page") if url == FakePage.url else pytest.fail("must use startup page"))
    monkeypatch.setattr(launch, "stop_service", lambda: calls.append("stop"))
    monkeypatch.setattr(launch, "ensure_service", lambda: calls.append("home"))
    assert launch.main() == 0
    assert calls == ["page", "stop", "home", "ready"]
