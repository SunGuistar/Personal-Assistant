"""阅读管理出入参 Schema。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

BookStatus = Literal["todo", "reading", "done"]


class BookIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    author: str = ""
    note: str = ""
    status: BookStatus = "todo"
    is_important: bool = False


class BookPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    author: str | None = None
    note: str | None = None
    status: BookStatus | None = None
    is_important: bool | None = None


class BookOut(BaseModel):
    id: int
    title: str
    author: str
    note: str
    status: str
    is_important: bool
    note_count: int
    created_at: str
    updated_at: str


class NoteOut(BaseModel):
    id: int
    book_id: int
    filename: str
    size: int
    uploaded_at: str


class NoteMdIn(BaseModel):
    filename: str | None = Field(default=None, max_length=200)
    content: str = Field(min_length=1)
