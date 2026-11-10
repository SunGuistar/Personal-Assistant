"""重要信息（SQLite 多条记录）与随手备忘（SQLite 多条记录）出入参 Schema。

两者数据结构相同但业务概念独立（重要信息=长期知识；随手备忘=待处理想法），
不合并为同一张表；前端复用卡片/编辑弹窗组件。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .plan import TaskType


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


class MemoIn(BaseModel):
    title: str = Field(min_length=1, max_length=128)
    content: str = ""
    task_type: TaskType = "daily"  # 与每日任务同一套类型（展示/转回时恢复）


class MemoPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=128)
    content: str | None = None
    task_type: TaskType | None = None  # 新增后允许修改


class MemoOut(BaseModel):
    id: int
    title: str
    content: str
    task_type: str = ""  # 任务类型（与每日任务同一套；空=存量未保存，按 daily 回退）
    sort_order: int
    created_at: str
    updated_at: str


class MemoReorderIn(BaseModel):
    """随手备忘整体重排：ordered_ids 为全部记录的完整展示顺序。"""

    ordered_ids: list[int]
