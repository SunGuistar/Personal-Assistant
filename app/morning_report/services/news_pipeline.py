"""采集管线：热榜为主、精选补充 → 窗口过滤 → 同事件代表合并 → 持久化。

规则（V0.6 §4.1 / V0.6.1 §4）：
- 按原始发布时间过滤 [window_start, window_end)；无可靠时间的热摸爽条目仅作线索（保留，不入窗口统计）。
- 新浪两类热榜各取前 20 条，中新精选每类最多补充 5 条；相同事件只保留代表，其余来源保留在元信息，不删除历史记录。
- 单源失败不阻塞整体：记录 run_logs 与覆盖缺口，run 状态 degraded；全部失败才 failed。
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..adapters import NewsCandidate
from ..adapters import aihot, chinanews, remoshuang, sina_hot
from ..adapters.article import fetch_article
from ..adapters.http_common import FetchError
from ..models import EventGroup, NewsItem, RunLog, RunRecord
from . import progress as progress_mod

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))
# 事件归组：标题字符 bigram Jaccard 阈值（保守偏高，宁可漏归不可误并）
EVENT_GROUP_THRESHOLD = 0.55
COLLECTION_STRATEGY = "hot_featured_v1"


def saved_category_counts(mr: Session, collect_run_id: int) -> dict[str, int]:
    """本次采集实际保存的分类计数（精确去重后，含无可靠时间的线索）。"""
    counts = {"domestic": 0, "international": 0, "ai": 0}
    counts.update(dict(mr.execute(
        select(NewsItem.category, func.count(NewsItem.id))
        .where(NewsItem.run_id == collect_run_id).group_by(NewsItem.category)
    ).all()))
    return counts


def _now() -> str:
    return datetime.now(CST).isoformat()


def log_run(mr: Session, run_id: int, stage: str, message: str,
            level: str = "info", detail: dict | None = None) -> None:
    mr.add(RunLog(run_id=run_id, stage=stage, level=level, message=message[:500], detail=detail))
    mr.commit()


def content_hash(title: str, source_url: str) -> str:
    norm = (title.strip().lower() + "|" + source_url.strip().lower()).encode("utf-8")
    return hashlib.sha1(norm).digest().hex()


def _bigrams(text: str) -> set[str]:
    t = "".join(ch for ch in text if not ch.isspace())
    return {t[i:i + 2] for i in range(len(t) - 1)} or ({t} if t else set())


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


def _group_events(mr: Session, items: list[NewsItem]) -> None:
    """同 category 内按标题相似度归组（保留独立记录，仅打组标）。"""

    by_cat: dict[str, list[NewsItem]] = {}
    for it in items:
        by_cat.setdefault(it.category, []).append(it)
    for cat, group_items in by_cat.items():
        reps: list[tuple[EventGroup, set[str]]] = []
        for it in group_items:
            grams = _bigrams(it.title)
            matched_idx = None
            for idx, (eg, egrams) in enumerate(reps):
                if _jaccard(grams, egrams) >= EVENT_GROUP_THRESHOLD:
                    matched_idx = idx
                    break
            if matched_idx is None:
                eg = EventGroup(category=cat, key_terms=sorted(grams)[:10])
                mr.add(eg)
                mr.flush()
                reps.append((eg, grams))
                it.event_group_id = eg.id
            else:
                eg, egrams = reps[matched_idx]
                reps[matched_idx] = (eg, egrams | grams)
                it.event_group_id = eg.id


def _in_window(published: str | None, start: str, end: str) -> bool:
    if not published:
        return False
    try:
        stamp = datetime.fromisoformat(published)
        return stamp.tzinfo is not None and datetime.fromisoformat(start) <= stamp < datetime.fromisoformat(end)
    except (TypeError, ValueError):
        return False


def collection_summary(mr: Session, run_id: int) -> dict:
    detail = mr.execute(select(RunLog.detail).where(
        RunLog.run_id == run_id, RunLog.stage == "collect",
        RunLog.message == "采集完成").order_by(RunLog.id.desc()).limit(1)).scalar()
    return detail or {}


def collection_is_current(mr: Session, run_id: int) -> bool:
    return collection_summary(mr, run_id).get("collection_strategy") == COLLECTION_STRATEGY


def _category_counts(items: list[NewsCandidate]) -> dict:
    return {cat: sum(i.category == cat for i in items) for cat in ("domestic", "international", "ai")}


def _same_event(a: NewsCandidate, b: NewsCandidate) -> bool:
    return (a.source_url.rstrip("/") == b.source_url.rstrip("/") or
            a.category in ("domestic", "international") and a.category == b.category and _jaccard(_bigrams(a.title), _bigrams(b.title)) >= EVENT_GROUP_THRESHOLD)


def _merge_candidates(items: list[NewsCandidate]) -> tuple[list[NewsCandidate], int]:
    # 时间可靠的新闻优先；同事件保留单一代表，将其余报道来源记在元信息。
    trusted = ("新华社", "新华网", "央视", "中国新闻网", "中新网", "人民日报")
    ordered = sorted(items, key=lambda i: (i.published_at is None,
        not any(name in i.source_name for name in trusted), not bool(i.summary),
        i.raw.get("selection_kind") == "featured", i.adapter == "remoshuang"))
    out = []
    merged = 0
    for item in ordered:
        representative = next((saved for saved in out if _same_event(saved, item)), None)
        if representative is not None:
            representative.raw.setdefault("related_sources", []).append({
                "source_name": item.source_name, "url": item.source_url, "title": item.title,
                "published_at": item.published_at, "summary": item.summary,
                "selection_kind": item.raw.get("selection_kind"), "rank": item.raw.get("rank")})
            merged += 1
            continue
        out.append(item)
    return out, merged


def run_collect(mr: Session, run_id: int, cancel_token=None) -> dict:
    """执行一期采集（run_record 已建好 pending）。返回覆盖摘要。

    cancel_token：源之间的协作式取消检查点（正在进行的 HTTP 请求自然完成后停止）。
    """

    from .cancel import GenerationCancelled, check_cancel

    run = mr.get(RunRecord, run_id)
    run.status = "running"
    run.started_at = _now()
    mr.commit()
    tracker = progress_mod.ProgressTracker(mr, run_id)
    tracker.stage_started("collect", f"窗口 {run.window_start[:16]} ~ {run.window_end[:16]}")
    log_run(mr, run_id, "collect", f"开始采集，窗口 {run.window_start} ~ {run.window_end}")

    sources = {
        "aihot": lambda: aihot.fetch_selected(),
        "sina_domestic": lambda: sina_hot.fetch_hot("domestic", run.run_date),
        "sina_international": lambda: sina_hot.fetch_hot("international", run.run_date),
        "chinanews": lambda: chinanews.fetch_featured(run.window_start, run.window_end,
                                                       cancel_check=lambda: check_cancel(cancel_token)),
        "remoshuang": lambda: (
            remoshuang.fetch_daily((datetime.fromisoformat(run.window_end) - timedelta(days=1)).date().isoformat())
            + remoshuang.fetch_daily(datetime.fromisoformat(run.window_end).date().isoformat())
        ),
    }

    candidates: list[NewsCandidate] = []
    failures: dict[str, str] = {}
    notes: list[str] = []
    per_source = {name: 0 for name in sources}
    for name, fn in sources.items():
        check_cancel(cancel_token)  # 安全检查点：用户停止则不再启动后续来源
        try:
            got = fn()
            per_source[name] = len(got)
            if any(i.raw.get("stale_rank") for i in got):
                notes.append(f"{name} 使用前一天的最近可用榜单，文章仍按本期发布时间过滤")
            if not got:
                notes.append(f"{name} 本期没有可用候选")
            if any(i.raw.get("featured_page_failures") for i in got):
                notes.append("中新网部分精选页面不可用")
            if name == "chinanews" and any(not i.summary for i in got):
                notes.append("中新网部分候选未取得正文摘录，仅保留标题与来源信息")
            if name.startswith("sina_"):
                detail_failed = 0
                for item in got:
                    check_cancel(cancel_token)
                    if item.published_at and not _in_window(item.published_at, run.window_start, run.window_end):
                        continue
                    try:
                        detail = fetch_article(item.source_url)
                        item.summary = detail["summary"]
                        if not item.summary:
                            detail_failed += 1
                            item.raw["detail_status"] = "missing"
                        if detail["published_at"]:
                            item.published_at = detail["published_at"]
                            item.raw["time_source"] = "article_page"
                    except FetchError:
                        detail_failed += 1
                        item.raw["detail_status"] = "failed"
                if detail_failed:
                    notes.append(f"{name} 有 {detail_failed} 条详情获取失败，保留榜单提供的时间与标题")
            candidates.extend(got)
            log_run(mr, run_id, "collect", f"{name} 获取 {len(got)} 条", detail={"adapter": name})
        except GenerationCancelled:
            raise
        except FetchError as exc:
            failures[name] = exc.reason
            log_run(mr, run_id, "collect", f"{name} 获取失败：{exc.reason}", level="warning")
        except Exception as exc:  # 解析等未预期错误同样降级记录
            failures[name] = f"{type(exc).__name__}: {exc}"
            log_run(mr, run_id, "collect", f"{name} 处理异常：{failures[name]}", level="warning")
    tracker.stage_progress("collect",
                           summary=f"已获取 {len(candidates)} 条候选",
                           data={"per_source": per_source, "raw_by_category": _category_counts(candidates)})
    # 窗口过滤（无时间线索保留但标记）
    windowed = [c for c in candidates if _in_window(c.published_at, run.window_start, run.window_end)]
    clues = [c for c in candidates if c.published_at is None]
    dropped = len(candidates) - len(windowed) - len(clues)

    # 无可靠时间仅作线索；国内/国际同事件只保存单一代表，其他来源进元信息。
    uniques, dup = _merge_candidates(windowed + clues)
    if clues:
        notes.append(f"{len(clues)} 条候选缺少可靠发布时间，仅保留为线索，不直接进入正文新闻")
    for source in failures:
        notes.append(f"{source} 获取失败，本期覆盖可能不足")
    for category, title in (("domestic", "国内"), ("international", "国际")):
        count = sum(i.category == category and i.published_at is not None for i in uniques)
        if count < 10:
            notes.append(f"{title}窗口内去重候选仅 {count} 条，不用旧闻或重复事件凑数")

    items = [
        NewsItem(
            run_id=run_id, category=c.category, title=c.title[:500], summary=c.summary,
            source_name=c.source_name, source_url=c.source_url, published_at=c.published_at,
            content_hash=content_hash(c.title, c.source_url),
            dedupe_status="unique", raw_ref={**c.raw, "adapter": c.adapter},
        )
        for c in uniques
    ]
    mr.add_all(items)
    mr.flush()
    _group_events(mr, items)
    mr.commit()

    summary = {
        "window": f"{run.window_start} ~ {run.window_end}",
        "per_source": per_source,
        "collection_strategy": COLLECTION_STRATEGY,
        "coverage_notes": notes,
        "raw_by_category": _category_counts(candidates),
        "windowed_by_category": _category_counts(windowed),
        "in_window": len(windowed),
        "clue_only": len(clues),
        "out_of_window_dropped": dropped,
        "duplicates_merged": dup,
        "saved_unique": len(items),
        "by_category": saved_category_counts(mr, run_id),
        "event_groups": len({i.event_group_id for i in items if i.event_group_id}),
        "source_failures": failures,
    }
    log_run(mr, run_id, "collect", "采集完成", detail=summary)
    tracker.stage_completed("collect",
                            summary=f"窗口内 {len(windowed)} 条，保存 {len(items)} 条",
                            data={"in_window": len(windowed), "saved": len(items),
                                  "by_category": summary["by_category"],
                                  "duplicates_merged": dup, "event_groups": summary["event_groups"],
                                  "source_failures": failures, "per_source": per_source,
                                  "coverage_notes": notes,
                                  "raw_by_category": summary["raw_by_category"],
                                  "windowed_by_category": summary["windowed_by_category"]})
    run.finished_at = _now()
    if len(failures) == len(sources) or not items:
        run.status = "failed"
        run.error = "全部来源获取失败或没有可保存候选"
    elif failures or notes:
        run.status = "degraded"
        run.error = "; ".join(notes)[:500]
    else:
        run.status = "success"
    mr.commit()
    return summary


def create_collect_run(mr: Session, report_date: str) -> RunRecord:
    end = datetime.fromisoformat(report_date).date()
    start = end - timedelta(days=1)
    run = RunRecord(
        run_date=report_date, kind="collect", status="pending",
        window_start=datetime(start.year, start.month, start.day, 8, 0, tzinfo=CST).isoformat(),
        window_end=datetime(end.year, end.month, end.day, 8, 0, tzinfo=CST).isoformat(),
    )
    mr.add(run)
    mr.commit()
    return run
