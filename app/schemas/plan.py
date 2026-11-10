"""计划管理出入参 Schema（snake_case，与 API 约定一致）。

2026-11 综合优化轮：daily_tasks 与长期计划彻底独立（plan_id 全链路移除）；
每日任务统一排序（今日 + 逾期一个列表，重要 > sort_order）；长期计划新增 goal。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field

PlanStatus = Literal["in_progress", "completed", "on_hold"]
TaskType = Literal["daily", "feature_add", "feature_optimize", "idea"]  # 顺序即类型排序顺序


def _check_real_date(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise ValueError("日期必须是 YYYY-MM-DD 格式的真实日期")
    return value


IsoDate = Annotated[str, AfterValidator(_check_real_date)]


class PlanIn(BaseModel):
    title: str = Field(min_length=1, max_length=128)
    description: str = ""
    goal: str | None = None  # 具体目标（可选多行文本）
    status: PlanStatus = "in_progress"
    target_date: IsoDate | None = None
    is_important: bool = False


class PlanPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    goal: str | None = None  # 传 null 或空串清空目标
    status: PlanStatus | None = None
    target_date: IsoDate | None = None
    is_important: bool | None = None


class PlanOut(BaseModel):
    id: int
    title: str
    description: str
    goal: str | None
    status: str
    target_date: str | None
    is_important: bool
    sort_order: int
    completed_at: str | None
    created_at: str
    updated_at: str


class DailyTaskIn(BaseModel):
    task_date: IsoDate
    title: str = Field(min_length=1, max_length=200)
    content: str | None = None  # 任务内容/备注（可选）
    task_type: TaskType = "daily"
    is_important: bool = False


class DailyTaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = None
    done: bool | None = None  # 可反复切换：完成记完成时间，取消完成清除并回到未完成区
    task_type: TaskType | None = None
    is_important: bool | None = None


class DailyTaskOut(BaseModel):
    id: int
    task_date: str
    title: str
    content: str | None
    task_type: str
    done: bool
    sort_order: int
    is_important: bool
    completed_at: str | None
    moved_from_date: str | None
    created_at: str
    updated_at: str


class PlanReorderIn(BaseModel):
    """长期计划整体重排：ordered_ids 为当前活动计划的完整展示顺序（重要在前）。"""

    ordered_ids: list[int]
