"""清理审核出入参 Schema。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class KeepReason(BaseModel):
    chunk_id: str
    reason: str  # protected / mixed / unresolved


class CandidateOut(BaseModel):
    id: int
    review_id: int
    chat_id: str
    chat_name: str
    msg_date: str
    snapshot_count: int
    normalized_count: int
    chunk_delete_count: int
    chunk_keep_count: int
    keep_reasons: list[KeepReason] = []
    size_estimate: int
    state: str
    error: str = ""


class ReviewOut(BaseModel):
    id: int
    week_id: str
    status: str
    confirmed_at: str | None = None
    reviewed_at: str | None = None
    candidates: list[CandidateOut] = []


class CleanupStatusOut(BaseModel):
    banner: dict | None = None
    reviews: list[ReviewOut] = []


class ConfirmIn(BaseModel):
    candidate_ids: list[int] = Field(min_length=1)


class ExecuteIn(BaseModel):
    review_id: int


class RetryIn(BaseModel):
    review_id: int
    candidate_ids: list[int] = Field(min_length=1)


class ExecuteOut(BaseModel):
    task_id: int
    status: str


class ExecuteResultOut(BaseModel):
    deleted_groups: int
    failed_groups: int
