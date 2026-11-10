"""阅读管理路由：书籍 CRUD + 笔记附件上传/预览/删除。

删除规则（PRD §2.4，用户拍板）：存在关联笔记的书籍禁止删除，
后端返回 409 `book_has_notes`；不级联、不自动解除关联。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..exceptions import DomainError
from ..schemas.reading import BookIn, BookOut, BookPatch, NoteMdIn, NoteOut
from ..services import reading_service
from .deps import get_session, get_settings

router = APIRouter(prefix="/books", tags=["reading"])


@router.get("", response_model=list[BookOut])
def list_books(
    status: str | None = None,
    book_type: str | None = None,
    session: Session = Depends(get_session),
):
    if status is not None and status not in reading_service.BOOK_STATUS:
        raise DomainError(f"非法阅读状态: {status}", code="invalid_status", status_code=400)
    if book_type is not None and book_type not in reading_service.BOOK_TYPES:
        raise DomainError(f"非法阅读类型: {book_type}", code="invalid_book_type", status_code=400)
    return reading_service.list_books(session, status, book_type)


@router.post("", response_model=BookOut, status_code=201)
def create_book(payload: BookIn, session: Session = Depends(get_session)):
    return reading_service.create_book(session, **payload.model_dump())


@router.get("/{book_id}", response_model=BookOut)
def get_book(book_id: int, session: Session = Depends(get_session)):
    book = reading_service.get_book(session, book_id)
    return reading_service.book_to_dict(session, book)


@router.patch("/{book_id}", response_model=BookOut)
def update_book(book_id: int, payload: BookPatch, session: Session = Depends(get_session)):
    return reading_service.update_book(session, book_id, payload.model_dump(exclude_unset=True))


@router.delete("/{book_id}", status_code=204)
def delete_book(book_id: int, session: Session = Depends(get_session)):
    reading_service.delete_book(session, book_id)


@router.get("/{book_id}/notes", response_model=list[NoteOut])
def list_notes(book_id: int, session: Session = Depends(get_session)):
    return reading_service.list_notes(session, book_id)


@router.post("/{book_id}/notes", response_model=NoteOut, status_code=201)
async def upload_note(
    book_id: int,
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    settings = get_settings(request)
    data = await file.read()
    return reading_service.save_note(
        session,
        book_id=book_id,
        filename=file.filename or "",
        data=data,
        notes_dir=settings.reading_notes_dir,
        max_bytes=settings.upload_max_mb * 1024 * 1024,
    )


@router.post("/{book_id}/notes/md", response_model=NoteOut, status_code=201)
def create_md_note(
    book_id: int,
    payload: NoteMdIn,
    request: Request,
    session: Session = Depends(get_session),
):
    settings = get_settings(request)
    return reading_service.create_text_note(
        session,
        book_id=book_id,
        content=payload.content,
        filename=payload.filename,
        notes_dir=settings.reading_notes_dir,
        max_bytes=settings.upload_max_mb * 1024 * 1024,
    )


@router.delete("/{book_id}/notes/{note_id}", status_code=204)
def delete_note(book_id: int, note_id: int, request: Request, session: Session = Depends(get_session)):
    settings = get_settings(request)
    note = reading_service.get_note(session, note_id)
    if note.book_id != book_id:
        raise reading_service.NotFoundError(f"笔记不存在: {note_id}")
    reading_service.delete_note(session, note_id, settings.reading_notes_dir)


notes_router = APIRouter(prefix="/notes", tags=["reading"])


@notes_router.get("/{note_id}/file")
def note_file(
    note_id: int,
    request: Request,
    download: bool = False,
    session: Session = Depends(get_session),
):
    settings = get_settings(request)
    note = reading_service.get_note(session, note_id)
    path = reading_service.note_file_path(session, note_id, settings.reading_notes_dir)
    return FileResponse(
        path,
        media_type=reading_service.note_content_type(note.filename),
        filename=note.filename,
        content_disposition_type="attachment" if download else "inline",
    )
