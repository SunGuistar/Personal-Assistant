"""资讯中心出入参 Schema（snake_case，与 API 约定一致；PRD §2.2 最终版）。

收藏/已读等平台功能已取消：库中字段保留，但不再出现在对外接口中。
"""

from __future__ import annotations

from pydantic import BaseModel


class NewsItemOut(BaseModel):
    id: int
    title: str
    url: str
    source: str
    topic: str
    published_at: str
    raw_summary: str
    title_zh: str = ""
    summary_zh: str = ""
    translate_status: str = ""
    score: float
    effective_score: float
    rank: int


class NewsTopOut(BaseModel):
    items: list[NewsItemOut]
    total: int
    generated_at: str


class NewsRefreshOut(BaseModel):
    task_id: int
    status: str


class NewsStatusOut(BaseModel):
    last_refresh: dict | None = None
    refresh_minutes: int
    stale: bool
