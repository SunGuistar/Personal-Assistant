"""重要信息（SQLite）与随手备忘（本地 Markdown 文件）测试。

数据安全：memo 测试一律使用 PH_USER_ENV_DIR 指向的临时目录，不触碰真实
~/.personal-hub/memo.md；不提交任何备忘内容到 Git。
"""

from __future__ import annotations

import os


# ---------- 重要信息 ----------

def test_infos_crud_and_persist(fclient):
    created = fclient.post("/api/infos", json={"title": "设计规范", "content": "**简洁优先**"}).json()
    assert created["sort_order"] == 1
    listed = fclient.get("/api/infos").json()
    assert [i["id"] for i in listed] == [created["id"]]

    updated = fclient.patch(f"/api/infos/{created['id']}", json={"title": "新标题"}).json()
    assert updated["title"] == "新标题" and updated["content"] == "**简洁优先**"

    # 持久化：另一个请求仍能看到
    assert fclient.get("/api/infos").json()[0]["title"] == "新标题"

    assert fclient.delete(f"/api/infos/{created['id']}").status_code == 204
    assert fclient.get("/api/infos").json() == []
    assert fclient.patch("/api/infos/9999", json={"title": "x"}).status_code == 404


def test_infos_reorder(fclient):
    a = fclient.post("/api/infos", json={"title": "a"}).json()
    b = fclient.post("/api/infos", json={"title": "b"}).json()
    result = fclient.put("/api/infos/reorder", json={"ordered_ids": [b["id"], a["id"]]})
    assert result.status_code == 200
    assert [i["id"] for i in result.json()] == [b["id"], a["id"]]

    conflict = fclient.put("/api/infos/reorder", json={"ordered_ids": [b["id"], 9999]})
    assert conflict.status_code == 409


# ---------- 随手备忘 ----------

def test_memo_roundtrip_and_missing_file(fclient, tmp_path, monkeypatch):
    """文件不存在按空内容；保存后读取一致（临时用户目录，隔离真实文件）。"""
    monkeypatch.setenv("PH_USER_ENV_DIR", str(tmp_path))
    assert fclient.get("/api/memo").json() == {"content": ""}

    assert fclient.put("/api/memo", json={"content": "# 想法\n- 待研究"}).status_code == 200
    assert fclient.get("/api/memo").json()["content"] == "# 想法\n- 待研究"
    # 确实写入本地文件（UTF-8）
    memo_file = tmp_path / "memo.md"
    assert memo_file.read_text(encoding="utf-8") == "# 想法\n- 待研究"


def test_memo_atomic_replace_and_no_stale_overwrite(fclient, tmp_path, monkeypatch):
    """原子替换：写入中断不残留临时文件；expected 不一致时拒绝旧内容覆盖。"""
    monkeypatch.setenv("PH_USER_ENV_DIR", str(tmp_path))
    assert fclient.put("/api/memo", json={"content": "v1"}).status_code == 200

    # expected 与实际不符 → 409 冲突，旧内容不被覆盖
    conflict = fclient.put("/api/memo", json={"content": "stale", "expected": " outdated"})
    assert conflict.status_code == 409
    assert fclient.get("/api/memo").json()["content"] == "v1"

    # expected 正确 → 写入成功；且无临时文件残留
    assert fclient.put("/api/memo", json={"content": "v2", "expected": "v1"}).status_code == 200
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith("memo.md.tmp")]
    assert leftovers == []
    assert fclient.get("/api/memo").json()["content"] == "v2"


def test_memo_oversize_rejected(fclient, tmp_path, monkeypatch):
    monkeypatch.setenv("PH_USER_ENV_DIR", str(tmp_path))
    response = fclient.put("/api/memo", json={"content": "x" * (512 * 1024 + 1)})
    assert response.status_code == 422  # pydantic max_length 拦截
