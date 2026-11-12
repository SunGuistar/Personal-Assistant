"""阅读管理出入参 Schema。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

BookStatus = Literal["todo", "reading", "done"]
BookType = Literal["book", "article", "video", "essay"]


class BookIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    title_cn: str = Field(default="", max_length=200)
    book_type: BookType = "book"
    author: str = ""
    note: str = ""
    url: str = Field(default="", max_length=1024)
    status: BookStatus = "todo"
    is_important: bool = False


class BookPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    title_cn: str | None = Field(default=None, max_length=200)
    book_type: BookType | None = None
    author: str | None = None
    note: str | None = None
    url: str | None = Field(default=None, max_length=1024)
    status: BookStatus | None = None
    is_important: bool | None = None


class BookOut(BaseModel):
    id: int
    title: str
    title_cn: str
    book_type: str
    author: str
    note: str
    url: str
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
