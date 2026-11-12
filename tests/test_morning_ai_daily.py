# -*- coding: utf-8 -*-
"""AIHOT 最新日报策略：解析/落库/展示顺序、去重、降级、确定性组装注入（假模型/假 HTTP/临时库）。"""

from __future__ import annotations

import json

import pytest
import respx
from sqlalchemy import select

from app.morning_report.adapters import aihot, sina_hot, remoshuang
from app.morning_report.adapters.http_common import FetchError
from app.morning_report.config import MRSettings
from app.morning_report.graph.workflow import (AI_LIST_PLACEHOLDER, assemble_ai_list,
                                               inject_ai_list)
from app.morning_report.models import NewsItem, ReportVersion, RunRecord
from app.morning_report.services import news_pipeline, report_service
from app.morning_report.services.llm_router import ChatResult

from tests.test_morning_stage4_graph import REPORT_MD, FakeLLM, TraceSubagents, _deps

DATE = "2026-11-11"
WS, WE = "2026-11-10T08:00:00+08:00", "2026-11-11T08:00:00+08:00"


def _entry(title, original=None, aihot_link=None, published=None, summary="摘要", source="来源"):
    e = {"title": title, "summary": summary, "source": {"name": source},
         "links": {"original": original, "aihot": aihot_link}}
    if published is not None:
        e["publishedAt"] = published
    return e


def daily_payload(date=DATE, sections=None, flashes=None, highlights=None, lead=None):
    return {"schemaVersion": 1, "report": {
        "date": date, "generatedAt": f"{date}T07:30:00+08:00",
        "windowStart": WS, "windowEnd": WE,
        "lead": lead or {"title": "", "leadParagraph": ""},
        "sections": sections if sections is not None else [
            {"label": "模型发布/更新", "items": [
                _entry("模型 A 发布", original="https://example.com/a",
                       published="2026-11-10T10:00:00+08:00")]}],
        "flashes": flashes if flashes is not None else [],
        "highlights": highlights if highlights is not None else [],
    }}


# ---------- 适配器解析 ----------

def test_daily_parse_order_dedup_and_fields():
    """sections 按原分类顺序 → flashes → highlights；跨区域按规范化链接去重。"""
    payload = daily_payload(
        sections=[{"label": "模型发布/更新", "items": [
            _entry("模型 A 发布", original="https://Example.com/a/", published="2026-11-10T10:00:00Z"),
            _entry("模型 B 开源", original=None, aihot_link="https://aihot.news/i/b"),
        ]}, {"label": "行业动态", "items": [
            _entry("行业 C 合作", original="https://example.com/c"),
        ]}],
        flashes=[_entry("模型 A 发布", original="https://example.com/a"),  # 与栏目条目同链 → 去重
                 _entry("快讯 D", aihot_link="https://aihot.news/i/d")],
        highlights=[_entry("行业 C 合作", original="https://example.com/c"),  # 已出现 → 不重复
                    _entry("精选 E", original="https://example.com/e")],
        lead={"title": "模型 A 发布", "leadParagraph": "头条"},
    )
    items = aihot.parse_daily_report(payload, DATE)
    assert [i.title for i in items] == ["模型 A 发布", "模型 B 开源", "行业 C 合作", "快讯 D", "精选 E"]
    assert [i.raw["display_order"] for i in items] == [1, 2, 3, 4, 5]
    assert [i.raw["daily_kind"] for i in items] == ["section", "section", "section", "flash", "highlight"]
    assert [i.raw["section_label"] for i in items] == ["模型发布/更新", "模型发布/更新", "行业动态", "快讯", "精选"]
    a, b = items[0], items[1]
    assert a.source_url == "https://Example.com/a/"  # 展示链接优先 original（原样保留）
    assert a.published_at == "2026-11-10T18:00:00+08:00"  # Z → CST
    assert a.raw["is_lead"] is True
    assert b.source_url == "https://aihot.news/i/b"  # original 缺失回退有效 aihot 链接
    assert all(i.raw["daily_date"] == DATE and i.raw["daily_member"] for i in items)
    assert all(i.raw["daily_window_start"] == WS for i in items)


