"""随手备忘（SQLite 多条记录）、旧 memo.md 幂等迁移、与每日任务双向转换测试。

数据安全：memo 迁移测试一律使用 PH_USER_ENV_DIR 指向的临时目录，不触碰真实
~/.personal-hub/memo.md；不提交任何备忘内容到 Git。
"""

from __future__ import annotations

DATE = "2026-11-05"


# ---------- 随手备忘 CRUD 与排序 ----------

def test_memos_crud_and_persist(fclient):
    created = fclient.post("/api/memos", json={"title": "搁置的想法", "content": "多行\n内容"}).json()
    assert created["sort_order"] == 1
    assert created["task_type"] == "daily"  # 默认类型
    listed = fclient.get("/api/memos").json()
    assert [m["id"] for m in listed] == [created["id"]]

    updated = fclient.patch(f"/api/memos/{created['id']}", json={"title": "新标题"}).json()
    assert updated["title"] == "新标题" and updated["content"] == "多行\n内容"
    assert fclient.get("/api/memos").json()[0]["title"] == "新标题"  # 持久化

    assert fclient.delete(f"/api/memos/{created['id']}").status_code == 204
    assert fclient.get("/api/memos").json() == []
    assert fclient.patch("/api/memos/9999", json={"title": "x"}).status_code == 404


def test_memos_task_type_create_update(fclient):
    """随手备忘任务类型：新增可选（默认 daily）、新增后可修改、展示返回。"""
    created = fclient.post(
        "/api/memos", json={"title": "新想法", "task_type": "idea"}
    ).json()
    assert created["task_type"] == "idea"

    updated = fclient.patch(f"/api/memos/{created['id']}", json={"task_type": "feature_optimize"}).json()
    assert updated["task_type"] == "feature_optimize"
    assert fclient.get("/api/memos").json()[0]["task_type"] == "feature_optimize"

    # 非法类型：422（Literal 校验）/ Service 直调 400
    bad = fclient.post("/api/memos", json={"title": "x", "task_type": "nope"})
    assert bad.status_code == 422

    from app.services import memos_service

    session = fclient.app.state.session_factory()
    try:
        import pytest

        with pytest.raises(Exception):
            memos_service.create_memo(session, title="y", task_type="nope")
    finally:
        session.close()


def test_memos_reorder(fclient):
    a = fclient.post("/api/memos", json={"title": "a"}).json()
    b = fclient.post("/api/memos", json={"title": "b"}).json()
    result = fclient.put("/api/memos/reorder", json={"ordered_ids": [b["id"], a["id"]]})
    assert result.status_code == 200
    assert [m["id"] for m in result.json()] == [b["id"], a["id"]]

    conflict = fclient.put("/api/memos/reorder", json={"ordered_ids": [b["id"], 9999]})
    assert conflict.status_code == 409


# ---------- 旧 memo.md 迁移（幂等） ----------

def test_legacy_memo_file_migration_idempotent(fclient, tmp_path, monkeypatch):
    """旧文件内容完整导入为一条备忘；重复启动不重复导入；原文件保留。"""
    memo_file = tmp_path / "memo.md"
    legacy = "# 旧想法\n- 待办一\n- 待办二"
    memo_file.write_bytes(legacy.encode("utf-8"))  # 二进制写入，避免 Windows 换行转换
    monkeypatch.setenv("PH_USER_ENV_DIR", str(tmp_path))

    with fclient.app.state.session_factory() as session:
        from app.services import memo_service

        assert memo_service.migrate_legacy_memo(session) is True
        # 幂等：第二次运行不生成重复记录
        assert memo_service.migrate_legacy_memo(session) is False

    memos = fclient.get("/api/memos").json()
    assert len(memos) == 1
    assert memos[0]["content"] == legacy  # 内容完整
    assert memo_file.exists()  # 原文件保留

    # 启动钩子幂等：在同一应用上再触发一次 startup，也不重复导入
    from fastapi.testclient import TestClient

    with TestClient(fclient.app) as _:
        pass
    memos = fclient.get("/api/memos").json()
    assert len(memos) == 1


