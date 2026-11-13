from app.morning_report.services.report_assembly import build_yesterday


def test_groups_preserve_records_and_collapse_repeated_task_analysis():
    personal = {"daily_done": [{"id": i, "title": "完成事项" + str(i)} for i in range(1, 7)]}
    goal = {"status": "ok", "analysis": {
        "progress": [{"content": "重复说明完成任务", "kind": "analysis", "evidence_ids": ["daily_tasks:1"]},
                     {"title": "目标推进", "content": "关联长期目标。详细依据保留。", "kind": "analysis", "evidence_ids": ["long_term_plans:1"]}],
        "risks": [{"content": "有依据的阻塞", "kind": "analysis", "evidence_ids": ["daily_tasks:7"]},
                  {"content": "未知风险", "kind": "unknown", "evidence_ids": []}],
        "questions": [{"content": "需要确认安排", "kind": "unknown"}], "data_gaps": ["信息不足"]}}
    content = build_yesterday(personal, goal)
    assert len(content["completed"]) == 6
    assert len(content["goal_progress"]) == len(content["attention"]) == len(content["additional"]) == 1
    assert len(content["questions"]) == 3
    assert content["goal_progress"][0]["summary"] == "关联长期目标。"
    assert content["goal_progress"][0]["detail"] == "关联长期目标。详细依据保留。"


def test_failure_keeps_facts_without_inventing_risks():
    content = build_yesterday({"daily_done": [{"title": "真实完成"}]}, {"status": "failed", "error": "TypeError"})
    assert content["completed"][0]["kind"] == "confirmed"
    assert not content["attention"] and "TypeError" in content["notices"][0]


def test_legacy_display_reads_snapshot_without_changing_stored_sections():
    from types import SimpleNamespace
    from app.morning_report.services.report_assembly import display_yesterday
    original = {"goal": {"status": "failed", "error": "TypeError"}}
    row = SimpleNamespace(payload={"id": 4, "title": "历史完成记录"}, record_id=4)
    class ReadOnly:
        def execute(self, statement):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [row]))
    result = display_yesterday(ReadOnly(), SimpleNamespace(run_id=7), original)
    assert "yesterday_content" not in original
    assert result["yesterday_content"]["completed"][0]["title"] == "历史完成记录"
    assert result["yesterday_content"]["completed"][0]["kind"] == "confirmed"


def test_agent_authored_report_is_used_without_rewriting_or_merging_tasks():
    from app.morning_report.services.report_assembly import validate_yesterday, personal_sections
    report = {"version": 1, "completed": [{"id": "outcome", "title": "Agent归纳的成果", "summary": "多个任务共同完成一个成果。", "detail": "完整细节", "kind": "confirmed", "evidence_ids": ["daily_tasks:1"]}], "goal_progress": [], "attention": [], "questions": [], "additional": [], "notices": []}
    checked = validate_yesterday(report, {"daily_tasks:1": {}})
    goal = {"status": "ok", "analysis": {"yesterday_report": checked}}
    personal = {"daily_done": [{"title": "不应再自动追加的任务"}]}
    assert build_yesterday(personal, goal) == report
    markdown, _ = personal_sections(personal, goal, {})
    assert "Agent归纳的成果" in markdown and "不应再自动追加" not in markdown
    assert "多个任务共同完成一个成果。" in markdown and "完整细节" in markdown
    assert "### 昨日完成" not in markdown and "事实完成" in markdown


def test_personal_sections_publishes_only_one_advice_from_old_multi_action_data():
    from app.morning_report.services.report_assembly import personal_sections
    _, actions = personal_sections({}, {}, {"advices": [
        {"content": "首选行动", "basis": "依据", "next_step": "第一步"},
        {"content": "第二行动", "basis": "依据", "next_step": "第二步"}]})
    assert "首选行动" in actions and "第二行动" not in actions


def test_invalid_agent_report_is_explicitly_rejected():
    import pytest
    from app.morning_report.services.report_assembly import validate_yesterday
    base = {"version": 1, "completed": [], "goal_progress": [], "attention": [], "questions": [], "additional": [], "notices": []}
    for change in ({"completed": "text"}, {"notices": [{}]}, {"attention": [{"id": "risk", "title": "风险", "summary": "无依据风险", "detail": "", "kind": "analysis", "evidence_ids": ["fake:1"]}]}):
        with pytest.raises(ValueError, match="yesterday_report"):
            validate_yesterday(dict(base, **change), {})


def test_missing_final_report_has_explicit_notice_and_only_real_task_fallback():
    content = build_yesterday({"daily_done": [{"title": "真实完成"}]}, {"status": "ok", "analysis": {"progress": [{"content": "不应重新编写"}]}, "yesterday_error": "未返回我的昨日"})
    assert len(content["completed"]) == 1 and not content["goal_progress"]
    assert "未返回我的昨日" in content["notices"][0]
