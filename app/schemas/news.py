"""资讯中心出入参 Schema（snake_case，与 API 约定一致）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

NewsSort = Literal["latest", "top"]


class NewsSourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    kind: Literal["rss", "hn"]
    endpoint: str = Field(min_length=1, max_length=512)
    enabled: bool = True
    weight: float = Field(default=1.0, ge=0.0, le=10.0)


class NewsSourcePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    endpoint: str | None = Field(default=None, min_length=1, max_length=512)
    enabled: bool | None = None
    weight: float | None = Field(default=None, ge=0.0, le=10.0)


class NewsSourceOut(BaseModel):
    id: int
    name: str
    kind: str
    endpoint: str
    enabled: bool
    weight: float
    created_at: str
    updated_at: str


class NewsItemPatch(BaseModel):
    is_favorite: bool | None = None
    is_read: bool | None = None


class NewsItemOut(BaseModel):
    id: int
    title: str
    url: str
    source: str
    source_id: int | None
    topic: str
    published_at: str
    raw_summary: str
    norm_heat: float
    score: float
    is_favorite: bool
    is_read: bool
    fetched_at: str
    created_at: str
    updated_at: str


class NewsItemListOut(BaseModel):
    items: list[NewsItemOut]
    total: int
    page: int
    page_size: int


class NewsRefreshOut(BaseModel):
    task_id: int
    status: str


class NewsStatusOut(BaseModel):
    last_refresh: dict | None = None
    refresh_minutes: int
    stale: bool


class SourceFailure(BaseModel):
    source: str
    error: str
