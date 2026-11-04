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


class PlanPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    status: PlanStatus | None = None
    target_date: IsoDate | None = None


class PlanOut(BaseModel):
    id: int
    title: str
    description: str
    status: str
    target_date: str | None
    created_at: str
    updated_at: str


class PlanDetailOut(PlanOut):
    task_ids: list[int] = []


class DailyTaskIn(BaseModel):
    task_date: IsoDate
    title: str = Field(min_length=1, max_length=200)
    plan_id: int | None = None


class DailyTaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    done: bool | None = None
    plan_id: int | None = None


class DailyTaskOut(BaseModel):
    id: int
    plan_id: int | None
    task_date: str
    title: str
    done: bool
    sort_order: int
    moved_from_date: str | None
    created_at: str
    updated_at: str


class MoveTaskIn(BaseModel):
    target_date: IsoDate


class ReorderIn(BaseModel):
    date: IsoDate
    ordered_ids: list[int]
