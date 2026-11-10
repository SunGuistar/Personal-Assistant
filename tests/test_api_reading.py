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
    """重要全局置顶、切换持久化；非重要区域按 在读 > 未读 > 已读 排序。"""
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

    # 取消重要 → 回落状态排序（在读仍在前）
    fclient.patch(f"/api/books/{important['id']}", json={"is_important": False})
    listed = fclient.get("/api/books").json()
    assert [b["id"] for b in listed] == [important["id"], normal["id"]]

    # 重新标记（持久化）：重要全局置顶，跨状态排在最前
    fclient.patch(f"/api/books/{normal['id']}", json={"is_important": True})
    listed = fclient.get("/api/books").json()
    assert listed[0]["id"] == normal["id"]
    assert listed[1]["id"] == important["id"]


def test_book_status_sort_order(fclient):
    """排序：重要置顶（在读/未读内）→ 正在读 > 未读 > 已读；已读（含重要）始终沉底；组内 id 顺序。"""
    done_important = fclient.post(
        "/api/books", json={"title": "已读重要", "status": "done", "is_important": True}
    ).json()
    todo_a = fclient.post("/api/books", json={"title": "待读A"}).json()
    reading_important = fclient.post(
        "/api/books", json={"title": "在读重要", "status": "reading", "is_important": True}
    ).json()
    reading_b = fclient.post("/api/books", json={"title": "在读B", "status": "reading"}).json()
    todo_important = fclient.post("/api/books", json={"title": "待读重要", "is_important": True}).json()

    listed = fclient.get("/api/books").json()
    assert [b["id"] for b in listed] == [
        reading_important["id"],  # 重要置顶：在读重要先于未读重要
        todo_important["id"],
        reading_b["id"],
        todo_a["id"],
        done_important["id"],  # 已读即使重要也沉底
    ]


def test_book_title_cn_and_book_type(fclient):
    """需求：标题翻译与阅读类型（书籍/文章/视频/随笔）分别保存、可编辑，存量默认书籍。"""
    created = fclient.post(
        "/api/books",
        json={"title": "Deep Work", "title_cn": "深度工作", "book_type": "book", "author": "Cal Newport"},
    ).json()
    assert created["title_cn"] == "深度工作" and created["book_type"] == "book"

    patched = fclient.patch(
        f"/api/books/{created['id']}", json={"title_cn": "深度工作（修订）", "book_type": "article"}
    ).json()
    assert patched["title_cn"] == "深度工作（修订）" and patched["book_type"] == "article"

    # 存量数据（未填写）兼容：默认空翻译 + 书籍类型
    legacy = fclient.post("/api/books", json={"title": "存量书"}).json()
    assert legacy["title_cn"] == "" and legacy["book_type"] == "book"
    listed = {b["id"]: b for b in fclient.get("/api/books").json()}
    assert listed[created["id"]]["title_cn"] == "深度工作（修订）"

    # 非法阅读类型 → 422（Literal 校验）
    bad = fclient.post("/api/books", json={"title": "x", "book_type": "magazine"})
    assert bad.status_code == 422


def test_book_type_filter(fclient):
    """展示页类型筛选：book_type 参数过滤，非法类型 400，与状态筛选可叠加。"""
    book = fclient.post("/api/books", json={"title": "文章A", "book_type": "article"}).json()
    fclient.post("/api/books", json={"title": "视频B", "book_type": "video"}).json()
    fclient.post("/api/books", json={"title": "书籍C"}).json()

    articles = fclient.get("/api/books?book_type=article").json()
    assert [b["id"] for b in articles] == [book["id"]]

    # 与状态筛选叠加
    both = fclient.get("/api/books?book_type=article&status=todo").json()
    assert [b["id"] for b in both] == [book["id"]]
    assert fclient.get("/api/books?book_type=article&status=done").json() == []

    invalid = fclient.get("/api/books?book_type=magazine")
    assert invalid.status_code == 400
    assert invalid.json()["detail"]["code"] == "invalid_book_type"


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


# ---------- 云记 .Jnotes：上传自动转 PDF ----------

import json
import zipfile


def _make_jnotes(strokes=None):
    """构造最小可用的云记文件：ZIP 容器内含 zip.Jzip（一页 seg 笔迹 JSON）。"""
    if strokes is None:
        strokes = [{"c": {"k": [{"x": 100, "y": 100}, {"x": 200, "y": 150}, {"x": 300, "y": 100}], "c": -16777216, "d": 5.0}}]
    payload = b"\x00\x04PAGE\x00\x02DB" + b"seg:1/1" + json.dumps(strokes).encode("utf-8") + b"\x00\xfftrailing-binary"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("zip.Jzip", payload)
    return buf.getvalue()


def test_jnotes_upload_converted_to_pdf(fclient):
    """.Jnotes 上传后落库为同名 .pdf，预览/下载均为有效 PDF 内容。"""
    book = _make_book(fclient)
    uploaded = _upload(fclient, book["id"], name="手写笔记.Jnotes", data=_make_jnotes())
    assert uploaded.status_code == 201, uploaded.text
    note = uploaded.json()
    assert note["filename"] == "手写笔记.pdf"  # 扩展名替换为 .pdf
    assert note["size"] > 0

    downloaded = fclient.get(f"/api/notes/{note['id']}/file")
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"%PDF-")
    assert downloaded.headers["content-type"].startswith("application/pdf")
    assert note["size"] == len(downloaded.content)


def test_jnotes_upload_rejects_corrupt_file(fclient):
    """PK 头但无法解析（无 zip.Jzip / 无 PAGE 记录）→ 400 jnotes_convert_failed，不留半截数据。"""
    book = _make_book(fclient)

    # 合法 ZIP 但缺少 zip.Jzip
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("other.txt", "hello")
    missing = _upload(fclient, book["id"], name="a.jnotes", data=buf.getvalue())
    assert missing.status_code == 400
    assert missing.json()["detail"]["code"] == "jnotes_convert_failed"

    # zip.Jzip 存在但没有 PAGE 记录
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("zip.Jzip", b"\x00\x04NOPE\x00\x02DB seg:1/1 []")
    no_page = _upload(fclient, book["id"], name="b.jnotes", data=buf.getvalue())
    assert no_page.status_code == 400
    assert no_page.json()["detail"]["code"] == "jnotes_convert_failed"

    # 非 ZIP 内容（伪造扩展名）
    fake = _upload(fclient, book["id"], name="c.jnotes", data=b"PK\x03\x04not a real zip")
    assert fake.status_code == 400
    assert fake.json()["detail"]["code"] in ("signature_mismatch", "jnotes_convert_failed")

    assert fclient.get(f"/api/books/{book['id']}/notes").json() == []
