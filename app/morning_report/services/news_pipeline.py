"""采集管线：多源获取 → 窗口过滤 → 精确去重 → 保守事件归组 → 持久化。

规则（V0.6 §4.1 / V0.6.1 §4）：
- 按原始发布时间过滤 [window_start, window_end)；无可靠时间的热摸爽条目仅作线索（保留，不入窗口统计）。
- 去重保守：同 hash 只保留首条（duplicate_merged 不另存）；同事件归组只打 event_group_id，不删原始记录。
- 单源失败不阻塞整体：记录 run_logs 与覆盖缺口，run 状态 degraded；全部失败才 failed。
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters import NewsCandidate
from ..adapters import aihot, chinanews, remoshuang
from ..adapters.http_common import FetchError
from ..models import EventGroup, NewsItem, RunLog, RunRecord

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))
# 事件归组：标题字符 bigram Jaccard 阈值（保守偏高，宁可漏归不可误并）
EVENT_GROUP_THRESHOLD = 0.55


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
    return published is not None and start <= published < end


def run_collect(mr: Session, run_id: int) -> dict:
    """执行一期采集（run_record 已建好 pending）。返回覆盖摘要。"""

    run = mr.get(RunRecord, run_id)
    run.status = "running"
    run.started_at = _now()
    mr.commit()
    log_run(mr, run_id, "collect", f"开始采集，窗口 {run.window_start} ~ {run.window_end}")

    sources = {
        "aihot": lambda: aihot.fetch_selected(),
        "chinanews": lambda: chinanews.fetch_window(
            (datetime.fromisoformat(run.window_end) - timedelta(days=1)).date().isoformat(),
            datetime.fromisoformat(run.window_end).date().isoformat(),
        ),
        "remoshuang": lambda: (
            remoshuang.fetch_daily((datetime.fromisoformat(run.window_end) - timedelta(days=1)).date().isoformat())
            + remoshuang.fetch_daily(datetime.fromisoformat(run.window_end).date().isoformat())
        ),
    }

    candidates: list[NewsCandidate] = []
    failures: dict[str, str] = {}
    for name, fn in sources.items():
        try:
            got = fn()
            candidates.extend(got)
            log_run(mr, run_id, "collect", f"{name} 获取 {len(got)} 条", detail={"adapter": name})
        except FetchError as exc:
            failures[name] = exc.reason
            log_run(mr, run_id, "collect", f"{name} 获取失败：{exc.reason}", level="warning")
        except Exception as exc:  # 解析等未预期错误同样降级记录
            failures[name] = f"{type(exc).__name__}: {exc}"
            log_run(mr, run_id, "collect", f"{name} 处理异常：{failures[name]}", level="warning")
    # 窗口过滤（无时间线索保留但标记）
    windowed = [c for c in candidates if _in_window(c.published_at, run.window_start, run.window_end)]
    clues = [c for c in candidates if c.published_at is None]
    dropped = len(candidates) - len(windowed) - len(clues)

    # 精确去重（跨源同文）
    seen: set[str] = set()
    uniques: list[NewsCandidate] = []
    dup = 0
    for c in windowed + clues:
        h = content_hash(c.title, c.source_url)
        if h in seen:
            dup += 1
            continue
        seen.add(h)
        uniques.append(c)

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
        "per_source": {name: sum(1 for c in candidates if c.adapter == name) for name in sources},
        "in_window": len(windowed),
        "clue_only": len(clues),
        "out_of_window_dropped": dropped,
        "duplicates_merged": dup,
        "saved_unique": len(items),
        "event_groups": len({i.event_group_id for i in items if i.event_group_id}),
        "source_failures": failures,
    }
    log_run(mr, run_id, "collect", "采集完成", detail=summary)

    run.finished_at = _now()
    if len(failures) == len(sources):
        run.status = "failed"
        run.error = "全部来源获取失败"
    elif failures:
        run.status = "degraded"
        run.error = "部分来源失败：" + "; ".join(f"{k}({v})" for k, v in failures.items())
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