def test_daily_no_published_at_and_old_flash_kept():
    """无 publishedAt 的栏目条目、早于窗口的快讯都按当期日报成员保留，时间不伪造。"""
    payload = daily_payload(
        sections=[{"label": "模型发布/更新", "items": [_entry("无时间条目", original="https://example.com/x")]}],
        flashes=[_entry("上周快讯", original="https://example.com/old",
                        published="2026-11-03T09:00:00+08:00")])
    items = aihot.parse_daily_report(payload, DATE)
    assert len(items) == 2
    assert items[0].published_at is None  # 留空，不用日报日期伪造
    assert items[1].published_at == "2026-11-03T09:00:00+08:00"  # 早于窗口仍保留


@pytest.mark.parametrize("bad", [
    {}, {"report": {}}, {"report": {"date": "2026-11-10"}},  # 日期不符
    {"report": {"date": DATE}},  # sections 缺失
    {"report": {"date": DATE, "sections": "not-a-list"}},
    {"report": {"date": DATE, "sections": [], "flashes": [], "highlights": []}},  # 空日报
    "not-a-dict",
])
def test_daily_rejects_bad_date_structure_or_empty(bad):
    with pytest.raises(FetchError):
        aihot.parse_daily_report(bad, DATE)


def test_daily_http_failure_raises():
    with respx.mock(assert_all_called=True) as mock:
        mock.get(aihot.DAILY_API).respond(500, text="err")
        with pytest.raises(FetchError):
            aihot.fetch_daily(DATE)


def test_lead_without_verifiable_link_not_added():
    """lead 只有标题没有可验证条目链接：不凭标题构造链接、不新增条目。"""
    payload = daily_payload(
        sections=[{"label": "模型发布/更新", "items": [_entry("模型 A 发布", original="https://example.com/a")]}],
        lead={"title": "无从验证的头条", "leadParagraph": "……"})
    items = aihot.parse_daily_report(payload, DATE)
    assert len(items) == 1 and items[0].title == "模型 A 发布"


# ---------- 确定性组装与注入 ----------

def test_assemble_escapes_markdown_and_sanitizes_links():
    items = [
        {"title": "模型 [Pro] *增强* 发布", "url": "https://example.com/a"},
        {"title": "含括号标题(正式版)", "url": "https://example.com/b(1) v2"},
        {"title": "非法链接条目", "url": "ftp://example.com/x"},
        {"title": "缺链接条目", "url": ""},
    ]
    block = assemble_ai_list(items)
    lines = block.split("\n")
    assert lines[0] == "- [模型 \\[Pro\\] \\*增强\\* 发布](https://example.com/a)"
    assert lines[1] == "- [含括号标题(正式版)](https://example.com/b%281%29%20v2)"  # 括号/空格编码
    assert lines[2] == "- 非法链接条目"  # 非 http/https 丢弃链接，不编造
    assert lines[3] == "- 缺链接条目"
    assert assemble_ai_list([]) == "（本期 AIHOT 日报不可用或无条目，AI 资讯列表缺失）"


def test_inject_replaces_placeholder_and_strips_model_items():
    draft = ("## 二、重要资讯\n### 国内\n- [国内新闻](https://example.com/d)\n### AI\n"
             "本期 AI 概览。\n- [模型虚构的标题](https://evil.example.com/fake)\n"
             + AI_LIST_PLACEHOLDER + "\n\n## 三、我的昨日\n内容\n")
    block = "- [真实日报条目](https://example.com/a)"
    out, injected = inject_ai_list(draft, block)
    assert injected is True
    assert "- [真实日报条目](https://example.com/a)" in out
    assert "虚构的标题" not in out  # 模型自写列表行被剔除
    assert "本期 AI 概览。" in out  # 引语保留
    assert AI_LIST_PLACEHOLDER not in out


