"""资讯评分纯函数单元测试（TEST_PLAN：新闻去重/热度归一化/评分/过期）。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.news_scoring import (
    age_decay,
    compute_score,
    is_expired,
    norm_heat_hn,
    norm_heat_rss,
    normalize_url,
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


# ---------- 过期判定 ----------

def test_is_expired_favorite_exempt_and_boundary():
    old = NOW - timedelta(days=8)
    recent = NOW - timedelta(days=6, hours=23)
    assert is_expired(old, NOW, is_favorite=False) is True
    assert is_expired(old, NOW, is_favorite=True) is False
    assert is_expired(recent, NOW) is False
