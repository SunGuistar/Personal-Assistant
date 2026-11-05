"""重要信息与随手备忘出入参 Schema。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class InfoIn(BaseModel):
    title: str = Field(min_length=1, max_length=128)
    content: str = ""


class InfoPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=128)
    content: str | None = None


class InfoOut(BaseModel):
    id: int
    title: str
    content: str
    sort_order: int
    created_at: str
    updated_at: str


class InfoReorderIn(BaseModel):
    """重要信息整体重排：ordered_ids 为全部记录的完整展示顺序。"""

    ordered_ids: list[int]


class MemoOut(BaseModel):
    content: str


class MemoIn(BaseModel):
    content: str = Field(default="", max_length=512 * 1024)  # 便签上限 512KB
    expected: str | None = None  # 客户端已知的前一次内容（可选，防乱序覆盖）
