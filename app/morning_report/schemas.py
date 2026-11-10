"""晨报 API 出入参 schema（snake_case）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class StatusOut(BaseModel):
    db_ok: bool
    mr_schema_version: int
    schedule_enabled: bool
    today: str
    today_run: dict | None  # run_records(kind=generate) 当日最新一条摘要
    news_counts: dict  # {domestic: n, international: n, ai: n} 当日窗口


class MemoryIn(BaseModel):
    kind: str = Field(pattern="^(interest|action_pref|supplement_goal|other)$")
    content: str = Field(min_length=1, max_length=2000)


class MemoryPatch(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=2000)
    enabled: bool | None = None


class MemoryOut(BaseModel):
    id: int
    kind: str
    content: str
    enabled: bool
    confirmed: bool
    source: str
    created_at: str
    updated_at: str


class RunOut(BaseModel):
    id: int
    run_date: str
    kind: str
    status: str
    window_start: str | None
    window_end: str | None
    error: str | None
    started_at: str | None
    finished_at: str | None


class LogOut(BaseModel):
    id: int
    at: str
    stage: str
    level: str
    message: str
    detail: dict | None


class PersonalContextOut(BaseModel):
    window_start: str
    window_end: str
    daily_done: list[dict]
    daily_pending: list[dict]
    longterm_highlight: list[dict]
    longterm_active: list[dict]
    important_infos: list[dict]
