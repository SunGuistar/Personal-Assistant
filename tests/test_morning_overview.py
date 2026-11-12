"""开篇速览由来源确定性组装，主编使用分点展示 system prompt。"""
import json
from types import SimpleNamespace
from app.morning_report.graph import prompts
from app.morning_report.graph.workflow import node_editor
from app.morning_report.services.llm_router import ChatResult
from tests.test_morning_stage4_graph import _initial, REPORT_MD


def test_overview_has_first_news_and_all_tips_with_source_summaries():
    state = _initial()
    state.update(news_selection={"domestic": [{"id": 1}], "international": [{"id": 2}], "ai": []},
                 goal_result={}, advice_result={})
    state["ai_daily"] = state["ai_daily"] + [
        {"id": 4, "title": "使用技巧", "url": "https://example.com/tip", "summary": "技巧摘要", "section_label": "技巧与观点"},
        {"id": 5, "title": "行业观点", "url": "https://example.com/view", "summary": "观点摘要", "section_label": "讨论与观点"},
        {"id": 6, "title": "不进速览", "url": "https://example.com/other", "summary": "其他摘要", "section_label": "行业动态"},
    ]
    captured = []
    def chat(messages, *, json_mode):
        assert json_mode is True
        captured.extend(messages)
        return ChatResult(content=json.dumps({"content_md": REPORT_MD}, ensure_ascii=False))
    deps = SimpleNamespace(cancel_token=None, progress=None, llm=SimpleNamespace(chat=chat), record=lambda *a: None)
    draft = node_editor(state, deps)["draft"]
    overview = draft.split("## 一、开篇速览", 1)[1].split("## 二、重要资讯", 1)[0]
    for title, summary, kind in [("国常会部署经济工作", "部署稳增长", "国内新闻"),
                                  ("特朗普宣布铁门行动", "美伊局势", "国外新闻"),
                                  ("LangGraph 0.6 发布", "新增中断恢复", "AI新闻"),
                                  ("使用技巧", "技巧摘要", "技巧与观点"),
                                  ("行业观点", "观点摘要", "技巧与观点")]:
        assert title in overview and summary in overview and f"【{kind}】" in overview
    assert "不进速览" not in overview and "本期关注" not in overview
    assert captured[0] == {"role": "system", "content": prompts.EDITOR_SYSTEM}
    assert "分点" in prompts.EDITOR_SYSTEM and "下一步" in prompts.EDITOR_SYSTEM
    assert "## 三、我的昨日" in draft and "## 四、今日建议" in draft


def test_overview_missing_sources_and_injection_fallback():
    from app.morning_report.graph.workflow import assemble_overview, inject_overview
    state = {"news": [], "news_selection": {}, "ai_daily": []}
    assert "暂无可用" in assemble_overview(state)
    result = inject_overview("## 二、重要资讯\n正文\n## 三、我的昨日\n回顾", "- 条目")
    assert result.index("## 一、开篇速览") < result.index("## 二、重要资讯")
    assert "正文" in result and "回顾" in result


def test_overview_includes_all_tips_even_when_first_ai_is_a_tip():
    from app.morning_report.graph.workflow import assemble_overview
    state = {"news": [], "news_selection": {}, "ai_daily": [
        {"id": 1, "title": "技巧", "summary": "原摘要", "section_label": "技巧与观点"}]}
    block = assemble_overview(state)
    assert "【AI新闻】" in block and "【技巧与观点】" in block
    assert "原摘要" in block
