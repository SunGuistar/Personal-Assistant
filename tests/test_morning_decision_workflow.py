"""决策型晨报：隔离数据库、假 Agent，验证真实工具传递和数据证据契约。"""
import json
import sqlite3

import pytest
from app.morning_report.graph.workflow import build_workflow
from app.morning_report.services import hub_readonly
from tests.test_morning_stage4_graph import _deps


def test_retired_memory_not_forwarded_or_accepted_as_evidence(fclient):
    from app.morning_report.graph.workflow import _decision_context, _evidence
    from tests.test_morning_stage4_graph import _initial

    state = _initial()
    state["memory"] = [{"id": 99, "content": "已停用的历史偏好"}]
    assert "memory" not in _decision_context(state)
    assert "memories:99" not in _evidence(state, _deps(fclient), "goal_analysis")


def test_no_daily_tech_research(fclient):
    nodes = build_workflow(_deps(fclient)).compile().nodes
    assert "tech_research" not in nodes
    assert "goal_analysis" in nodes and "advice" in nodes


def test_personal_source_is_readonly_and_complete(tmp_path):
    path = tmp_path / "personal.db"
    db = sqlite3.connect(path)
    db.executescript("""
        create table daily_tasks(id integer,task_date text,title text,content text,done integer,completed_at text,updated_at text,is_important integer,task_type text);
        insert into daily_tasks values(1,'2026-11-10','已完成','',1,'2026-11-10T10:00:00+08:00','2026-11-10',1,'daily');
        insert into daily_tasks values(2,'2026-11-10','昨日未完成','',0,null,'2026-11-10',1,'daily');
        insert into daily_tasks values(3,'2026-11-11','今日待办','',0,null,'2026-11-11',1,'daily');
        create table long_term_plans(id integer,title text,description text,goal text,status text,is_important integer,target_date text,updated_at text);
        insert into long_term_plans values(1,'项目','真实目标','完成项目','in_progress',1,'2026-11-20','2026-11-10');
        create table important_infos(id integer,title text,content text,updated_at text);
        create table memos(id integer,title text,content text,updated_at text);
        create table books(id integer,title text,status text,note text,updated_at text);
        create table book_notes(id integer,book_id integer,filename text,created_at text);
    """)
    db.commit(); db.close()
    ctx = hub_readonly.load_readonly_context(path,'2026-11-10T08:00:00+08:00','2026-11-11T08:00:00+08:00')
    assert len(ctx['daily_done']) == 1
    assert ctx['yesterday_pending'][0]['id'] == 2
    assert ctx['today_pending'][0]['id'] == 3
    assert ctx['source_meta']['counts']['daily_tasks'] == 3
    with hub_readonly.readonly_connection(path) as ro:
        with pytest.raises(sqlite3.OperationalError):
            ro.execute("delete from daily_tasks")
    assert sqlite3.connect(path).execute('select count(*) from daily_tasks').fetchone()[0] == 3


@pytest.mark.parametrize("category", ["domestic", "international"])
def test_official_rank_only_ten_original_titles_and_times(category):
    import respx
    from app.morning_report.adapters import chinanews
    html = '<a href="/gn/2026/11-10/99999999.shtml">非榜单内容</a><div class="hotlist"><ul>'
    html += ''.join(f'<li><a title="完整标题{i}" href="/gn/2026/11-10/{10000000+i}.shtml">截断标题</a></li>' for i in range(15))
    html += '</ul></div>'
    with respx.mock(assert_all_called=False) as mock:
        mock.get(chinanews.HOT_PAGES[category]).respond(200, text=html)
        details = []
        for i in range(15):
            # 前两条分别过期和无可靠时间，不能拿第 11 条补位。
            stamp = '2026-11-09T10:00:00+08:00' if i == 0 else '2026-11-10T10:00:00+08:00'
            body = (f'<time datetime="{stamp}"></time>' if i != 1 else '') + '<p>' + '真实来源摘要' * 10 + '</p>'
            details.append(mock.get(f'https://www.chinanews.com.cn/gn/2026/11-10/{10000000+i}.shtml').respond(200, text=body))
        rows = chinanews.fetch_hot_ranked(category, '2026-11-10T08:00:00+08:00', '2026-11-11T08:00:00+08:00')
    assert len(rows) == 10 and sum(r.published_at is not None for r in rows) == 9
    assert rows[0].title == '完整标题0' and rows[0].published_at == '2026-11-09T10:00:00+08:00'
    assert rows[1].published_at is None
    assert [r.raw['rank'] for r in rows] == list(range(1, 11))
    assert all('未公开' in r.raw['ranking_basis'] for r in rows)
    assert sum(r.call_count for r in details) == 10


