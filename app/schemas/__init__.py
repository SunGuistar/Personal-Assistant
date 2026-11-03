"""出参 Schema（snake_case，与 API 约定一致）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str


class TaskOut(BaseModel):
    id: int
    kind: str
    status: str
    progress: int
    result: dict[str, Any] | None = None
    error: str | None = None

    model_config = {"from_attributes": True}
