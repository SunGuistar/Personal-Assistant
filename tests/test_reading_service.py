"""阅读 service 单元测试：CRUD、删除规则（6 必测）、上传安全（PRD §2.4）。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from alembic import command
from alembic.config import Config

from app.exceptions import BookHasNotes, DomainError, NotFoundError
from app.models import Book, BookNote
from app.services import reading_service


@pytest.fixture()
def session(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'unit.db'}"
    os.environ["PH_DATABASE_URL"] = db_url
    command.upgrade(Config(str(Path(__file__).resolve().parent.parent / "alembic.ini")), "head")
    engine = create_engine(db_url)
    factory = sessionmaker(bind=engine)
    with factory() as s:
        yield s
    engine.dispose()


@pytest.fixture()
def notes_dir(tmp_path):
    directory = tmp_path / "reading_notes"
    directory.mkdir()
    return directory


def _make_book(session, title="书", status="todo"):
    return reading_service.create_book(session, title=title, status=status)


def _add_note(session, book_id, notes_dir, name="n.pdf", data=b"%PDF-fake"):
    return reading_service.save_note(
        session, book_id=book_id, filename=name, data=data,
        notes_dir=notes_dir, max_bytes=1024 * 1024,
    )


# ---------- 书籍 CRUD 与状态 ----------

def test_book_crud_and_status(session):
    book = _make_book(session, status="reading")
    assert book["status"] == "reading"
    updated = reading_service.update_book(session, book["id"], {"status": "done"})
    assert updated["status"] == "done"
    assert reading_service.list_books(session, status="done")[0]["id"] == book["id"]
    assert reading_service.list_books(session, status="todo") == []


def test_book_invalid_status(session):
    with pytest.raises(DomainError):
        _make_book(session, status="reading_now")


def test_book_note_count(session, notes_dir):
    book = _make_book(session)
    assert book["note_count"] == 0
    _add_note(session, book["id"], notes_dir)
    _add_note(session, book["id"], notes_dir, name="m.png", data=b"\x89PNG")
    assert reading_service.list_books(session)[0]["note_count"] == 2


# ---------- 删除规则 6 必测 ----------

def test_delete_book_without_notes_ok(session):
    book = _make_book(session)
    reading_service.delete_book(session, book["id"])
    assert reading_service.list_books(session) == []


def test_delete_book_with_one_note_rejected(session, notes_dir):
    book = _make_book(session)
    _add_note(session, book["id"], notes_dir)
    with pytest.raises(BookHasNotes) as exc_info:
        reading_service.delete_book(session, book["id"])
    assert exc_info.value.code == "book_has_notes"


def test_delete_book_with_multiple_notes_rejected(session, notes_dir):
    book = _make_book(session)
    _add_note(session, book["id"], notes_dir)
    _add_note(session, book["id"], notes_dir, name="a.png", data=b"\x89PNG")
    with pytest.raises(BookHasNotes):
        reading_service.delete_book(session, book["id"])


def test_rejected_delete_leaves_data_and_files_untouched(session, notes_dir):
    book = _make_book(session)
    note = _add_note(session, book["id"], notes_dir)
    with pytest.raises(BookHasNotes):
        reading_service.delete_book(session, book["id"])
    # 书籍记录、笔记记录、笔记文件三者均在
    assert reading_service.get_book(session, book["id"]).title == "书"
    assert reading_service.list_notes(session, book["id"])[0]["id"] == note["id"]
    assert (notes_dir / str(book["id"]) / "n.pdf").exists()


def test_delete_book_after_removing_all_notes(session, notes_dir):
    book = _make_book(session)
    note = _add_note(session, book["id"], notes_dir)
    reading_service.delete_note(session, note["id"], notes_dir)
    reading_service.delete_book(session, book["id"])
    assert reading_service.list_books(session) == []


def test_delete_constraint_holds_without_frontend(session, notes_dir):
    """绕过前端=直接调 service/API 层，约束依然在（等价 6 之 6）。"""

    book = _make_book(session)
    _add_note(session, book["id"], notes_dir)
    with pytest.raises(BookHasNotes):
        reading_service.delete_book(session, book["id"])


# ---------- 上传安全 ----------

@pytest.mark.parametrize(
    "bad_name",
    ["../evil.pdf", "..\\evil.pdf", "/abs/path.png", "a/b/c.pdf", "...", ""],
)
def test_sanitize_filename_rejects_traversal(bad_name):
    with pytest.raises(DomainError):
        reading_service.sanitize_filename(bad_name)


def test_sanitize_filename_strips_illegal_chars():
    assert reading_service.sanitize_filename('a<b>:c|.pdf') == "a_b__c_.pdf"


def test_upload_rejects_bad_extension(session, notes_dir):
    book = _make_book(session)
    with pytest.raises(DomainError) as exc_info:
        reading_service.save_note(
            session, book_id=book["id"], filename="x.exe", data=b"MZ",
            notes_dir=notes_dir, max_bytes=1024,
        )
    assert exc_info.value.code == "invalid_file_type"
    assert reading_service.list_notes(session, book["id"]) == []


def test_upload_rejects_oversize(session, notes_dir):
    book = _make_book(session)
    with pytest.raises(DomainError) as exc_info:
        reading_service.save_note(
            session, book_id=book["id"], filename="big.pdf", data=b"x" * 11,
            notes_dir=notes_dir, max_bytes=10,
        )
    assert exc_info.value.code == "file_too_large"


def test_upload_duplicate_name_gets_unique_file(session, notes_dir):
    book = _make_book(session)
    first = _add_note(session, book["id"], notes_dir, name="same.pdf")
    second = _add_note(session, book["id"], notes_dir, name="same.pdf")
    assert first["filename"] == "same.pdf"
    assert second["filename"] == "same_2.pdf"


def test_note_roundtrip_and_missing_file(session, notes_dir):
    book = _make_book(session)
    note = _add_note(session, book["id"], notes_dir, data=b"hello-bytes")
    path = reading_service.note_file_path(session, note["id"], notes_dir)
    assert path.read_bytes() == b"hello-bytes"
    reading_service.delete_note(session, note["id"], notes_dir)
    with pytest.raises(NotFoundError):
        reading_service.note_file_path(session, note["id"], notes_dir)


def test_note_file_path_rejects_escape(session, notes_dir):
    book = _make_book(session)
    note = _add_note(session, book["id"], notes_dir)
    # 篡改记录的 path 为 ../ 路径，必须被拦截
    row = session.get(BookNote, note["id"])
    row.path = "../outside.pdf"
    session.commit()
    with pytest.raises(DomainError) as exc_info:
        reading_service.note_file_path(session, note["id"], notes_dir)
    assert exc_info.value.code == "invalid_note_path"


def test_delete_note_removes_file_and_record(session, notes_dir):
    book = _make_book(session)
    note = _add_note(session, book["id"], notes_dir)
    reading_service.delete_note(session, note["id"], notes_dir)
    assert reading_service.list_notes(session, book["id"]) == []
    assert not (notes_dir / str(book["id"]) / "n.pdf").exists()
