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
    assert downloaded.headers["content-disposition"].startswith("inline")

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


def test_book_important_pinned_and_persist(fclient):
    """需求十：重要书籍置顶（筛选内）、切换持久化，不影响既有删除规则。"""
    normal = fclient.post("/api/books", json={"title": "普通书"}).json()
    important = fclient.post(
        "/api/books", json={"title": "重要书", "status": "reading", "is_important": True}
    ).json()
    assert important["is_important"] is True

    listed = fclient.get("/api/books").json()
    assert [b["id"] for b in listed] == [important["id"], normal["id"]]  # 重要置顶

    # 状态筛选内同样置顶
    reading = fclient.get("/api/books?status=reading").json()
    assert [b["id"] for b in reading] == [important["id"]]

    # 取消重要 → 回落默认顺序
    fclient.patch(f"/api/books/{important['id']}", json={"is_important": False})
    listed = fclient.get("/api/books").json()
    assert [b["id"] for b in listed] == [normal["id"], important["id"]]

    # 重新标记（持久化）
    fclient.patch(f"/api/books/{normal['id']}", json={"is_important": True})
    assert fclient.get("/api/books").json()[0]["id"] == normal["id"]


# ---------- Markdown 笔记：导入 + 在线编写 ----------

def test_md_upload_roundtrip(fclient):
    book = _make_book(fclient)
    data = "# 第一章\n\n- 要点一\n- 要点二\n".encode("utf-8")
    uploaded = _upload(fclient, book["id"], name="章节笔记.md", data=data)
    assert uploaded.status_code == 201
    note = uploaded.json()
    assert note["filename"] == "章节笔记.md"
    assert note["size"] == len(data)

    downloaded = fclient.get(f"/api/notes/{note['id']}/file")
    assert downloaded.status_code == 200
    assert downloaded.content == data
    assert downloaded.headers["content-type"].startswith("text/markdown")


def test_md_upload_rejects_non_utf8(fclient):
    book = _make_book(fclient)
    response = _upload(fclient, book["id"], name="bad.md", data=b"\xff\xfe\x00binary")
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_text_content"
    assert fclient.get(f"/api/books/{book['id']}/notes").json() == []


def test_create_md_note_online(fclient):
    book = _make_book(fclient)
    created = fclient.post(
        f"/api/books/{book['id']}/notes/md",
        json={"filename": " 随手记 ", "content": "# 感想\n\n写在线笔记。\n"},
    )
    assert created.status_code == 201
    note = created.json()
    assert note["filename"] == "随手记.md"  # 无扩展名自动补 .md

    downloaded = fclient.get(f"/api/notes/{note['id']}/file")
    assert downloaded.status_code == 200
    assert downloaded.content == "# 感想\n\n写在线笔记。\n".encode("utf-8")

    # 默认文件名 + 同名再建时自动去重
    again = fclient.post(f"/api/books/{book['id']}/notes/md", json={"content": "再写一条"})
    assert again.status_code == 201
    assert again.json()["filename"] != note["filename"]


def test_create_md_note_validation(fclient):
    book = _make_book(fclient)
    assert fclient.post(f"/api/books/{book['id']}/notes/md", json={"content": ""}).status_code == 422
    assert fclient.post(f"/api/books/9999/notes/md", json={"content": "x"}).status_code == 404

    traversal = fclient.post(
        f"/api/books/{book['id']}/notes/md",
        json={"filename": "../../evil.md", "content": "x"},
    )
    assert traversal.status_code == 400
    assert fclient.get(f"/api/books/{book['id']}/notes").json() == []
def test_note_file_download_mode(fclient):
    """默认 inline 预览；download=1 时 attachment 且带原始文件名；两种模式内容一致。"""
    book = _make_book(fclient)
    uploaded = _upload(fclient, book["id"], name="报告.pdf")
    note_id = uploaded.json()["id"]

    inline = fclient.get(f"/api/notes/{note_id}/file")
    assert inline.status_code == 200
    assert inline.headers["content-disposition"].startswith("inline")

    attachment = fclient.get(f"/api/notes/{note_id}/file?download=1")
    assert attachment.status_code == 200
    disposition = attachment.headers["content-disposition"]
    assert disposition.startswith("attachment")
    from urllib.parse import unquote

    assert "filename" in disposition
    assert unquote(disposition).endswith("报告.pdf")  # RFC 5987 编码的中文文件名
    assert attachment.content == inline.content
