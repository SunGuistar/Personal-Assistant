"""阅读管理业务逻辑（PRD §2.4）：书籍 CRUD、笔记附件上传/下载/删除。

删除规则（用户拍板）：存在关联笔记的书籍**禁止删除**——Service 层在
删除事务内检查 book_notes，存在则抛 BookHasNotes(409)，书籍与文件均不变；
不级联、不自动解除关联、不依赖前端校验。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..exceptions import BookHasNotes, DomainError, NotFoundError
from ..models import Book, BookNote
from ..models.reading import BOOK_STATUS

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = frozenset({".pdf", ".png", ".jpg", ".jpeg", ".md"})
_ILLEGAL_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
BOOK_HAS_NOTES_MESSAGE = "该书籍存在关联笔记，请先删除全部笔记后再删除书籍。"

# 文件头签名：扩展名与实际内容不符时拒绝上传（云记导出为真实文件，误杀风险低）
_FILE_SIGNATURES: dict[str, tuple[bytes, str]] = {
    ".pdf": (b"%PDF-", "PDF"),
    ".png": (b"\x89PNG\r\n\x1a\n", "PNG"),
    ".jpg": (b"\xff\xd8\xff", "JPEG"),
    ".jpeg": (b"\xff\xd8\xff", "JPEG"),
}


def verify_file_signature(filename: str, data: bytes) -> None:
    """校验文件头签名与扩展名一致（防伪造扩展名）。"""

    suffix = Path(filename).suffix.lower()
    if suffix == ".md":
        # Markdown 无文件头签名：要求内容为有效 UTF-8 文本且不含 NUL
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise DomainError(
                "Markdown 笔记必须是有效的 UTF-8 文本",
                code="invalid_text_content",
                status_code=400,
            )
        if "\x00" in text:
            raise DomainError(
                "Markdown 笔记必须是有效的 UTF-8 文本",
                code="invalid_text_content",
                status_code=400,
            )
        return
    signature, kind = _FILE_SIGNATURES[suffix]
    if not data.startswith(signature):
        raise DomainError(
            f"文件内容与扩展名不符：不是有效的 {kind} 文件",
            code="signature_mismatch",
            status_code=400,
        )


def book_to_dict(session: Session, book: Book) -> dict:
    note_count = session.execute(
        select(func.count(BookNote.id)).where(BookNote.book_id == book.id)
    ).scalar_one()
    return {
        "id": book.id,
        "title": book.title,
        "author": book.author,
        "note": book.note,
        "status": book.status,
        "is_important": bool(book.is_important),
        "note_count": int(note_count),
        "created_at": book.created_at,
        "updated_at": book.updated_at,
    }


def note_to_dict(note: BookNote) -> dict:
    return {
        "id": note.id,
        "book_id": note.book_id,
        "filename": note.filename,
        "size": note.size,
        "uploaded_at": note.uploaded_at,
    }


def list_books(session: Session, status: str | None = None) -> list[dict]:
    # 排序规则（2026-11 优化轮）：重要置顶，组内沿用默认（id）顺序
    statement = select(Book).order_by(Book.is_important.desc(), Book.id)
    if status:
        statement = statement.where(Book.status == status)
    books = session.execute(statement).scalars().all()
    return [book_to_dict(session, book) for book in books]


def get_book(session: Session, book_id: int) -> Book:
    book = session.get(Book, book_id)
    if book is None:
        raise NotFoundError(f"书籍不存在: {book_id}")
    return book


def create_book(
    session: Session, *, title: str, author: str = "", note: str = "", status: str = "todo", is_important: bool = False
) -> dict:
    if status not in BOOK_STATUS:
        raise DomainError(f"非法阅读状态: {status}", code="invalid_status", status_code=400)
    book = Book(title=title, author=author, note=note, status=status, is_important=1 if is_important else 0)
    session.add(book)
    session.commit()
    session.refresh(book)
    return book_to_dict(session, book)


def update_book(session: Session, book_id: int, fields: dict) -> dict:
    book = get_book(session, book_id)
    if "status" in fields and fields["status"] is not None and fields["status"] not in BOOK_STATUS:
        raise DomainError(f"非法阅读状态: {fields['status']}", code="invalid_status", status_code=400)
    for key in ("title", "author", "note", "status"):
        if key in fields and fields[key] is not None:
            setattr(book, key, fields[key])
    if fields.get("is_important") is not None:
        book.is_important = 1 if fields["is_important"] else 0
    session.commit()
    session.refresh(book)
    return book_to_dict(session, book)


def delete_book(session: Session, book_id: int) -> None:
    """有笔记禁止删除（409 book_has_notes）；无笔记正常删除。"""

    book = get_book(session, book_id)
    note_count = session.execute(
        select(func.count(BookNote.id)).where(BookNote.book_id == book_id)
    ).scalar_one()
    if int(note_count) > 0:
        raise BookHasNotes()
    session.execute(sql_delete(Book).where(Book.id == book_id))
    session.commit()


def list_notes(session: Session, book_id: int) -> list[dict]:
    get_book(session, book_id)
    notes = session.execute(
        select(BookNote).where(BookNote.book_id == book_id).order_by(BookNote.id)
    ).scalars().all()
    return [note_to_dict(note) for note in notes]


def sanitize_filename(filename: str) -> str:
    """清洗上传文件名：含目录分隔符/绝对路径/全点名的直接拒绝（防路径穿越）。"""

    if "/" in filename or "\\" in filename:
        raise DomainError("文件名不允许包含路径", code="invalid_filename", status_code=400)
    name = _ILLEGAL_FILENAME_CHARS.sub("_", filename).strip()
    if not name or set(name) <= {"."}:
        raise DomainError("文件名不合法", code="invalid_filename", status_code=400)
    return name


def _unique_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    for index in range(2, 1000):
        candidate = directory / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
    raise DomainError("无法生成不重复的文件名", code="filename_conflict", status_code=409)


def _write_and_record(
    session: Session, *, book_id: int, notes_dir: Path, book_dir: Path, safe_name: str, data: bytes
) -> dict:
    """写文件并落库；写库失败时回滚并清理已写文件，不留半截数据。"""

    target = _unique_path(book_dir, safe_name)
    try:
        target.write_bytes(data)
    except OSError as exc:
        raise DomainError(f"文件写入失败: {exc}", code="file_write_failed", status_code=500)

    try:
        note = BookNote(
            book_id=book_id,
            filename=target.name,
            path=str(target.relative_to(notes_dir)),
            size=len(data),
        )
        session.add(note)
        session.commit()
        session.refresh(note)
    except Exception:
        target.unlink(missing_ok=True)
        session.rollback()
        raise
    return note_to_dict(note)


def save_note(
    session: Session,
    *,
    book_id: int,
    filename: str,
    data: bytes,
    notes_dir: Path,
    max_bytes: int,
) -> dict:
    """校验并保存笔记附件；返回笔记记录。任何一步失败都不留半截文件。"""

    get_book(session, book_id)
    safe_name = sanitize_filename(filename)
    if Path(safe_name).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise DomainError(
            f"不支持的文件类型: {Path(safe_name).suffix or '(无扩展名)'}，仅支持 pdf/png/jpg/jpeg/md",
            code="invalid_file_type",
            status_code=400,
        )
    if len(data) > max_bytes:
        raise DomainError(
            f"文件超过大小限制（{max_bytes // (1024 * 1024)}MB）",
            code="file_too_large",
            status_code=400,
        )
    verify_file_signature(safe_name, data)

    book_dir = notes_dir / str(book_id)
    book_dir.mkdir(parents=True, exist_ok=True)
    return _write_and_record(
        session, book_id=book_id, notes_dir=notes_dir, book_dir=book_dir, safe_name=safe_name, data=data
    )


def create_text_note(
    session: Session,
    *,
    book_id: int,
    content: str,
    filename: str | None,
    notes_dir: Path,
    max_bytes: int,
) -> dict:
    """在线编写 Markdown 笔记：内容编码为 UTF-8 后按附件同一套规则落盘。"""

    get_book(session, book_id)
    data = content.encode("utf-8")
    if len(data) > max_bytes:
        raise DomainError(
            f"内容超过大小限制（{max_bytes // (1024 * 1024)}MB）",
            code="file_too_large",
            status_code=400,
        )
    raw_name = (filename or "").strip() or "未命名笔记.md"
    if Path(raw_name).suffix.lower() != ".md":
        raw_name = f"{raw_name}.md"
    safe_name = sanitize_filename(raw_name)
    verify_file_signature(safe_name, data)

    book_dir = notes_dir / str(book_id)
    book_dir.mkdir(parents=True, exist_ok=True)
    return _write_and_record(
        session, book_id=book_id, notes_dir=notes_dir, book_dir=book_dir, safe_name=safe_name, data=data
    )


def get_note(session: Session, note_id: int) -> BookNote:
    note = session.get(BookNote, note_id)
    if note is None:
        raise NotFoundError(f"笔记不存在: {note_id}")
    return note


def note_file_path(session: Session, note_id: int, notes_dir: Path) -> Path:
    """按 id 查库取路径（不接受用户传入路径，防穿越）。"""

    note = get_note(session, note_id)
    path = (notes_dir / note.path).resolve()
    if not str(path).startswith(str(notes_dir.resolve())):
        raise DomainError("笔记路径非法", code="invalid_note_path", status_code=400)
    if not path.is_file():
        raise NotFoundError(f"笔记文件缺失: {note.filename}")
    return path


def delete_note(session: Session, note_id: int, notes_dir: Path) -> None:
    note = get_note(session, note_id)
    path = (notes_dir / note.path).resolve()
    if path.is_file():
        try:
            path.unlink()
        except OSError as exc:
            raise DomainError(f"笔记文件删除失败: {exc}", code="file_delete_failed", status_code=500)
    session.execute(sql_delete(BookNote).where(BookNote.id == note_id))
    session.commit()


def note_content_type(filename: str) -> str:
    return {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".md": "text/markdown; charset=utf-8",
    }.get(Path(filename).suffix.lower(), "application/octet-stream")
