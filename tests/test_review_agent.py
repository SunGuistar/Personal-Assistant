"""每周回顾 Agent 测试：只读工具输出、脚本化模型驱动的真实 Agent 往返、零业务写。

工具 docstring = 提示词（AGENTS 铁律 5），本组测试同时充当工具行为的回归基线。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

import pytest
from alembic import command
from alembic.config import Config
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import Book, DailyTask, ImportantInfo, LongTermPlan, Memo
from app.review_agent import build_agent
from app.review_agent.agent import build_system_prompt
from app.review_agent.tools import build_tools
from app.services import review_stats

WEEK = "2026-06-01"


@pytest.fixture()
def session(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'agent.db'}"
    os.environ["PH_DATABASE_URL"] = db_url
    command.upgrade(Config(str(Path(__file__).resolve().parent.parent / "alembic.ini")), "head")
    engine = create_engine(db_url)
    factory = sessionmaker(bind=engine)
    with factory() as s:
        yield s
    engine.dispose()


@pytest.fixture()
def seeded(session):
    session.add_all([
        DailyTask(task_date=WEEK, title="写周报功能", done=1, completed_at="2026-06-02T10:00:00"),
        DailyTask(task_date="2026-05-20", title="历史积压", done=0),
        LongTermPlan(title="核心目标", goal="做出每周回顾", target_date="2026-06-07"),
        Memo(title="搁置想法", updated_at="2026-05-01T10:00:00"),
        ImportantInfo(title="设计原则", content="本地优先"),
        Book(title="在读的书", status="reading"),
    ])
    session.commit()
    return session


def _tool_map(tools):
    return {tool.name: tool for tool in tools}


# ---------- 工具输出 ----------


def test_task_stats_tool(seeded):
    tools = _tool_map(build_tools(seeded, WEEK))
    out = tools["get_task_stats"].invoke({})
    assert "本周归属任务 1 项，完成 1 项" in out
    assert "周末仍逾期/积压 1 项" in out
    assert "历史积压" in out and "[id=" in out


def test_week_tasks_tool(seeded):
    tools = _tool_map(build_tools(seeded, WEEK))
    out = tools["get_week_tasks"].invoke({})
    assert "写周报功能" in out and "已完成(2026-06-02T10:00)" in out


def test_plans_tool(seeded):
    tools = _tool_map(build_tools(seeded, WEEK))
    out = tools["get_plans_overview"].invoke({})
    assert "核心目标" in out and "做出每周回顾" in out and "目标日期: 2026-06-07" in out


def test_memos_and_infos_tools(seeded):
    tools = _tool_map(build_tools(seeded, WEEK))
    memos = tools["get_memos_overview"].invoke({})
    assert "搁置想法" in memos and "已搁置" in memos
    infos = tools["get_important_infos"].invoke({})
    assert "设计原则" in infos and "本地优先" in infos


def test_reading_tool(seeded):
    tools = _tool_map(build_tools(seeded, WEEK))
    out = tools["get_reading_overview"].invoke({})
    assert "在读的书" in out


def test_six_tools_exactly(seeded):
    tools = build_tools(seeded, WEEK)
    assert [t.name for t in tools] == [
        "get_task_stats",
        "get_week_tasks",
        "get_plans_overview",
        "get_memos_overview",
        "get_important_infos",
        "get_reading_overview",
    ]


# ---------- 脚本化模型驱动的 Agent 往返 ----------


class ScriptedModel(GenericFakeChatModel):
    """支持 bind_tools 的脚本化模型：按序输出 AIMessage（可带 tool_calls）。"""

    messages: Iterator
    model_name: str = "fake-review-agent"

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):  # noqa: ANN001
        return self


def _business_counts(session):
    return {
        "tasks": len(session.execute(select(DailyTask)).scalars().all()),
        "plans": len(session.execute(select(LongTermPlan)).scalars().all()),
        "memos": len(session.execute(select(Memo)).scalars().all()),
        "infos": len(session.execute(select(ImportantInfo)).scalars().all()),
        "books": len(session.execute(select(Book)).scalars().all()),
    }


def test_agent_tool_roundtrip_and_no_business_write(seeded):
    model = ScriptedModel(
        messages=iter([
            AIMessage(
                content="",
                tool_calls=[{"name": "get_task_stats", "args": {}, "id": "call_1"}],
            ),
            AIMessage(content="本周完成 1 项任务，另有 1 项历史积压未处理。"),
        ])
    )
    agent = build_agent(seeded, WEEK, "2026-06-07", llm=model)
    before = _business_counts(seeded)

    result = agent.invoke({"messages": [HumanMessage("帮我分析本周任务情况")]})
    final = result["messages"][-1].content
    assert "历史积压" in final

    # Agent 全程只读：五张业务表零变化
    assert _business_counts(seeded) == before


def test_system_prompt_injects_week_and_rules():
    prompt = build_system_prompt("2026-06-01", "2026-06-07")
    assert "2026-06-01 至 2026-06-07" in prompt
    assert "今天是" in prompt
    assert "推断" in prompt  # 要求显式声明语义推断
