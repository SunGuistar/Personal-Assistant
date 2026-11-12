"""新闻重要标记：按来源内容哈希同步同一新闻的采集副本。"""
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from ...exceptions import NotFoundError
from ..models import NewsItem, ReportVersion


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