@pytest.mark.parametrize('stage,tool_name', [('goal_analysis', 'search_personal_records'), ('advice', 'search_task_status')])
def test_runner_executes_only_snapshot_personal_tools(fclient, monkeypatch, stage, tool_name):
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage
    from app.morning_report.graph.subagents import LangChainSubagentRunner
    from app.morning_report.config import MRSettings
    import langchain_openai
    bound = []
    class Model(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            bound.extend(t.name for t in tools)
            return self
    model = Model(responses=[AIMessage(content='', tool_calls=[{'name': tool_name, 'args': {'query': '项目'}, 'id': 'call-test', 'type': 'tool_call'}]), AIMessage(content='{"status":"finished"}')])
    monkeypatch.setattr(langchain_openai, 'ChatOpenAI', lambda **kwargs: model)
    runner = LangChainSubagentRunner(MRSettings())
    runner.configure_context({'daily_pending': [{'source_id': 'daily_tasks:1', 'title': '项目', 'done': False}]}, None)
    result = runner.run(stage, '查询当前项目记录', runner.tools_for(stage))
    assert result == '{"status":"finished"}'
    assert tool_name in bound and not any('historical' in name for name in bound)
    assert runner.last_tool_calls[stage] == 1
    assert runner.evidence[stage][0]['source_id'] == 'daily_tasks:1'


def test_history_tools_removed_and_personal_lookup_stays_in_snapshot(fclient):
    from app.morning_report.services.decision_tools import make_tools
    from app.morning_report.models import ReportVersion
    with fclient.app.state.mr_session_factory() as db:
        db.add(ReportVersion(report_date='2026-11-09', content_md='历史秘密项目', sections={}))
        db.commit()
    tools = make_tools({}, 'goal_analysis')
    assert [t.name for t in tools] == ['search_personal_records']
    assert json.loads(tools[0].invoke({'query': '历史秘密项目'}))['records'] == []
    assert [t.name for t in make_tools({}, 'advice')] == ['search_personal_records', 'search_task_status']


def test_full_personal_enters_agents_but_news_is_excluded(fclient):
    import asyncio
    from tests.test_morning_stage4_graph import TraceSubagents, _initial, _run_graph
    prompts = {}
    class Capture(TraceSubagents):
        def run(self, name, prompt, tools):
            prompts[name] = prompt
            return super().run(name, prompt, tools)
    initial = _initial()
    initial['personal']['daily_pending'] = [{'id': 2, 'source_id': 'daily_tasks:2', 'title': '待办证据XYZ'}]
    asyncio.run(_run_graph(fclient, _deps(fclient, subagents=Capture()), initial))
    for prompt in prompts.values():
        assert '待办证据XYZ' in prompt and 'daily_pending' in prompt
        assert 'news_items:1' not in prompt and '部署稳增长' not in prompt and 'https://example.com/d1' not in prompt
        assert 'ai_daily' not in prompt and 'LangGraph 0.6 发布' not in prompt
    assert 'goal_analysis' in prompts['advice']


def test_missing_personal_never_triggers_evaluation(fclient):
    from app.morning_report.graph.workflow import build_workflow
    nodes = build_workflow(_deps(fclient)).compile().nodes
    assert 'quality_eval' not in nodes



def test_invalid_goal_evidence_and_unanchored_advice_rejected(fclient):
    from tests.test_morning_stage4_graph import _initial
    from app.morning_report.graph.workflow import node_goal_analysis, node_advice
    class Agent:
        def run(self, name, prompt, tools):
            if name == 'goal_analysis':
                return json.dumps({'current_state': {'content': '已完成不存在的项目', 'kind': 'confirmed', 'evidence_ids': ['fake:1']}})
            return json.dumps({'advices': [{'content': '研究宏观产业政策', 'basis': '新闻', 'priority': '今日优先', 'personal_refs': [], 'evidence_ids': ['news_items:1'], 'next_step': '制定产业政策'}]})
    state = _initial(); deps = _deps(fclient, subagents=Agent())
    goal = node_goal_analysis(state, deps)['goal_result']
    assert goal['analysis']['current_state']['kind'] == 'unknown'
    state['goal_result'] = goal
    result = node_advice(state, deps)['advice_result']
    assert result['status'] == 'ok' and result['advices'] == [] and result['rejected_count'] == 1


def test_duplicate_completed_and_invented_estimates_filtered(fclient):
    from tests.test_morning_stage4_graph import _initial
    from app.morning_report.graph.workflow import node_advice
    state = _initial()
    state['personal']['daily_pending'] = [{'source_id': 'daily_tasks:2', 'title': '未完成任务', 'done': False}]
    row = {'content': '推进已有任务', 'basis': '真实未完成任务', 'priority': '今日优先', 'personal_refs': ['daily_tasks:2'],
           'evidence_ids': ['daily_tasks:2'], 'next_step': '确认下一步方案', 'estimated_time': '10分钟', 'expected_value': '收益一万元'}
    class Agent:
        def run(self, name, prompt, tools):
            return json.dumps({'advices': [row, row, {**row, 'personal_refs': ['daily_tasks:1'], 'evidence_ids': ['daily_tasks:1']}]})
    result = node_advice(state, _deps(fclient, subagents=Agent()))['advice_result']
    assert len(result['advices']) == 1 and result['rejected_count'] == 2
    assert result['advices'][0]['estimated_time'] is None and result['advices'][0]['expected_value'] is None


def test_advice_selects_at_most_one_valid_action(fclient):
    from tests.test_morning_stage4_graph import _initial
    from app.morning_report.graph.workflow import node_advice
    from app.morning_report.graph import prompts
    state = _initial()
    state['personal']['daily_pending'] = [{'source_id': 'daily_tasks:2', 'title': '未完成任务', 'done': False}]
    row = {'content': '推进已有任务', 'basis': '真实未完成任务', 'priority': '今日优先',
           'personal_refs': ['daily_tasks:2'], 'evidence_ids': ['daily_tasks:2'], 'next_step': '确认方案'}
    class Agent:
        def run(self, name, prompt, tools):
            assert '最多一个元素' in prompt
            return json.dumps({'advices': [row, {**row, 'content': '另一项行动', 'next_step': '查看资料'}]})
    result = node_advice(state, _deps(fclient, subagents=Agent()))['advice_result']
    assert result['status'] == 'ok' and len(result['advices']) == 1
    assert result['advices'][0]['content'] == '推进已有任务'
    assert result['rejected_count'] == 1
    assert '最多输出 1 条' in prompts.ADVICE_SYSTEM


def test_publish_does_not_write_evaluation_even_for_legacy_state(fclient):
    from tests.test_morning_stage4_graph import _initial
    from app.morning_report.graph.workflow import node_publish
    from app.morning_report.models import Evaluation
    from sqlalchemy import select
    state = _initial()
    state.update(draft='正文', evaluation={'status': 'ok', 'composite': 99},
                 news_selection={}, goal_result={}, advice_result={})
    node_publish(state, _deps(fclient))
    with fclient.app.state.mr_session_factory() as db:
        assert db.execute(select(Evaluation)).first() is None



def test_missing_personal_path_does_not_create_or_fallback(tmp_path):
    path = tmp_path / 'missing.db'
    with pytest.raises(FileNotFoundError):
        hub_readonly.load_readonly_context(path, '2026-11-10T08:00:00+08:00', '2026-11-11T08:00:00+08:00')
    assert not path.exists()


def test_news_and_report_ids_cannot_be_used_as_decision_evidence(fclient):
    from tests.test_morning_stage4_graph import _initial
    from app.morning_report.graph.workflow import node_goal_analysis, node_advice, _evidence
    state = _initial()
    state['personal']['daily_pending'] = [{'source_id': 'daily_tasks:2', 'title': '待办', 'done': False}]
    class Agent:
        evidence = {'goal_analysis': [{'source_id': 'report_versions:1'}]}
        def run(self, name, prompt, tools):
            assert '部署稳增长' not in prompt and '新增中断恢复' not in prompt
            if name == 'goal_analysis':
                return json.dumps({'current_state': {'content': '新闻推断', 'kind': 'confirmed', 'evidence_ids': ['news_items:1']}})
            return json.dumps({'advices': [{'content': '行动', 'basis': '新闻', 'priority': '今日优先',
                'personal_refs': ['daily_tasks:2'], 'evidence_ids': ['news_items:1'], 'next_step': '开始'}]})
    deps = _deps(fclient, subagents=Agent())
    assert 'news_items:1' not in _evidence(state, deps, 'goal_analysis')
    assert 'report_versions:1' not in _evidence(state, deps, 'goal_analysis')
    goal = node_goal_analysis(state, deps)['goal_result']
    assert goal['analysis']['current_state']['kind'] == 'unknown'
    state['goal_result'] = {}
    assert node_advice(state, deps)['advice_result']['advices'] == []