def test_inject_fallback_when_placeholder_missing():
    block = "- [真实日报条目](https://example.com/a)"
    # 有 AI 小节但模型自写了内容 → 整节替换，不产生重复小节
    draft = "## 二、重要资讯\n### AI\n- [虚构条目](https://x.example.com)\n\n## 三、我的昨日\n内容\n"
    out, injected = inject_ai_list(draft, block)
    assert injected is False and "虚构条目" not in out
    assert out.count("### AI") == 1 and block in out
    # 完全没有 AI 小节 → 插入"三、"之前
    draft2 = "## 二、重要资讯\n内容\n\n## 三、我的昨日\n内容\n"
    out2, _ = inject_ai_list(draft2, block)
    assert "### AI" in out2 and out2.index("### AI") < out2.index("## 三、我的昨日")


# ---------- 生成链路（假模型 + 临时库） ----------

class DailyFakeLLM(FakeLLM):
    """资讯选取按提示词中的候选动态生成；保留完整提示词供断言。"""

    def __init__(self, editor_md: str = REPORT_MD, **kw):
        super().__init__(**kw)
        self.editor_md = editor_md
        self.full_prompts: list[str] = []

    def chat(self, messages, *, json_mode=False, tools=None, thinking=None):
        prompt = messages[-1]["content"]
        self.full_prompts.append(prompt)
        if "选出值得进入晨报的条目" in prompt:
            news_txt = prompt.split("新闻候选：\n", 1)[1].split("\n用户兴趣偏好", 1)[0]
            news = json.loads(news_txt)
            content = json.dumps({
                "domestic": [{"id": n["id"], "title": n["title"], "why": "w"}
                             for n in news if n["category"] == "domestic"],
                "international": [{"id": n["id"], "title": n["title"], "why": "w"}
                                  for n in news if n["category"] == "international"],
            }, ensure_ascii=False)
            return ChatResult(content=content, input_tokens=1, output_tokens=1, elapsed_ms=1)
        if "五部分结构" in prompt:
            return ChatResult(content=json.dumps({"content_md": self.editor_md}, ensure_ascii=False), input_tokens=1, output_tokens=1, elapsed_ms=1)
        return super().chat(messages, json_mode=json_mode, tools=tools, thinking=thinking)


def _seed_collect(mr, report_date=DATE, daily_count=3, daily_titles=None, strategy_current=True):
    collect = news_pipeline.create_collect_run(mr, report_date)
    collect.status = "success"
    mr.add(news_pipeline.RunLog(run_id=collect.id, stage="collect", level="info",
                                message="采集完成",
                                detail={"collection_strategy": (
                                    news_pipeline.COLLECTION_STRATEGY if strategy_current
                                    else "hot_featured_v1")}))
    titles = daily_titles or [f"AI 日报条目 {i}" for i in range(daily_count)]
    for i, title in enumerate(titles, 1):
        mr.add(NewsItem(
            run_id=collect.id, category="ai", title=title, summary=f"摘要{i}",
            source_name="AIHOT", source_url=f"https://example.com/ai/{i}",
            published_at=None,  # 日报成员可无原文时间
            content_hash=f"d{i}", dedupe_status="unique",
            raw_ref={"daily_member": True, "daily_date": report_date,
                     "display_order": i, "daily_kind": "section",
                     "section_label": "模型发布/更新",
                     "daily_window_start": WS, "daily_window_end": WE}))
    mr.add(NewsItem(run_id=collect.id, category="domestic", title="国内重大政策", summary="s",
                    source_name="央视", source_url="https://example.com/dom",
                    published_at="2026-11-10T10:00:00+08:00", content_hash="h1",
                    dedupe_status="unique", raw_ref={"selection_kind": "hot", "rank": 1}))
    mr.add(NewsItem(run_id=collect.id, category="international", title="国际外交突破", summary="s",
                    source_name="新华社", source_url="https://example.com/intl",
                    published_at="2026-11-10T12:00:00+08:00", content_hash="h2",
                    dedupe_status="unique", raw_ref={"selection_kind": "hot", "rank": 1}))
    mr.commit()
    return collect


