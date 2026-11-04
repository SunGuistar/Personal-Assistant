"""资讯 API 集成测试（TestClient + respx Mock 外部源，零真实外网）。"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone

import httpx

HN_URL = "https://hn.algolia.com/api/v1/search"

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>T</title>
<entry><title>{title}</title><link href="{url}"/><updated>{updated}</updated>
<summary>digest</summary></entry>
</feed>"""


def _atom(title: str, url: str) -> httpx.Response:
    updated = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return httpx.Response(200, content=ATOM.format(title=title, url=url, updated=updated).encode("utf-8"))


def _hn_payload() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "hits": [
                {
                    "objectID": "9",
                    "title": "Launching a new agent framework",
                    "url": "https://acme.dev/agent-framework",
                    "points": 300,
                    "created_at_i": int(time.time()) - 3600,
                }
            ]
        },
    )


def _mock_sources(respx_mock, one_failing: bool = False) -> None:
    """按默认来源 endpoint 逐一 Mock；可选让一个源失败。"""
    from app.services.news_service import DEFAULT_SOURCES

    for seed in DEFAULT_SOURCES:
        if one_failing and seed["name"] == "Python Insider":
            respx_mock.get(seed["endpoint"]).mock(return_value=httpx.Response(500))
        elif seed["kind"] == "hn":
            respx_mock.get(re.compile(re.escape(HN_URL) + r".*")).mock(return_value=_hn_payload())
        else:
            title = f"{seed['name']} latest post"
            url = f"https://seed.example/{seed['name'].replace(' ', '-').lower()}"
            respx_mock.get(seed["endpoint"]).mock(return_value=_atom(title, url))


def _wait_job(client, task_id: int, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/jobs/{task_id}").json()
        if body["status"] in ("success", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"任务 {task_id} 超时未完成")


def _refresh_and_wait(client, timeout: float = 10.0) -> dict:
    accepted = client.post("/api/news/refresh", json={})
    assert accepted.status_code == 202
    return _wait_job(client, accepted.json()["task_id"], timeout=timeout)


def test_refresh_full_chain_dedup_and_top(fclient, respx_mock, monkeypatch):
    monkeypatch.setattr("app.adapters.news_common.time.sleep", lambda _s: None)
    _mock_sources(respx_mock)

    accepted = fclient.post("/api/news/refresh", json={})
    assert accepted.status_code == 202
    task_id = accepted.json()["task_id"]

    # 重复提交被 409 拒绝（同 kind 未完成）
    conflict = fclient.post("/api/news/refresh", json={})
    assert conflict.status_code == 409

    job = _wait_job(fclient, task_id)
    assert job["status"] == "success"
    assert job["result"]["new_items"] == 7  # 7 个默认来源各 1 条
    assert job["result"]["failures"] == []

    # 再次刷新：零新增、不重复
    job2 = _refresh_and_wait(fclient)
    assert job2["result"]["new_items"] == 0

    top = fclient.get("/api/news/top").json()
    assert top["total"] == 7
    assert [item["rank"] for item in top["items"]] == list(range(1, 8))
    # 多次请求排名稳定
    assert fclient.get("/api/news/top").json()["items"] == top["items"]

    status = fclient.get("/api/news/status").json()
    assert status["stale"] is False
    assert status["last_refresh"]["refreshed_at"]


def test_single_source_failure_keeps_others(fclient, respx_mock, monkeypatch):
    monkeypatch.setattr("app.adapters.news_common.time.sleep", lambda _s: None)
    _mock_sources(respx_mock, one_failing=True)

    job = _refresh_and_wait(fclient)
    assert job["status"] == "success"
    assert job["result"]["new_items"] == 6
    assert [f["source"] for f in job["result"]["failures"]] == ["Python Insider"]

    top = fclient.get("/api/news/top").json()
    assert top["total"] == 6  # 其余来源结果保留


def test_refresh_failure_retains_existing_cache(fclient, respx_mock, monkeypatch):
    """刷新失败后旧缓存仍可查询（TOP 10 不丢数据）。"""
    from app.services.news_service import DEFAULT_SOURCES

    monkeypatch.setattr("app.adapters.news_common.time.sleep", lambda _s: None)
    _mock_sources(respx_mock)
    _refresh_and_wait(fclient)
    before = fclient.get("/api/news/top").json()
    assert before["total"] > 0

    def _boom(self):
        raise httpx.ConnectTimeout("boom")

    # 用适配器层注入全部失败（respx 首次注册的路由优先，二次覆盖不可靠）
    monkeypatch.setattr("app.adapters.news_hn.HackerNewsAdapter.fetch", _boom)
    monkeypatch.setattr("app.adapters.news_rss.RssAdapter.fetch", _boom)

    job = _refresh_and_wait(fclient, timeout=30.0)
    assert job["status"] == "success"
    assert job["result"]["new_items"] == 0
    assert len(job["result"]["failures"]) == 7

    after = fclient.get("/api/news/top").json()
    assert after["items"] == before["items"]  # 旧缓存完整保留


def test_top_empty_cache(fclient):
    top = fclient.get("/api/news/top").json()
    assert top["total"] == 0 and top["items"] == []
    status = fclient.get("/api/news/status").json()
    assert status["stale"] is True  # 从未成功刷新 → 需要刷新
