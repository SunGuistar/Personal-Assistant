# -*- coding: utf-8 -*-
"""阶段 2 验收：三源适配器解析、窗口过滤、去重、事件归组、失败降级、runner 冲突。"""

from __future__ import annotations

import httpx
import respx
from sqlalchemy import func, select

from app.morning_report.adapters import chinanews, remoshuang
from app.morning_report.models import NewsItem, RunRecord
from app.morning_report.services import news_pipeline
from app.morning_report.services.runner import MorningRunner

# ---------- 合成 fixtures ----------

ARCHIVE_1109 = """
<html><body><div class="content_list"><ul>
<li><div class="dd_lm">[<a href=/world.shtml>国际</a>]</div> <div class="dd_bt"><a href="/gj/2026/11-09/10729001.shtml">特朗普宣布实施铁门行动</a></div><div class="dd_time">11-9 17:38</div></li>
<li><div class="dd_lm">[<a href=/world.shtml>国际</a>]</div> <div class="dd_bt"><a href="/gj/2026/11-09/10729002.shtml">伊朗称两日计划依然有效</a></div><div class="dd_time">11-9 21:42</div></li>
<li><div class="dd_lm">[<a href=/china.shtml>时政</a>]</div> <div class="dd_bt"><a href="/gn/2026/11-09/10729003.shtml">黄仁勋事件外交部回应</a></div><div class="dd_time">11-9 15:23</div></li>
<li><div class="dd_lm">[<a href=/china.shtml>时政</a>]</div> <div class="dd_bt"><a href="/gn/2026/11-09/10729004.shtml">国常会部署经济工作</a></div><div class="dd_time">11-9 10:00</div></li>
<li><div class="dd_lm">[<a href=/sh.shtml>社会</a>]</div> <div class="dd_bt"><a href="/sh/2026/11-09/10729005.shtml">太原高层建筑火灾救援持续</a></div><div class="dd_time">11-9 07:30</div></li>
</ul></div></body></html>
"""

ARCHIVE_1110 = """
<html><body><div class="content_list"><ul>
<li><div class="dd_lm">[<a href=/world.shtml>国际</a>]</div> <div class="dd_bt"><a href="/gj/2026/11-10/10729101.shtml">德国总理提名总统候选人</a></div><div class="dd_time">11-10 07:42</div></li>
<li><div class="dd_lm">[<a href=/world.shtml>国际</a>]</div> <div class="dd_bt"><a href="/gj/2026/11-10/10729102.shtml">早间国际要闻综述</a></div><div class="dd_time">11-10 09:30</div></li>
</ul></div></body></html>
"""

REMOSHUANG_MD = """# 2026年11月10日早间新闻
1. [特朗普称将与中俄元首在APEC讨论美伊冲突](https://view.inews.qq.com/a/20261109A09BX600)
   外交部回应相关言论。
2. [某国产大模型发布新版本](https://example.com/ai-model)
   AI 摘要内容。
"""

AIHOT_DAILY = {
    "schemaVersion": 1,
    "report": {
        "date": "2026-11-10",
        "generatedAt": "2026-11-10T07:30:00+08:00",
        "windowStart": "2026-11-09T08:00:00+08:00",
        "windowEnd": "2026-11-10T08:00:00+08:00",
        "lead": {"title": "LangGraph 0.6 发布", "leadParagraph": "……"},
        "sections": [
            {"label": "模型发布/更新", "items": [
                {"title": "LangGraph 0.6 发布", "summary": "s1",
                 "source": {"name": "GitHub"},
                 "links": {"aihot": "https://aihot.news/i/a1", "original": "https://example.com/lg"},
                 "publishedAt": "2026-11-09T10:00:00Z"},
                {"title": "OpenAI 新模型", "summary": "s2",
                 "source": {"name": "OpenAI"},
                 "links": {"aihot": "https://aihot.news/i/a2", "original": "https://example.com/oai"},
                 "publishedAt": "2026-11-09T20:00:00+08:00"},
            ]},
        ],
        "flashes": [
            {"title": "昨日旧闻", "source": {"name": "X"},
             "links": {"aihot": "https://aihot.news/i/a3", "original": "https://example.com/old"},
             "publishedAt": "2026-11-08T09:00:00+08:00"},
        ],
        "highlights": [],
    },
}


