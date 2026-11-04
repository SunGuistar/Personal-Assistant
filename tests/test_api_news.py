"""资讯 API 集成测试（TestClient + respx Mock 外部源，零真实外网）。"""

from __future__ import annotations

import re
import time

import httpx

HN_URL = "https://hn.algolia.com/api/v1/search"

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>T</title>
<entry><title>{title}</title><link href="{url}"/><updated>2026-11-09T08:00:00Z</updated>
<summary>digest</summary></entry>
</feed>"""


def _atom(title: str, url: str) -> httpx.Response:
    return httpx.Response(200, content=ATOM.format(title=title, url=url).encode("utf-8"))


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
                    "created_at_i": 1762416000,
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


def _refresh_and_wait(client) -> dict:
    accepted = client.post("/api/news/refresh", json={})
    assert accepted.status_code == 202
    return _wait_job(client, accepted.json()["task_id"])


def test_sources_seed_and_crud(fclient):
    sources = fclient.get("/api/news/sources").json()
    assert len(sources) == 7
    assert {s["kind"] for s in sources} == {"rss", "hn"}

    created = fclient.post(
        "/api/news/sources",
        json={"name": "Test Feed", "kind": "rss", "endpoint": "https://t.example/feed"},
    )
    assert created.status_code == 201
    source_id = created.json()["id"]

    patched = fclient.patch(f"/api/news/sources/{source_id}", json={"enabled": False, "weight": 2.0})
    assert patched.json()["enabled"] is False and patched.json()["weight"] == 2.0

    dup = fclient.post(
        "/api/news/sources", json={"name": "Test Feed", "kind": "rss", "endpoint": "https://x.example/feed"}
    )
    assert dup.status_code == 409


def test_refresh_full_chain_and_dedup(fclient, respx_mock, monkeypatch):
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

    listing = fclient.get("/api/news/items?sort=latest&page_size=50").json()
    assert listing["total"] == 7

    # 再次刷新：零新增、不重复
    job2 = _refresh_and_wait(fclient)
    assert job2["result"]["new_items"] == 0
    assert fclient.get("/api/news/items").json()["total"] == 7

    status = fclient.get("/api/news/status").json()
    assert status["stale"] is False
    assert status["last_refresh"]["refreshed_at"]


def test_single_source_failure_keeps_others(fclient, respx_mock, monkeypatch):
    monkeypatch.setattr("app.adapters.news_common.time.sleep", lambda _s: None)
    _mock_sources(respx_mock, one_failing=True)

    job = _refresh_and_wait(fclient)
    assert job["status"] == "success"
    assert job["result"]["new_items"] == 6  # 7 个默认来源中 1 个失败，其余 6 个各 1 条
    assert [f["source"] for f in job["result"]["failures"]] == ["Python Insider"]

    listing = fclient.get("/api/news/items").json()
    assert listing["total"] == 6  # 其余来源结果保留


def test_item_filters_and_state(fclient, respx_mock, monkeypatch):
    monkeypatch.setattr("app.adapters.news_common.time.sleep", lambda _s: None)
    _mock_sources(respx_mock)
    _refresh_and_wait(fclient)

    items = fclient.get("/api/news/items?page_size=50").json()["items"]
    hn_item = next(i for i in items if i["source"] == "Hacker News")
    assert hn_item["is_read"] is False

    # 收藏 + 已读
    patched = fclient.patch(f"/api/news/items/{hn_item['id']}", json={"is_favorite": True, "is_read": True})
    assert patched.json()["is_favorite"] is True and patched.json()["is_read"] is True

    fav = fclient.get("/api/news/items?favorite=true").json()
    assert fav["total"] == 1
    unread = fclient.get("/api/news/items?unread=true").json()
    assert all(not i["is_read"] for i in unread["items"])

    by_source = fclient.get("/api/news/items?source=Hacker%20News").json()
    assert by_source["total"] == 1
    by_topic = fclient.get("/api/news/items?topic=agent").json()
    assert by_topic["total"] >= 1

    # 重复刷新后收藏/已读状态保留
    _refresh_and_wait(fclient)
    kept = fclient.get("/api/news/items?favorite=true").json()
    assert kept["items"][0]["is_read"] is True


def test_refresh_timeout_failure_recorded(fclient, respx_mock, monkeypatch):
    monkeypatch.setattr("app.adapters.news_common.time.sleep", lambda _s: None)
    # 只保留 Hacker News 启用，其余禁用，避免触碰真实外网
    for source in fclient.get("/api/news/sources").json():
        if source["kind"] != "hn":
            fclient.patch(f"/api/news/sources/{source['id']}", json={"enabled": False})
    respx_mock.get(re.compile(r"https://hn\.algolia\.com/.*")).mock(side_effect=httpx.ConnectTimeout("boom"))

    job = _refresh_and_wait(fclient)
    assert job["status"] == "success"  # 任务本身成功：失败来源记录在结果里
    assert job["result"]["failures"], "应有失败来源记录"
    assert job["result"]["new_items"] == 0