def _run_generate(fclient, llm, run_id):
    settings = MRSettings(schedule_enabled=False)
    deps = _deps(fclient, llm=llm, run_id=run_id)
    with fclient.app.state.mr_session_factory() as mr:
        return report_service.run_generate(
            mr, run_id, settings, mode="manual", deps_override=deps,
            hub_session_factory=None, mr_session_factory=fclient.app.state.mr_session_factory)


def _new_run(mr, report_date=DATE):
    run = RunRecord(run_date=report_date, kind="generate", status="pending")
    mr.add(run)
    mr.commit()
    return run.id


def test_generate_full_daily_list_and_eval_sees_final_draft(fclient):
    """>60 条日报全部进正文（不经模型筛选/截断）；质量评价与落库看到的是组装后正文。"""
    n = 70
    with fclient.app.state.mr_session_factory() as mr:
        _seed_collect(mr, daily_count=n)
        rid = _new_run(mr)
    llm = DailyFakeLLM()
    out = _run_generate(fclient, llm, rid)
    assert out["status"] in ("success", "degraded")
    with fclient.app.state.mr_session_factory() as mr:
        ver = mr.execute(select(ReportVersion)).scalars().one()
    draft = ver.content_md
    assert AI_LIST_PLACEHOLDER not in draft
    for i in range(n):
        assert f"- [AI 日报条目 {i}](https://example.com/ai/{i + 1})" in draft
    assert draft.split("## 二、重要资讯", 1)[1].count("](https://example.com/ai/") == n  # 正文完整列表不漏项；速览另有首条
    # AI 日报未进入资讯筛选模型输入（只查候选 JSON 段，提示词说明文字不算）
    info_prompts = [p for p in llm.full_prompts if "选出值得进入晨报的条目" in p]
    assert info_prompts == []  # 三类资讯均不再交给模型筛选
    eval_prompts = [p for p in llm.full_prompts if "七个维度各打" in p]
    assert eval_prompts and f"AI 日报条目 {n - 1}" in eval_prompts[0]
    editor_prompts = [p for p in llm.full_prompts if "五部分结构" in p]
    assert editor_prompts and "{{DOMESTIC_NEWS_LIST}}" in editor_prompts[0]
    assert "国内重大政策" in draft and "国际外交突破" in draft
    assert "https://example.com/dom" in draft and "https://example.com/intl" in draft



def test_generate_placeholder_missing_fallback(fclient):
    md = REPORT_MD.replace("{{AI_NEWS_LIST}}\n", "").replace(
        "### AI\n本期 AI 进展概览。", "### AI\n本期 AI 概览。\n- [模型虚构的条目](https://evil.example.com/f)")
    with fclient.app.state.mr_session_factory() as mr:
        _seed_collect(mr, daily_count=2)
        rid = _new_run(mr)
    out = _run_generate(fclient, DailyFakeLLM(editor_md=md), rid)
    assert out["status"] in ("success", "degraded")
    with fclient.app.state.mr_session_factory() as mr:
        draft = mr.execute(select(ReportVersion)).scalars().one().content_md
    assert "- [AI 日报条目 0](https://example.com/ai/1)" in draft
    assert "- [AI 日报条目 1](https://example.com/ai/2)" in draft
    assert "模型虚构的条目" not in draft  # 模型虚构内容被整节替换
    assert draft.count("### AI") == 1  # 不产生重复小节
    assert "已自动补齐" in draft