def _mock_sources(rspx, aihot_status=200, cn_status=200, rm_status=200):
    if aihot_status == 200:
        rspx.get("https://aihot.news/api/v1/dailies/latest").respond(200, json=AIHOT_DAILY)
    else:
        rspx.get("https://aihot.news/api/v1/dailies/latest").respond(aihot_status, text="err")
    entries = chinanews.parse_archive(ARCHIVE_1109, "2026/11/09") + chinanews.parse_archive(ARCHIVE_1110, "2026/11/10")
    for category, page in chinanews.HOT_PAGES.items():
        html = '<div class="hotlist"><ul>' + ''.join(f'<li><a href="{e.source_url}">{e.title}</a></li>' for e in entries if e.category == category) + '</ul></div>'
        rspx.get(page).respond(cn_status, text=html if cn_status == 200 else "err")
    for entry in chinanews.parse_archive(ARCHIVE_1109, "2026/11/09") + chinanews.parse_archive(ARCHIVE_1110, "2026/11/10"):
        rspx.get(entry.source_url).respond(200, text=f'<time datetime="{entry.published_at}"></time><p>{entry.title * 5}</p>')
    for cat, title in (("news_china_suda", "国内主要政策发布"), ("news_world_suda", "国际外交谈判取得突破")):
        rspx.get("https://top.news.sina.com.cn/ws/GetTopDataList.php", params__contains={"top_cat": cat}).respond(
            200, json={"data": [{"title": title, "url": "https://example.com/" + cat,
                "media": "测试媒体", "time": "Mon, 09 Nov 2026 12:00:00 +0800",
                "top_time": "20261110", "top_num": "1,000"}]})
    (rspx.get("https://remoshuang.com/daily/2026-11-09.md").respond(
        rm_status, text=REMOSHUANG_MD if rm_status == 200 else "err"))
    (rspx.get("https://remoshuang.com/daily/2026-11-10.md").respond(
        rm_status, text=REMOSHUANG_MD if rm_status == 200 else "err"))


# ---------- 适配器单元 ----------

def test_chinanews_parse_and_classify():
    items = chinanews.parse_archive(ARCHIVE_1109, "2026/11/09")
    assert len(items) == 5
    by_title = {i.title: i for i in items}
    assert by_title["特朗普宣布实施铁门行动"].category == "international"
    assert by_title["伊朗称两日计划依然有效"].category == "international"
    assert by_title["黄仁勋事件外交部回应"].category == "international"  # 涉外时政
    assert by_title["国常会部署经济工作"].category == "domestic"
    assert by_title["太原高层建筑火灾救援持续"].published_at == "2026-11-09T07:30:00+08:00"


def test_remoshuang_parse_clue():
    items = remoshuang.parse_daily(REMOSHUANG_MD, "2026-11-10")
    assert len(items) == 2
    assert all(i.published_at is None for i in items)
    assert {i.category for i in items} == {"international", "ai"}


# ---------- 管线集成 ----------

