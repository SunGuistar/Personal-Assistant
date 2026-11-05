"""资讯评分与 TOP 10 排名纯函数单元测试（规则见 PRD §2.2：排名/去重/时效/多样性）。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.news_scoring import (
    age_decay,
    compute_score,
    effective_score,
    norm_heat_hn,
    norm_heat_rss,
    normalize_url,
    rank_top_items,
    title_hash,
    topic_of,
)

NOW = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)


# ---------- URL 规范化 ----------

def test_normalize_url_strips_tracking_and_trailing_slash():
    assert normalize_url(
        "HTTPS://Example.COM:443/path/?utm_source=x&b=2&a=1&ref=gh#frag"
    ) == "https://example.com/path?a=1&b=2"


def test_normalize_url_keeps_meaningful_params_sorted():
    assert normalize_url("https://a.com/p?z=1&m=2") == normalize_url("https://a.com/p?m=2&z=1")


def test_normalize_url_root_and_case():
    assert normalize_url("http://A.com/") == "http://a.com/"


# ---------- 标题哈希 ----------

def test_title_hash_normalizes_whitespace_and_case():
    assert title_hash("Hello   World") == title_hash("hello world")
    assert title_hash("不同标题") != title_hash("不同 标题吗")


# ---------- 热度归一化 ----------

def test_norm_heat_hn_monotonic_and_bounded():
    assert norm_heat_hn(0) == 0.0
    assert 0 < norm_heat_hn(10) < norm_heat_hn(100) < norm_heat_hn(1000) < 1.0
    assert norm_heat_hn(-5) == 0.0  # 零互动不为 NaN


def test_norm_heat_rss_neutral_default():
    assert norm_heat_rss() == 0.5


# ---------- 时效衰减 ----------

def test_age_decay_boundaries():
    published = NOW - timedelta(hours=48)  # 恰好一个半衰期
    assert age_decay(published, NOW) == 0.5
    assert age_decay(NOW + timedelta(hours=1), NOW) == 1.0  # 未来不衰减
    assert age_decay(NOW - timedelta(days=30), NOW) > 0.0  # 不为负/零


# ---------- 主题相关度 ----------

def test_topic_of_title_hit_first():
    topic, relevance = topic_of("Introducing the new Python runtime")
    assert topic == "python" and relevance == 1.0


def test_topic_of_summary_hit_half():
    topic, relevance = topic_of("Weekly roundup", "Summary of agent frameworks and tools")
    assert topic == "agent" and relevance == 0.5


def test_topic_of_other():
    assert topic_of("Random daily note", "nothing matches") == ("other", 0.0)


# ---------- 综合评分 ----------

def test_compute_score_formula():
    published = NOW - timedelta(hours=48)
    # 0.5(归一化) × 2(权重) × 0.5(半衰期) = 0.5
    assert compute_score(0.5, 2.0, published, NOW) == 0.5
    assert compute_score(0.5, 0.0, published, NOW) == 0.0  # 零权重为零


def test_effective_score_relevance_participates():
    base = compute_score(0.5, 1.0, NOW - timedelta(hours=48), NOW)
    with_rel = effective_score(base, "New Python agent framework")
    without = effective_score(base, "Untitled weekly note", "nothing")
    assert with_rel > without  # 主题相关性真实参与排序
    assert without == base


# ---------- TOP 10 排名 ----------

def _item(item_id: int, source: str, hours_old: float, score: float, title: str = "note", url: str | None = None) -> dict:
    return {
        "id": item_id,
        "title": title,
        "url": url or f"https://{source}.example/{item_id}",
        "source": source,
        "published_at": (NOW - timedelta(hours=hours_old)).isoformat(timespec="seconds"),
        "raw_summary": "",
        "score": score,
    }


def test_rank_prefers_effective_score_and_is_stable():
    items = [
        _item(1, "A", hours_old=2, score=0.5, title="Python news"),
        _item(2, "B", hours_old=1, score=0.5, title="Python news"),
        _item(3, "C", hours_old=3, score=0.9, title="random"),
    ]
    ranked = rank_top_items(items, now=NOW)
    assert [r["id"] for r in ranked] == [3, 2, 1]  # 分数优先；同分新的在前
    assert rank_top_items(items, now=NOW) == ranked  # 同输入同输出（稳定）


def test_rank_24h_window_then_72h_fallback():
    items = [_item(i, f"S{i}", hours_old=1, score=0.1) for i in range(4)]
    items.append(_item(99, "Old", hours_old=48, score=0.95))  # 高分但超过 24h
    ranked = rank_top_items(items, now=NOW, limit=10)
    assert ranked[0]["id"] == 99  # 24h 内不足时回退 72h 窗口纳入

    enough = [_item(i, f"S{i}", hours_old=1, score=0.1) for i in range(10)]
    enough.append(_item(99, "Old", hours_old=48, score=0.95))
    ranked2 = rank_top_items(enough, now=NOW, limit=10)
    assert all(r["id"] != 99 for r in ranked2)  # 24h 足够时不取旧闻


def test_rank_source_cap_diversity():
    items = [_item(i, "HN", hours_old=1, score=1.0 - i * 0.01) for i in range(8)]
    items.append(_item(100, "RSS", hours_old=2, score=0.1))
    ranked = rank_top_items(items, now=NOW, limit=10, source_cap=4)
    hn_count = sum(1 for r in ranked if r["source"] == "HN")
    assert hn_count <= 4  # 单一来源不包揽榜单


def test_rank_dedup_same_url_and_actual_count():
    items = [
        _item(1, "A", hours_old=1, score=0.9, url="https://dup.example/x"),
        _item(2, "B", hours_old=1, score=0.8, url="https://dup.example/x"),
        _item(3, "C", hours_old=1, score=0.7),
    ]
    ranked = rank_top_items(items, now=NOW, limit=10)
    assert len(ranked) == 2  # 相同 URL 不重复上榜
    assert [r["rank"] for r in ranked] == [1, 2]

    few = [_item(1, "A", hours_old=1, score=0.5)]
    ranked2 = rank_top_items(few, now=NOW, limit=10)
    assert ranked2[0]["rank"] == 1 and len(ranked2) == 1  # 不足 10 条按实际数量


def test_rank_drops_older_than_72h():
    items = [
        _item(1, "A", hours_old=96, score=1.0),  # 超过 72h
        _item(2, "B", hours_old=70, score=0.1),
    ]
    ranked = rank_top_items(items, now=NOW, limit=10)
    assert [r["id"] for r in ranked] == [2]