def test_regenerate_reuses_daily_snapshot(fclient, monkeypatch):
    """重新生成复用已落库日报快照，不重新请求 AIHOT；旧策略采集记录不算当期快照。"""
    monkeypatch.setattr(news_pipeline.aihot, "fetch_daily",
                        lambda date: (_ for _ in ()).throw(AssertionError("不应重新请求 AIHOT")))
    with fclient.app.state.mr_session_factory() as mr:
        collect = _seed_collect(mr, daily_count=2)
        old = news_pipeline.create_collect_run(mr, "2026-11-10")
        old.status = "success"
        mr.add(news_pipeline.RunLog(run_id=old.id, stage="collect", level="info",
                                    message="采集完成",
                                    detail={"collection_strategy": "hot_featured_v1"}))
        mr.commit()
        rid = _new_run(mr)
        assert news_pipeline.collection_is_current(mr, collect.id)
        assert not news_pipeline.collection_is_current(mr, old.id)  # 旧 items 策略不误认
    out = _run_generate(fclient, DailyFakeLLM(), rid)
    assert out["status"] in ("success", "degraded")
    with fclient.app.state.mr_session_factory() as mr:
        draft = mr.execute(select(ReportVersion)).scalars().one().content_md
    assert "AI 日报条目 0" in draft and "AI 日报条目 1" in draft


def test_pipeline_daily_failure_degrades(fclient, monkeypatch):
    """latest 日期不符/接口失败：明确记录来源不可用，走降级，不冒充当期。"""
    def wrong_date(date):
        raise FetchError(aihot.DAILY_API, f"日报日期不符：期望 {date}，实际 2026-11-10")
    monkeypatch.setattr(news_pipeline.aihot, "fetch_daily", wrong_date)
    monkeypatch.setattr(sina_hot, "fetch_hot", lambda cat, date: [])
    monkeypatch.setattr(news_pipeline.chinanews, "fetch_hot_ranked", lambda *a, **k: [])
    monkeypatch.setattr(remoshuang, "fetch_daily", lambda day: [])
    with fclient.app.state.mr_session_factory() as mr:
        run = news_pipeline.create_collect_run(mr, DATE)
        summary = news_pipeline.run_collect(mr, run.id)
        assert "aihot" in summary["source_failures"]
        assert summary["ai_daily_members"] == 0
        assert any("AIHOT 最新日报不可用" in n for n in summary["coverage_notes"])
        assert mr.execute(select(NewsItem).where(
            NewsItem.run_id == run.id, NewsItem.category == "ai")).scalars().all() == []


def test_pipeline_daily_members_saved_and_remoshuang_clue_not_mixed(fclient, monkeypatch):
    """日报成员（含无时间/早于窗口）落库并标记；不采集热摸爽等其他 AI 来源。"""
    payload = daily_payload(
        sections=[{"label": "模型发布/更新", "items": [
            _entry("无时间栏目条目", original="https://example.com/x")]}],
        flashes=[_entry("上周快讯", original="https://example.com/old",
                        published="2026-11-03T09:00:00+08:00")])
    monkeypatch.setattr(news_pipeline.aihot, "fetch_daily",
                        lambda date: aihot.parse_daily_report(payload, date))
    monkeypatch.setattr(sina_hot, "fetch_hot", lambda cat, date: [])
    monkeypatch.setattr(news_pipeline.chinanews, "fetch_hot_ranked", lambda *a, **k: [])
    from app.morning_report.adapters import remoshuang as rm_adapter
    monkeypatch.setattr(remoshuang, "fetch_daily", lambda day: [
        rm_adapter.NewsCandidate(category="ai", title="热摸爽 AI 线索", summary="",
                                 source_name="热摸爽", source_url="https://clue.example.com/1",
                                 published_at=None, adapter="remoshuang",
                                 raw={"daily_date": day, "time_confidence": "day_only"})])
    with fclient.app.state.mr_session_factory() as mr:
        run = news_pipeline.create_collect_run(mr, DATE)
        summary = news_pipeline.run_collect(mr, run.id)
        assert summary["ai_daily_members"] == 2
        rows = mr.execute(select(NewsItem).where(
            NewsItem.run_id == run.id, NewsItem.category == "ai")).scalars().all()
        daily_rows = [r for r in rows if (r.raw_ref or {}).get("daily_member")]
        assert {r.title for r in daily_rows} == {"无时间栏目条目", "上周快讯"}
        assert len(rows) == 2
        assert not any(r.title == "热摸爽 AI 线索" for r in rows)  # 生产不再采集其他 AI 来源