def test_pipeline_full_flow(fclient):
    with respx.mock(assert_all_called=False) as rspx:
        _mock_sources(rspx)
        with fclient.app.state.mr_session_factory() as mr:
            run = news_pipeline.create_collect_run(mr, "2026-11-10")
            summary = news_pipeline.run_collect(mr, run.id)

    assert summary["per_source"]["aihot"] == 3  # 当期日报：2 条栏目 + 1 条快讯
    assert summary["per_source"]["chinanews_domestic"] == 2
    assert summary["per_source"]["chinanews_international"] == 5
    assert set(summary["per_source"]) == {"aihot", "chinanews_domestic", "chinanews_international"}
    assert not any("sina.com" in str(c.request.url) or "remoshuang.com" in str(c.request.url) or "scroll-news" in str(c.request.url) for c in rspx.calls)
    assert summary["in_window"] == 7
    assert summary["ai_daily_members"] == 3
    assert summary["clue_only"] == 0
    assert summary["out_of_window_dropped"] == 0  # 官方榜单新闻不按时间过滤
    assert summary["source_failures"] == {}
    assert summary["event_groups"] >= 1

    with fclient.app.state.mr_session_factory() as mr:
        run = mr.get(RunRecord, run.id)
        assert run.status == "degraded"  # 线索/覆盖不足被明确披露
        rows = mr.execute(select(NewsItem)).scalars().all()
        cats = {r.category for r in rows}
        assert cats == {"domestic", "international", "ai"}
        assert summary["by_category"] == {
            category: sum(r.category == category for r in rows)
            for category in ("domestic", "international", "ai")
        }
        assert sum(summary["by_category"].values()) == summary["saved_unique"]
        # 涉外时政入国际
        assert any(r.category == "international" and "黄仁勋" in r.title for r in rows)
        # 日报成员带日报归属元数据；日报窗口与原文发布时间分开记录
        daily_rows = [r for r in rows if (r.raw_ref or {}).get("daily_member")]
        assert len(daily_rows) == 3
        assert all(r.raw_ref["daily_date"] == "2026-11-10" for r in daily_rows)
        assert all(r.raw_ref["daily_window_start"] == "2026-11-09T08:00:00+08:00" for r in daily_rows)
        flash = next(r for r in daily_rows if r.title == "昨日旧闻")
        assert flash.published_at == "2026-11-08T09:00:00+08:00"  # 原文时间如实保留，不伪造
        lead = next(r for r in daily_rows if r.title == "LangGraph 0.6 发布")
        assert lead.raw_ref["is_lead"] is True
        # 线索保留但无发布时间
        clues = [r for r in rows if r.published_at is None]
        assert len(clues) == 0  # 不混入其他来源线索
        assert all(r.raw_ref["time_confidence"] == "day_only" for r in clues)


def test_pipeline_dedup_across_sources(fclient):
    from app.morning_report.adapters import NewsCandidate
    candidates = [NewsCandidate("domestic", "重要政策公布", "摘要", "中国新闻网", f"https://example.com/{i}", "2026-11-09T10:00:00+08:00", "chinanews", {"rank": i}) for i in (1, 2)]
    with respx.mock(assert_all_called=False) as rspx:
        _mock_sources(rspx)
        from unittest.mock import patch
        with patch.object(chinanews, "fetch_hot_ranked", side_effect=lambda cat, *a, **k: candidates if cat == "domestic" else []):
            with fclient.app.state.mr_session_factory() as mr:
                run = news_pipeline.create_collect_run(mr, "2026-11-10")
                summary = news_pipeline.run_collect(mr, run.id)
    assert summary["duplicates_merged"] > 0


def test_pipeline_source_failure_degraded(fclient):
    with respx.mock(assert_all_called=False) as rspx:
        _mock_sources(rspx, aihot_status=500)
        rspx.routes  # silence
        with fclient.app.state.mr_session_factory() as mr:
            run = news_pipeline.create_collect_run(mr, "2026-11-10")
            summary = news_pipeline.run_collect(mr, run.id)
    assert "aihot" in summary["source_failures"]
    with fclient.app.state.mr_session_factory() as mr:
        assert mr.get(RunRecord, run.id).status == "degraded"


def test_runner_conflict_guard(fclient):
    runner = MorningRunner(fclient.app.state.mr_session_factory)
    calls: list[int] = []

    def slow_fn(mr, run_id):
        calls.append(run_id)
        return {}

    with fclient.app.state.mr_session_factory() as mr:
        r1 = news_pipeline.create_collect_run(mr, "2026-11-10")
    assert runner.submit("collect", r1.id, slow_fn) is True
    with fclient.app.state.mr_session_factory() as mr:
        r2 = news_pipeline.create_collect_run(mr, "2026-11-10")
    assert runner.submit("collect", r2.id, slow_fn) is False  # 同 kind 冲突
    import time
    for _ in range(50):
        if calls:
            break
        time.sleep(0.05)
    assert calls == [r1.id]
    runner.shutdown()
