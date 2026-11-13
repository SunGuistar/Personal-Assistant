"""收藏新闻的去重、独立重点标记及备注持久化（隔离临时库）。"""
from sqlalchemy import select
from app.morning_report.models import NewsItem, NewsFavoriteSetting


def test_favorites_dedupe_edit_and_independent_highlight(fclient):
    sf = fclient.app.state.mr_session_factory
    with sf() as mr:
        rows = [NewsItem(run_id=i, category="ai", title=title, content_hash=key, is_important=star)
                for i, title, key, star in [(1, "old", "same", True), (2, "new", "same", True),
                                           (3, "other", "other", True), (4, "ignored", "ignored", False)]]
        rows[1].summary = "新闻摘要"
        mr.add_all(rows); mr.commit()
        first, duplicate, other, ignored = [row.id for row in rows]
    url = "/api/morning/favorites"
    items = fclient.get(url).json()["items"]
    assert [item["id"] for item in items] == [other, duplicate]
    assert items[1]["summary"] == "新闻摘要"
    assert all(item["note"] == "" and not item["is_highlighted"] for item in items)
    assert fclient.patch(f"{url}/{first}", json={"note": "私人备注", "is_highlighted": True}).status_code == 200
    items = fclient.get(url).json()["items"]
    assert items[0]["id"] == duplicate and items[0]["note"] == "私人备注"
    assert items[0]["is_highlighted"] is True
    fclient.patch(f"{url}/{duplicate}", json={"is_highlighted": False})
    items = fclient.get(url).json()["items"]
    assert len(items) == 2 and items[1]["note"] == "私人备注"
    with sf() as mr:
        assert mr.get(NewsItem, duplicate).is_important is True
        assert len(mr.scalars(select(NewsFavoriteSetting)).all()) == 1
    for body in ({"title": "changed"}, {"category": "domestic"}, {"note": None}, {"is_highlighted": "false"}):
        assert fclient.patch(f"{url}/{first}", json=body).status_code == 422
    assert fclient.patch(f"{url}/{ignored}", json={"note": "no"}).status_code == 404
    assert fclient.patch(f"{url}/999999", json={"note": "no"}).status_code == 404
    fclient.patch(f"/api/morning/news/{first}/importance", json={"is_important": False})
    assert len(fclient.get(url).json()["items"]) == 1
    fclient.patch(f"/api/morning/news/{first}/importance", json={"is_important": True})
    assert fclient.get(url).json()["items"][1]["note"] == "私人备注"


def test_favorites_empty_and_no_hash_news_are_distinct(fclient):
    assert fclient.get("/api/morning/favorites").json() == {"items": []}
    with fclient.app.state.mr_session_factory() as mr:
        mr.add_all([NewsItem(run_id=1, category="domestic", title="same", is_important=True) for _ in range(2)])
        mr.commit()
    assert len(fclient.get("/api/morning/favorites").json()["items"]) == 2
