"""新闻展示快照：以 ID/字段为契约，不从模型 Markdown 推断新闻类别。"""
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..models import NewsItem, RunStage

CATEGORIES = ("domestic", "international", "ai")


def build_news_content(selection: dict, sources: list[dict], errors: dict | None = None) -> dict:
    by_id = {row["id"]: row for row in sources if isinstance(row.get("id"), int)}
    categories = {key: [] for key in CATEGORIES}
    for category in CATEGORIES:
        seen = set()
        selected_rows = selection.get(category, [])
        if not isinstance(selected_rows, list): continue
        for selected in selected_rows:
            if not isinstance(selected, dict) or not isinstance(selected.get("id"), int): continue
            news_id = selected["id"]
            if news_id in seen: continue
            seen.add(news_id)
            source = by_id.get(news_id, {})
            def value(key):
                return selected.get(key) or source.get(key) or ""
            title = value("title")
            if not title: continue
            categories[category].append({"id": news_id, "category": category, "title": str(title),
                "url": str(value("url") or value("source_url")), "summary": str(value("summary")),
                "section_label": str(value("section_label")), "published_at": value("published_at") or None})
    overview = []
    for category, label in (("domestic", "国内新闻"), ("international", "国外新闻"), ("ai", "AI新闻")):
        if categories[category]: overview.append({**categories[category][0], "display_type": label})
    overview.extend({**item, "display_type": "技巧与观点"} for item in categories["ai"]
                    if item["section_label"] in ("技巧与观点", "讨论与观点"))
    return {"version": 1, "categories": categories, "overview": overview,
            "errors": {key: str(value) for key, value in (errors or {}).items() if key in CATEGORIES and value}}


def display_sections(mr: Session, version) -> dict:
    """旧报告按已保存的所选 ID 只读补齐；不写回或修改历史正文。"""
    sections = dict(version.sections or {})
    if isinstance(sections.get("news_content"), dict) and sections["news_content"].get("version") == 1:
        return sections
    selection = sections.get("news_selection")
    if not isinstance(selection, dict) or not any(key in selection for key in CATEGORIES): return sections
    ids = {item["id"] for key in CATEGORIES for item in (selection.get(key) if isinstance(selection.get(key), list) else [])
           if isinstance(item, dict) and isinstance(item.get("id"), int)}
    rows = mr.execute(select(NewsItem).where(NewsItem.id.in_(ids))).scalars().all() if ids else []
    sources = [{"id": row.id, "title": row.title, "source_url": row.source_url, "summary": row.summary,
                "section_label": (row.raw_ref or {}).get("section_label", ""), "published_at": row.published_at} for row in rows]
    stage = mr.execute(select(RunStage).where(RunStage.run_id == version.run_id, RunStage.stage == "collect")).scalars().first()
    errors = (stage.data or {}).get("category_errors", {}) if stage else {}
    sections["news_content"] = build_news_content(selection, sources, errors)
    return sections
