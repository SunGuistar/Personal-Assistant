"""阅读 API 集成测试：CRUD、上传 round-trip、删除规则 409（绕过前端直调 API）。"""

from __future__ import annotations

import io


def _make_book(fclient, title="三体", status="reading"):
    response = fclient.post("/api/books", json={"title": title, "author": "刘慈欣", "status": status})
    assert response.status_code == 201
    return response.json()


def _upload(fclient, book_id, name="note.pdf", data=b"%PDF-fake-content"):
    return fclient.post(
        f"/api/books/{book_id}/notes",
        files={"file": (name, io.BytesIO(data), "application/octet-stream")},
    )


# ---------- 书籍 ----------

def test_books_crud_and_filter(fclient):
    book = _make_book(fclient)
    assert book["note_count"] == 0

    listed = fclient.get("/api/books?status=reading").json()
    assert [b["id"] for b in listed] == [book["id"]]
    assert fclient.get("/api/books?status=todo").json() == []

    patched = fclient.patch(f"/api/books/{book['id']}", json={"status": "done", "note": "已读完"})
    assert patched.json()["status"] == "done"

    assert fclient.get(f"/api/books/{book['id']}").status_code == 200
    assert fclient.delete(f"/api/books/{book['id']}").status_code == 204
    assert fclient.get(f"/api/books/{book['id']}").status_code == 404


def test_books_400_404_422(fclient):
    assert fclient.get("/api/books/9999").status_code == 404
    assert fclient.patch("/api/books/9999", json={"title": "x"}).status_code == 404
    assert fclient.post("/api/books", json={"title": ""}).status_code == 422
    bad_status = fclient.post("/api/books", json={"title": "x", "status": "sleeping"})
    assert bad_status.status_code == 422  # Literal 校验


# ---------- 笔记上传 / 预览 / 删除 ----------

def test_note_upload_list_download_roundtrip(fclient):
    book = _make_book(fclient)
    uploaded = _upload(fclient, book["id"])
    assert uploaded.status_code == 201
    note = uploaded.json()
    assert note["filename"] == "note.pdf"

    notes = fclient.get(f"/api/books/{book['id']}/notes").json()
    assert [n["id"] for n in notes] == [note["id"]]
    assert notes[0]["size"] == len(b"%PDF-fake-content")

    downloaded = fclient.get(f"/api/notes/{note['id']}/file")
    assert downloaded.status_code == 200
    assert downloaded.content == b"%PDF-fake-content"
    assert downloaded.headers["content-type"].startswith("application/pdf")

    assert fclient.delete(f"/api/books/{book['id']}/notes/{note['id']}").status_code == 204
    assert fclient.get(f"/api/books/{book['id']}/notes").json() == []
    assert fclient.get(f"/api/notes/{note['id']}/file").status_code == 404


def test_note_upload_validation(fclient):
    book = _make_book(fclient)
    bad_ext = _upload(fclient, book["id"], name="virus.exe", data=b"MZ")
    assert bad_ext.status_code == 400
    assert bad_ext.json()["detail"]["code"] == "invalid_file_type"

    traversal = _upload(fclient, book["id"], name="../../etc/passwd.pdf")
    assert traversal.status_code == 400

    assert fclient.get(f"/api/books/{book['id']}/notes").json() == []


def test_note_wrong_book_404(fclient):
    book_a = _make_book(fclient, title="A")
    book_b = _make_book(fclient, title="B")
    note = _upload(fclient, book_a["id"]).json()
    assert fclient.delete(f"/api/books/{book_b['id']}/notes/{note['id']}").status_code == 404


# ---------- 删除规则：绕过前端直接调 API ----------

def test_api_rejects_book_delete_with_notes(fclient):
    """无笔记可删；有笔记 409 book_has_notes；删光笔记后可删；拒绝后数据不变。"""

    book = _make_book(fclient)
    assert fclient.delete(f"/api/books/{book['id']}").status_code == 204

    book2 = _make_book(fclient, title="带笔记的书")
    _upload(fclient, book2["id"], name="one.pdf")
    _upload(fclient, book2["id"], name="two.png", data=b"\x89PNG\r\n\x1a\nfake")

    rejected = fclient.delete(f"/api/books/{book2['id']}")
    assert rejected.status_code == 409
    detail = rejected.json()["detail"]
    assert detail["code"] == "book_has_notes"
    assert "请先删除全部笔记" in detail["message"]

    # 拒绝后：书、笔记、文件都还在
    assert fclient.get(f"/api/books/{book2['id']}").status_code == 200
    notes = fclient.get(f"/api/books/{book2['id']}/notes").json()
    assert len(notes) == 2
    assert fclient.get(f"/api/notes/{notes[0]['id']}/file").status_code == 200

    # 删光笔记后可正常删除
    for note in notes:
        assert fclient.delete(f"/api/books/{book2['id']}/notes/{note['id']}").status_code == 204
    assert fclient.delete(f"/api/books/{book2['id']}").status_code == 204
    assert fclient.get(f"/api/books/{book2['id']}").status_code == 404
