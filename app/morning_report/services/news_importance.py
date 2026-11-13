"""新闻重要标记：按来源内容哈希同步同一新闻的采集副本。"""
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from ...exceptions import NotFoundError
from ..models import NewsItem, ReportVersion, NewsFavoriteSetting


def news_out(item: NewsItem) -> dict:
    return {"id": item.id, "title": item.title, "source_url": item.source_url,
            "category": item.category, "content_hash": item.content_hash, "is_important": bool(item.is_important)}


def report_news(mr: Session, version_id: int) -> list[dict]:
    version = mr.get(ReportVersion, version_id)
    if version is None:
        raise NotFoundError("报告不存在")
    selection = (version.sections or {}).get("news_selection") or {}
    ids = {item["id"] for rows in selection.values() if isinstance(rows, list)
           for item in rows if isinstance(item, dict) and isinstance(item.get("id"), int)}
    if not ids:
        return []
    return [news_out(row) for row in mr.execute(select(NewsItem).where(
        NewsItem.id.in_(ids)).order_by(NewsItem.id)).scalars()]


def set_importance(mr: Session, news_id: int, is_important: bool) -> dict:
    item = mr.get(NewsItem, news_id)
    if item is None:
        raise NotFoundError("新闻不存在")
    predicate = NewsItem.content_hash == item.content_hash if item.content_hash else NewsItem.id == news_id
    mr.execute(update(NewsItem).where(predicate).values(is_important=is_important))
    mr.commit()
    mr.refresh(item)
    return news_out(item)


def _news_key(item: NewsItem) -> str:
    return f"hash:{item.content_hash}" if item.content_hash else f"id:{item.id}"


def favorite_news(mr: Session) -> list[dict]:
    settings = {row.news_key: row for row in mr.scalars(select(NewsFavoriteSetting))}
    seen = set()
    items = []
    for item in mr.scalars(select(NewsItem).where(NewsItem.is_important.is_(True)).order_by(NewsItem.id.desc())):
        key = _news_key(item)
        if key in seen:
            continue
        seen.add(key)
        setting = settings.get(key)
        items.append({**news_out(item), "summary": item.summary, "note": setting.note if setting else "",
                      "is_highlighted": bool(setting and setting.is_highlighted)})
    return sorted(items, key=lambda row: (not row["is_highlighted"], -row["id"]))


def update_favorite(mr: Session, news_id: int, changes: dict) -> dict:
    item = mr.get(NewsItem, news_id)
    if item is None or not item.is_important:
        raise NotFoundError("收藏新闻不存在")
    key = _news_key(item)
    setting = mr.scalar(select(NewsFavoriteSetting).where(NewsFavoriteSetting.news_key == key))
    if setting is None:
        setting = NewsFavoriteSetting(news_key=key)
        mr.add(setting)
    for name, value in changes.items():
        setattr(setting, name, value)
    mr.commit()
    return {**news_out(item), "summary": item.summary, "note": setting.note, "is_highlighted": setting.is_highlighted}
