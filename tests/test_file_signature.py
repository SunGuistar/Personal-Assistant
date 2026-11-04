"""上传文件头签名校验（F1，阶段 3 前置修复）。"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from alembic import command
from alembic.config import Config

from app.exceptions import DomainError
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


def _book(session):
    return reading_service.create_book(session, title="书")


def _upload(session, notes_dir, name, data):
    return reading_service.save_note(
        session,
        book_id=_book(session)["id"],
        filename=name,
        data=data,
        notes_dir=notes_dir,
        max_bytes=1024 * 1024,
    )


GOOD_PDF = b"%PDF-1.4 fake body"
GOOD_PNG = b"\x89PNG\r\n\x1a\nfake body"
GOOD_JPG = b"\xff\xd8\xff\xe0 fake body"


@pytest.mark.parametrize(
    "name,data",
    [("a.pdf", GOOD_PDF), ("b.png", GOOD_PNG), ("c.jpg", GOOD_JPG), ("d.jpeg", GOOD_JPG)],
)
def test_valid_signatures_accepted(session, notes_dir, name, data):
    note = _upload(session, notes_dir, name, data)
    assert note["filename"] == name


@pytest.mark.parametrize(
    "name,data",
    [
        ("fake.pdf", GOOD_PNG),      # PNG 内容冒充 PDF
        ("fake.png", GOOD_PDF),      # PDF 内容冒充 PNG
        ("fake.jpg", b"not-an-image"),
        ("empty.pdf", b""),          # 截断/空文件
        ("truncated.png", b"\x89PNG"),  # 签名不完整
    ],
)
def test_signature_mismatch_rejected(session, notes_dir, name, data):
    with pytest.raises(DomainError) as exc_info:
        _upload(session, notes_dir, name, data)
    assert exc_info.value.code == "signature_mismatch"
    assert exc_info.value.status_code == 400


def test_verify_file_signature_unit():
    reading_service.verify_file_signature("x.pdf", GOOD_PDF)
    with pytest.raises(DomainError):
        reading_service.verify_file_signature("x.pdf", GOOD_PNG)