def test_legacy_memo_empty_file_noop(fclient, tmp_path, monkeypatch):
    (tmp_path / "memo.md").write_text("", encoding="utf-8")
    monkeypatch.setenv("PH_USER_ENV_DIR", str(tmp_path))
    with fclient.app.state.session_factory() as session:
        from app.services import memo_service

        assert memo_service.migrate_legacy_memo(session) is False
    assert fclient.get("/api/memos").json() == []


# ---------- 双向转换 ----------

def test_memo_to_task_one_click_defaults(fclient):
    """一键转换：不要求选择时间/类型；默认今天、未保存类型回退 daily。"""
    memo = fclient.post("/api/memos", json={"title": "写报告", "content": "要点 A\n要点 B"}).json()
    task = fclient.post(f"/api/memos/{memo['id']}/to_task").json()
    assert task["title"] == "写报告"
    assert task["content"] == "要点 A\n要点 B"  # 内容不丢失
    assert task["task_type"] == "daily"  # 默认规则

    from datetime import date

    assert task["task_date"] == date.today().isoformat()
    assert fclient.get("/api/memos").json() == []  # 原备忘移除（移动非复制）

    # 重复转换 → 404（源已不存在，天然防重复点击）
    again = fclient.post(f"/api/memos/{memo['id']}/to_task")
    assert again.status_code == 404


def test_task_type_preserved_in_memo_roundtrip(fclient):
    """每日任务 → 备忘 → 每日任务：计划类型双向保留，不丢失。"""
    task = fclient.post(
        "/api/tasks", json={"task_date": DATE, "title": "优化入口", "task_type": "feature_optimize"}
    ).json()
    memo = fclient.post(f"/api/tasks/{task['id']}/to_memo").json()
    assert memo["task_type"] == "feature_optimize"  # 内部保存（前端不展示）

    restored = fclient.post(f"/api/memos/{memo['id']}/to_task").json()
    assert restored["task_type"] == "feature_optimize"  # 转回时恢复
    assert restored["title"] == "优化入口"
    assert fclient.get("/api/memos").json() == []


def test_task_to_memo_moves_with_content(fclient):
    task = fclient.post(
        "/api/tasks", json={"task_date": DATE, "title": "暂缓任务", "content": "说明文字", "task_type": "idea"}
    ).json()
    memo = fclient.post(f"/api/tasks/{task['id']}/to_memo").json()
    assert memo["title"] == "暂缓任务"
    assert memo["content"] == "说明文字"
    assert memo["task_type"] == "idea"  # 计划类型内部保存（展示层不显示）

    assert fclient.get(f"/api/tasks/{task['id']}").status_code == 404  # 原任务移除
    assert any(m["id"] == memo["id"] for m in fclient.get("/api/memos").json())


def test_done_task_cannot_convert_to_memo(fclient):
    task = fclient.post("/api/tasks", json={"task_date": DATE, "title": "已完成"}).json()
    fclient.patch(f"/api/tasks/{task['id']}", json={"done": True})
    conflict = fclient.post(f"/api/tasks/{task['id']}/to_memo")
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "task_done_not_convertible"
    # 任务与历史均不受影响
    assert fclient.get(f"/api/tasks/{task['id']}").json()["done"] is True
    assert fclient.get("/api/memos").json() == []


def test_conversion_failure_rolls_back(fclient, monkeypatch):
    """转换中任一步失败 → 事务回滚：源记录保留、不产生目标任务。"""

    class _Boom(Exception):
        pass

    import sqlalchemy.orm as orm

    monkeypatch.setattr(orm.Session, "delete", lambda *a, **k: (_ for _ in ()).throw(_Boom("boom")))

    from app.services import memos_service

    memo = fclient.post("/api/memos", json={"title": "回滚验证", "content": "x"}).json()
    session = fclient.app.state.session_factory()
    try:
        memos_service.memo_to_task(session, memo["id"], task_date=DATE)
        raised = False
    except _Boom:
        raised = True
    finally:
        session.close()
    monkeypatch.undo()
    assert raised

    # 源备忘保留、未生成任务
    assert any(m["id"] == memo["id"] for m in fclient.get("/api/memos").json())
    assert fclient.get(f"/api/tasks/daily?date={DATE}").json() == []
