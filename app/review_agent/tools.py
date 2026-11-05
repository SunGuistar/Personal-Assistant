"""每周回顾 Agent：只读工具集（阶段一）。

六个工具全部只读：只调用 services 层的 list/read 函数与确定性统计，
不提供任何写能力——即使提示词被注入"修改/删除任务"也没有工具可调，
从机制上保证 Agent 不修改业务数据（已批准原则 4）。

工具由 build_tools(session) 工厂生成，绑定本次回顾的周期与数据库会话。
注意：@tool 函数的 docstring 与参数签名会暴露给 LLM，改动 docstring = 改变模型行为。
"""

from __future__ import annotations

import json

from langchain_core.tools import tool
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DailyTask, ImportantInfo
from ..services import review_stats

_LIST_LIMIT = 20


def _lines(items, formatter):
    if not items:
        return ["  （无）"]
    lines = [formatter(item) for item in items[:_LIST_LIMIT]]
    if len(items) > _LIST_LIMIT:
        lines.append(f"  … 等共 {len(items)} 条")
    return lines


def build_tools(session: Session, week_start: str) -> list:
    """生成绑定会话与回顾周期的只读工具列表。"""
    week = review_stats.week_bounds(week_start)[0]

    @tool
    def get_task_stats() -> str:
        """获取本周任务的确定性统计：归属/完成/逾期数量、类型与重要分布。
        做总体分析前先调用本工具摸底；所有数字是代码计算的，直接引用即可。"""
        stats = review_stats.weekly_task_stats(session, week)
        belonging = stats["belonging"]
        lines = [
            f"周期 {stats['week_start']} ~ {stats['week_end']}",
            f"本周归属任务 {belonging['total']} 项，完成 {belonging['done']} 项；"
            f"本周标记完成 {stats['done_in_week']['total']} 项"
            f"（含历史遗留清掉 {stats['done_in_week']['carried_in_done']['total']} 项）；"
            f"本周新建 {stats['created_in_week']} 项",
            "类型分布: "
            + "、".join(
                f"{k} {v['total']}(完成{v['done']})" for k, v in belonging["by_type"].items()
            ),
            f"重要任务 {belonging['important']['total']} 项，完成 {belonging['important']['done']} 项",
            f"周末仍逾期/积压 {stats['overdue_at_week_end']['total']} 项:",
        ]
        lines += _lines(
            stats["overdue_at_week_end"]["items"],
            lambda t: f"  [id={t['id']}] {t['title']}（{t['task_date']}，{t['task_type_label']}）",
        )
        return "\n".join(lines)

    @tool
    def get_week_tasks() -> str:
        """列出本周归属的每条任务明细（标题/类型/重要/完成状态/完成时间）。
        需要核对具体任务内容、完成时间或备注时调用。"""
        start, end = review_stats.week_bounds(week)
        rows = session.execute(
            select(DailyTask)
            .where(DailyTask.task_date >= start, DailyTask.task_date <= end)
            .order_by(DailyTask.task_date, DailyTask.id)
        ).scalars().all()
        if not rows:
            return "本周没有归属任务。"
        lines = [f"本周归属任务明细（{len(rows)} 项，按日期）:"]
        for task in rows:
            state = (
                f"已完成({task.completed_at[:16]})"
                if task.done and task.completed_at
                else ("已完成" if task.done else "未完成")
            )
            important = "，重要" if task.is_important else ""
            note = f"，备注: {task.content[:60]}" if task.content else ""
            lines.append(
                f"  [id={task.id}] {task.task_date} {task.title}"
                f"（{task.task_type}{important}，{state}{note}）"
            )
        return "\n".join(lines)

    @tool
    def get_plans_overview() -> str:
        """获取长期计划现状：活动计划（含具体目标/目标日期）与本周内完成的计划。
        分析目标推进情况时调用。"""
        snapshot = review_stats.weekly_plan_snapshot(session, week)
        lines = [f"活动长期计划 {snapshot['active']['total']} 项:"]
        lines += _lines(
            snapshot["active"]["items"],
            lambda p: (
                f"  [id={p['id']}] {p['title']}（目标: {p['goal'] or '无'}，"
                f"目标日期: {p['target_date'] or '未设'}，"
                f"{'重要' if p['is_important'] else '普通'}，{p['status']}）"
            ),
        )
        if snapshot["target_date_in_week"]:
            lines.append("目标日期落在本周的活动计划:")
            lines += [f"  [id={p['id']}] {p['title']}" for p in snapshot["target_date_in_week"]]
        if snapshot["completed_in_week"]:
            lines.append("本周完成的长期计划:")
            lines += [
                f"  [id={p['id']}] {p['title']}（完成于 {p['completed_at'][:10]}）"
                for p in snapshot["completed_in_week"]
            ]
        return "\n".join(lines)

    @tool
    def get_memos_overview() -> str:
        """获取随手备忘缓冲池：全部备忘标题与搁置情况。
        寻找长期搁置想法、可转任务的事项时调用。"""
        snapshot = review_stats.memo_snapshot(session, week)
        lines = [f"随手备忘共 {snapshot['total']} 条，搁置（久未更新）{snapshot['stale']} 条:"]
        lines += _lines(
            snapshot["items"]["items"],
            lambda m: (
                f"  [id={m['id']}] {m['title']}（更新于 {(m['updated_at'] or '')[:10]}"
                f"{'，已搁置' if m['stale'] else ''}）"
            ),
        )
        return "\n".join(lines)

    @tool
    def get_important_infos() -> str:
        """获取右侧栏重要信息的标题与内容（设计原则、个人规则等）。
        仅作参考上下文：这些是长期参考，不代表当前必须完成的任务。"""
        snapshot = review_stats.important_info_snapshot(session)
        rows = session.execute(
            select(ImportantInfo).order_by(ImportantInfo.sort_order, ImportantInfo.id)
        ).scalars().all()
        lines = [f"重要信息共 {snapshot['total']} 条:"]
        for row in rows[:_LIST_LIMIT]:
            content = (row.content or "")[:120].replace("\n", " ")
            lines.append(f"  [id={row.id}] {row.title}: {content}")
        return "\n".join(lines)

    @tool
    def get_reading_overview() -> str:
        """获取阅读现状：各状态书籍数量、正在读的书与笔记数、本周新增笔记。
        分析阅读进展时调用。"""
        snapshot = review_stats.reading_snapshot(session, week)
        lines = [
            f"书籍共 {snapshot['total']} 本，状态分布: "
            + "、".join(f"{k} {v}" for k, v in snapshot["by_status"].items()),
            f"本周新增笔记 {snapshot['notes_added_in_week']} 份",
        ]
        if snapshot["reading"]:
            lines.append("正在读:")
            lines += [
                f"  [id={b['id']}] {b['title']}（笔记 {b['note_count']} 份）"
                for b in snapshot["reading"]
            ]
        if snapshot["updated_in_week"]:
            lines.append("本周有更新的书:")
            lines += [f"  [id={b['id']}] {b['title']}" for b in snapshot["updated_in_week"]]
        return "\n".join(lines)

    return [
        get_task_stats,
        get_week_tasks,
        get_plans_overview,
        get_memos_overview,
        get_important_infos,
        get_reading_overview,
    ]
