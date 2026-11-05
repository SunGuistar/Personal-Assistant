"""计划管理出入参 Schema（snake_case，与 API 约定一致）。"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field

PlanStatus = Literal["in_progress", "completed", "on_hold"]


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
    status: PlanStatus = "in_progress"
    target_date: IsoDate | None = None
    is_important: bool = False


class PlanPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    status: PlanStatus | None = None
    target_date: IsoDate | None = None
    is_important: bool | None = None


class PlanOut(BaseModel):
    id: int
    title: str
    description: str
    status: str
    target_date: str | None
    is_important: bool
    sort_order: int
    completed_at: str | None
    created_at: str
    updated_at: str


class PlanDetailOut(PlanOut):
    task_ids: list[int] = []


class DailyTaskIn(BaseModel):
    task_date: IsoDate
    title: str = Field(min_length=1, max_length=200)
    plan_id: int | None = None  # 历史遗留：关联入口已从 UI 移除，字段保留兼容
    is_important: bool = False


class DailyTaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    done: bool | None = None
    plan_id: int | None = None
    is_important: bool | None = None


class DailyTaskOut(BaseModel):
    id: int
    plan_id: int | None
    task_date: str
    title: str
    done: bool
    sort_order: int
    is_important: bool
    completed_at: str | None
    moved_from_date: str | None
    created_at: str
    updated_at: str


class MoveTaskIn(BaseModel):
    target_date: IsoDate


class ReorderIn(BaseModel):
    date: IsoDate
    scope: Literal["today", "overdue"] = "today"  # overdue=更早日期未完成任务分区
    ordered_ids: list[int]


class PlanReorderIn(BaseModel):
    """长期计划整体重排：ordered_ids 为当前活动计划的完整展示顺序（重要在前）。"""

    ordered_ids: list[int]
