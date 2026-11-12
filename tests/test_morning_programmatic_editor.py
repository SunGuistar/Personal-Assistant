"""正文组装零模型调用；目标分析异常只复现分析，不修改其逻辑。"""
import json
from types import SimpleNamespace
from app.morning_report.graph.workflow import node_editor, node_goal_analysis
from tests.test_morning_stage4_graph import _initial, _deps


def test_editor_never_calls_llm_and_keeps_personal_and_action_fields():
    class Forbidden:
        def chat(self, *a, **kw): raise AssertionError("unexpected model call")
    state = _initial()
    state.update(news_selection={"domestic": [{"id": 1}], "international": [{"id": 2}]},
        goal_result={"status": "failed", "error": "TypeError"},
        advice_result={"status": "ok", "advices": [{"content": "检查方案", "basis": "已有待办", "next_step": "列出缺口", "priority": "今日优先"}]})
    deps = SimpleNamespace(cancel_token=None, progress=None, llm=Forbidden(), record=lambda *a: (_ for _ in ()).throw(AssertionError("unexpected token write")))
    draft = node_editor(state, deps)["draft"]
    assert "### 昨日完成" in draft and "**读论文**" in draft
    assert "目标分析暂缺（TypeError）" in draft
    assert "1. **检查方案**（今日优先）" in draft and "依据：已有待办" in draft and "下一步：列出缺口" in draft
    assert "## 五、信息说明" in draft and "### AI" in draft


def test_goal_typeerror_can_be_reproduced_with_object_data_gaps(fclient):
    class Agent:
        def run(self, *a, **kw):
            return json.dumps({"current_state": {"content": "证据不足", "kind": "unknown", "evidence_ids": []},
                               "data_gaps": [{"content": "尚待确认"}]})
    result = node_goal_analysis(_initial(), _deps(fclient, subagents=Agent()))["goal_result"]
    assert result["status"] == "failed" and result["error"] == "TypeError"


def test_goal_agent_final_yesterday_is_validated_and_carried_through(fclient):
    class Agent:
        def run(self, *a, **kw):
            return json.dumps({"current_state": {"content": "待确认", "kind": "unknown", "evidence_ids": []}, "data_gaps": [], "yesterday_report": {"version": 1, "completed": [], "goal_progress": [], "attention": [], "questions": [{"id": "q1", "title": "确认昨日情况", "summary": "当前证据不足。", "detail": "", "kind": "unknown", "evidence_ids": []}], "additional": [], "notices": []}})
    result = node_goal_analysis(_initial(), _deps(fclient, subagents=Agent()))["goal_result"]
    assert result["status"] == "ok"
    assert result["analysis"]["yesterday_report"]["questions"][0]["title"] == "确认昨日情况"
    assert "yesterday_error" not in result
