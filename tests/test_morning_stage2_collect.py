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

AIHOT_PAGE1 = {
    "items": [
        {"id": "a1", "title": "LangGraph 0.6 发布", "summary": "s1",
         "publishedAt": "2026-11-09T10:00:00Z", "discoveredAt": "2026-11-09T11:00:00Z",
         "source": {"name": "GitHub"}, "links": {"original": "https://example.com/lg"}},
        {"id": "a2", "title": "OpenAI 新模型", "summary": "s2",
         "publishedAt": "2026-11-09T20:00:00+08:00", "discoveredAt": "2026-11-09T20:30:00+08:00",
         "source": {"name": "OpenAI"}, "links": {"original": "https://example.com/oai"}},
    ],
    "page": {"hasMore": True, "nextCursor": "c2"},
}
AIHOT_PAGE2 = {
    "items": [
        {"id": "a3", "title": "昨日旧闻", "summary": "s3",
         "publishedAt": "2026-11-08T09:00:00+08:00", "discoveredAt": "2026-11-08T10:00:00+08:00",
         "source": {"name": "X"}, "links": {"original": "https://example.com/old"}},
    ],
    "page": {"hasMore": False, "nextCursor": None},
}


def _mock_sources(rspx, aihot_status=200, cn_status=200, rm_status=200):
    def _aihot(request):
        if aihot_status != 200:
            return httpx.Response(aihot_status, text="err")
        if "cursor=c2" in str(request.url.query):
            return httpx.Response(200, json=AIHOT_PAGE2)
        return httpx.Response(200, json=AIHOT_PAGE1)

    rspx.get("https://aihot.news/api/v1/items").side_effect = _aihot
    (rspx.get("https://www.chinanews.com.cn/scroll-news/2026/1109/news.shtml").respond(
        cn_status, text=ARCHIVE_1109 if cn_status == 200 else "err"))
    (rspx.get("https://www.chinanews.com.cn/scroll-news/2026/1110/news.shtml").respond(
        cn_status, text=ARCHIVE_1110 if cn_status == 200 else "err"))
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

    assert summary["per_source"]["aihot"] == 3  # 两页合并
    assert summary["per_source"]["chinanews"] == 7
    assert summary["per_source"]["remoshuang"] == 4
    # 窗口 [11-09 08:00, 11-10 08:00)：太原07:30/综述09:30/aihot旧闻 出窗 → 中新5 + aihot2
    assert summary["in_window"] == 7
    assert summary["clue_only"] == 4
    assert summary["out_of_window_dropped"] == 3
    assert summary["source_failures"] == {}
    assert summary["event_groups"] >= 1

    with fclient.app.state.mr_session_factory() as mr:
        run = mr.get(RunRecord, run.id)
        assert run.status == "success"
        rows = mr.execute(select(NewsItem)).scalars().all()
        cats = {r.category for r in rows}
        assert cats == {"domestic", "international", "ai"}
        # 涉外时政入国际
        assert any(r.category == "international" and "黄仁勋" in r.title for r in rows)
        # 线索保留但无发布时间
        clues = [r for r in rows if r.published_at is None]
        assert len(clues) == 2  # 4 条两期相同去重后 2 条
        assert all(r.raw_ref["time_confidence"] == "day_only" for r in clues)


def test_pipeline_dedup_across_sources(fclient):
    dup_md = REMOSHUANG_MD.replace(
        "https://view.inews.qq.com/a/20261109A09BX600",
        "https://www.chinanews.com.cn/gj/2026/11-09/10729001.shtml",
    ).replace("特朗普称将与中俄元首在APEC讨论美伊冲突", "特朗普宣布实施铁门行动")
    with respx.mock(assert_all_called=False) as rspx:
        _mock_sources(rspx)
        rspx.get("https://remoshuang.com/daily/2026-11-09.md").respond(200, text=dup_md)
        rspx.get("https://remoshuang.com/daily/2026-11-10.md").respond(200, text=dup_md)
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
