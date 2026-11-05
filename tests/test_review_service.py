"""周报草稿/建议状态机与建议生成测试（隔离临时库 + FakeLLM）。

覆盖：草稿幂等、依据校验（含周期错配）、建议生成（校验/一般性建议/失败不破坏）、
重新生成规则、并发锁、处置流转、确认门禁与同周唯一约束。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import DailyTask, LongTermPlan, Memo, WeeklyReview, WeeklyReviewSuggestion
from app.services import review_service, review_stats

WEEK = "2026-06-01"  # 周一


@pytest.fixture()
def session(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'review.db'}"
    os.environ["PH_DATABASE_URL"] = db_url
    command.upgrade(Config(str(Path(__file__).resolve().parent.parent / "alembic.ini")), "head")
    engine = create_engine(db_url)
    factory = sessionmaker(bind=engine)
    with factory() as s:
        yield s
    engine.dispose()


class FakeSuggestLLM:
    """建议生成 FakeLLM：返回固定 JSON（analysis + 含有效/无效依据的建议）。"""

    model_name = "fake-suggest"

    def __init__(self, payload: dict | None = None, fail: bool = False):
        self.calls = 0
        self.fail = fail
        self.payload = payload or {
            "analysis": "本周完成度尚可，积压主要来自历史任务。",
            "suggestions": [
                {
                    "content": "优先清理历史积压任务",
                    "basis": [{"source_type": "daily_task", "source_id": 1, "reason": "该任务已逾期两周"}],
                },
                {
                    "content": "推进个人助手周报功能",
                    "basis": [
                        {"source_type": "long_term_plan", "source_id": 1, "reason": "核心目标"},
                        {"source_type": "daily_task", "source_id": 9999, "reason": "不存在的任务"},
                    ],
                },
                {
                    "content": "保持阅读习惯",
                    "basis": [],
                },
            ],
        }

    def invoke(self, prompt: str):
        self.calls += 1
        if self.fail:
            raise RuntimeError("模型 API 挂了")

        class _Resp:
            content = json.dumps(self.payload, ensure_ascii=False)
            usage_metadata = {"input_tokens": 100, "output_tokens": 50}

        return _Resp()


def _seed(session):
    task = DailyTask(task_date=WEEK, title="本周任务")
    old_task = DailyTask(task_date="2026-05-20", title="历史积压")  # 周期外依据
    plan = LongTermPlan(title="核心目标", goal="做出周报")
    memo = Memo(title="搁置想法")
    session.add_all([task, old_task, plan, memo])
    session.commit()
    return task, old_task, plan, memo


# ---------- 草稿生命周期 ----------


def test_get_or_create_review_idempotent_and_normalizes(session):
    review = review_service.get_or_create_review(session, "2026-06-03")  # 周三 → 归一化
    assert review.week_start == WEEK and review.week_end == "2026-06-07"
    stats = json.loads(review.stats_json)
    assert stats["week_start"] == WEEK
    again = review_service.get_or_create_review(session, WEEK)
    assert again.id == review.id
    assert session.execute(select(WeeklyReview)).scalars().one()


def test_update_draft_and_confirmed_readonly(session):
    review = review_service.get_or_create_review(session, WEEK)
    updated = review_service.update_draft(session, review.id, analysis_md="分析", user_notes="补充")
    assert updated["analysis_md"] == "分析" and updated["user_notes"] == "补充"

    review.status = "confirmed"
    review.confirmed_at = "2026-06-08T10:00:00"
    session.commit()
    with pytest.raises(Exception) as exc_info:
        review_service.update_draft(session, review.id, user_notes="x")
    assert exc_info.value.status_code == 409


# ---------- 依据校验 ----------


def test_validate_basis_happy_path(session):
    task, _, plan, memo = _seed(session)
    review = review_service.get_or_create_review(session, WEEK)
    ok = review_service.validate_basis(
        session, review, {"source_type": "daily_task", "source_id": task.id, "reason": "本周任务"}
    )
    assert ok and "本周任务" in ok["fact"] and ok["source_type"] == "daily_task"
    ok_plan = review_service.validate_basis(
        session, review, {"source_type": "long_term_plan", "source_id": plan.id, "reason": "目标"}
    )
    assert ok_plan and "核心目标" in ok_plan["fact"]
    ok_memo = review_service.validate_basis(
        session, review, {"source_type": "memo", "source_id": memo.id, "reason": "缓冲池"}
    )
    assert ok_memo


def test_validate_basis_rejects_bad_reference(session):
    task, old_task, _, _ = _seed(session)
    review = review_service.get_or_create_review(session, WEEK)
    # 不存在的类型 / id / 空理由 / 周期外任务
    assert review_service.validate_basis(
        session, review, {"source_type": "wechat", "source_id": task.id, "reason": "x"}
    ) is None
    assert review_service.validate_basis(
        session, review, {"source_type": "daily_task", "source_id": 9999, "reason": "x"}
    ) is None
    assert review_service.validate_basis(
        session, review, {"source_type": "daily_task", "source_id": task.id, "reason": " "}
    ) is None
    assert review_service.validate_basis(
        session, review, {"source_type": "daily_task", "source_id": old_task.id, "reason": "周期外"}
    ) is None


# ---------- 建议生成 ----------


def test_generate_suggestions_validates_basis(session):
    task, _, plan, _ = _seed(session)
    review = review_service.get_or_create_review(session, WEEK)
    llm = FakeSuggestLLM()
    suggestions = review_service.generate_suggestions(session, review.id, llm=llm)

    assert llm.calls == 1
    assert len(suggestions) == 3
    # 第 1 条：有效任务依据（保留 + 事实摘要）
    assert suggestions[0]["basis"][0]["source_id"] == task.id
    assert "本周任务" in suggestions[0]["basis"][0]["fact"]
    assert not suggestions[0]["is_general"]
    # 第 2 条：无效依据（id=9999）被剔除，只保留计划依据
    assert len(suggestions[1]["basis"]) == 1
    assert suggestions[1]["basis"][0]["source_type"] == "long_term_plan"
    # 第 3 条：无依据 → 一般性建议
    assert suggestions[2]["basis"] == [] and suggestions[2]["is_general"]
    # analysis 已写入草稿
    assert "完成度尚可" in session.get(WeeklyReview, review.id).analysis_md


def test_generate_records_token_usage(session):
    _seed(session)
    review = review_service.get_or_create_review(session, WEEK)
    review_service.generate_suggestions(session, review.id, llm=FakeSuggestLLM())
    from app.models import TokenUsage

    rows = session.execute(select(TokenUsage)).scalars().all()
    assert len(rows) == 1
    assert rows[0].ref == f"weekly_review:suggest:{review.id}"
    assert rows[0].output_tokens == 50


def test_generate_failure_keeps_existing(session):
    _seed(session)
    review = review_service.get_or_create_review(session, WEEK)
    review_service.generate_suggestions(session, review.id, llm=FakeSuggestLLM())
    before = review_service.list_suggestions(session, review.id)

    with pytest.raises(RuntimeError):
        review_service.generate_suggestions(session, review.id, llm=FakeSuggestLLM(fail=True))
    after = review_service.list_suggestions(session, review.id)
    assert [s["id"] for s in after] == [s["id"] for s in before]
    assert all(s["status"] == "pending" for s in after)


def test_regenerate_replaces_pending_but_blocks_dispositioned(session):
    _seed(session)
    review = review_service.get_or_create_review(session, WEEK)
    first = review_service.generate_suggestions(session, review.id, llm=FakeSuggestLLM())
    # 全部 pending → 可重新生成：pending 行被替换（数量随新输出变化）
    second_llm = FakeSuggestLLM(
        payload={"analysis": "第二轮分析", "suggestions": [{"content": "只有一条", "basis": []}]}
    )
    second = review_service.generate_suggestions(session, review.id, llm=second_llm)
    assert len(first) == 3 and len(second) == 1
    assert second[0]["content"] == "只有一条"
    assert len(session.execute(select(WeeklyReviewSuggestion)).scalars().all()) == 1
    assert session.get(WeeklyReview, review.id).analysis_md == "第二轮分析"
    # 处置一条后 → 禁止重新生成
    review_service.resolve_suggestion(session, second[0]["id"], "accept")
    with pytest.raises(Exception) as exc_info:
        review_service.generate_suggestions(session, review.id, llm=FakeSuggestLLM())
    assert exc_info.value.code == "suggestions_dispositioned"


def test_generate_concurrency_lock(session):
    _seed(session)
    review = review_service.get_or_create_review(session, WEEK)
    lock = review_service._gen_lock(review.id)
    assert lock.acquire(blocking=False)
    try:
        with pytest.raises(Exception) as exc_info:
            review_service.generate_suggestions(session, review.id, llm=FakeSuggestLLM())
        assert exc_info.value.code == "suggestion_generating"
    finally:
        lock.release()


# ---------- 处置与确认 ----------


def _full_flow(session):
    _seed(session)
    review = review_service.get_or_create_review(session, WEEK)
    ids = [s["id"] for s in review_service.generate_suggestions(session, review.id, llm=FakeSuggestLLM())]
    return review, ids


def test_resolve_suggestion_flows(session):
    review, ids = _full_flow(session)
    accepted = review_service.resolve_suggestion(session, ids[0], "accept")
    assert accepted["status"] == "accepted" and accepted["final_content"] == accepted["content"]

    modified = review_service.resolve_suggestion(session, ids[1], "modify", final_content="改成别的")
    assert modified["status"] == "modified" and modified["final_content"] == "改成别的"

    rejected = review_service.resolve_suggestion(session, ids[2], "reject", reject_reason="不重要")
    assert rejected["status"] == "rejected" and rejected["reject_reason"] == "不重要"

    with pytest.raises(Exception) as exc_info:
        review_service.resolve_suggestion(session, ids[0], "modify", final_content="  ")
    assert exc_info.value.status_code == 422
    with pytest.raises(Exception) as exc_info:
        review_service.resolve_suggestion(session, ids[0], "hug")
    assert exc_info.value.status_code == 400


def test_confirm_blocked_by_pending(session):
    review, ids = _full_flow(session)
    review_service.resolve_suggestion(session, ids[0], "accept")
    with pytest.raises(Exception) as exc_info:
        review_service.confirm_review(session, review.id)
    assert exc_info.value.code == "suggestions_pending"
    # 确认失败后仍是草稿
    assert session.get(WeeklyReview, review.id).status == "draft"


def test_confirm_happy_path_and_report(session):
    review, ids = _full_flow(session)
    review_service.resolve_suggestion(session, ids[0], "accept")
    review_service.resolve_suggestion(session, ids[1], "modify", final_content="改写后的建议")
    review_service.resolve_suggestion(session, ids[2], "reject", reject_reason="无必要")

    result = review_service.confirm_review(
        session, review.id, analysis_md="最终分析", user_notes="我的补充"
    )
    assert result["status"] == "confirmed" and result["confirmed_at"]
    row = session.get(WeeklyReview, review.id)
    assert row.report_md
    assert "最终分析" in row.report_md and "我的补充" in row.report_md
    assert "改写后的建议" in row.report_md and "（已修改）" in row.report_md
    assert "保持阅读习惯" in row.report_md  # 拒绝建议也留痕
    # 正式周报只读
    with pytest.raises(Exception) as exc_info:
        review_service.confirm_review(session, review.id)
    assert exc_info.value.code == "review_confirmed"


def test_confirmed_week_unique_constraint(session):
    review, ids = _full_flow(session)
    for sid in ids:
        review_service.resolve_suggestion(session, sid, "accept")
    review_service.confirm_review(session, review.id)

    # 绕过 get_or_create 直接插同周第二份草稿并确认 → 唯一索引兜底 409
    second = WeeklyReview(week_start=WEEK, week_end="2026-06-07", status="draft")
    session.add(second)
    session.commit()
    with pytest.raises(Exception) as exc_info:
        review_service.confirm_review(session, second.id)
    assert exc_info.value.code == "confirmed_week_exists"


def test_confirm_without_suggestions_allowed(session):
    _seed(session)
    review = review_service.get_or_create_review(session, WEEK)
    result = review_service.confirm_review(session, review.id, user_notes="直接确认")
    assert result["status"] == "confirmed"
    assert "下周建议（已处置）" in session.get(WeeklyReview, review.id).report_md
