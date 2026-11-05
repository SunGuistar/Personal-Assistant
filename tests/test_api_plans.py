"""计划/任务 API 集成测试（TestClient + 隔离库）。"""

from __future__ import annotations

DATE = "2026-11-03"


def test_plans_crud_roundtrip(fclient):
    created = fclient.post(
        "/api/plans", json={"title": "学 LangGraph", "target_date": "2026-12-31"}
    )
    assert created.status_code == 201
    plan = created.json()
    assert plan["status"] == "in_progress"

    plan_id = plan["id"]
    assert fclient.get(f"/api/plans/{plan_id}").status_code == 200
    patched = fclient.patch(f"/api/plans/{plan_id}", json={"status": "completed"})
    assert patched.json()["status"] == "completed"
    assert patched.json()["completed_at"]  # PATCH 置完成同样补记完成时间

    # 已完成计划离开当前列表，进入历史视图（不再从列表删除数据）
    listed = fclient.get("/api/plans").json()
    assert all(item["id"] != plan_id for item in listed)
    history = fclient.get("/api/plans/history").json()
    assert any(item["id"] == plan_id for item in history)

    assert fclient.delete(f"/api/plans/{plan_id}").status_code == 204
    assert fclient.get(f"/api/plans/{plan_id}").status_code == 404
    assert fclient.get("/api/plans/history").json() == []


def test_plan_complete_flow(fclient):
    """标记完成：记录完成时间、离开当前列表、进入历史（需求二）。"""
    plan = fclient.post("/api/plans", json={"title": "完成我"}).json()
    completed = fclient.post(f"/api/plans/{plan['id']}/complete").json()
    assert completed["status"] == "completed"
    assert completed["completed_at"]

    assert all(item["id"] != plan["id"] for item in fclient.get("/api/plans").json())
    history = fclient.get("/api/plans/history").json()
    assert [item["id"] for item in history] == [plan["id"]]
    # 历史保留原有信息与重要状态
    assert history[0]["title"] == "完成我"
    assert history[0]["created_at"]

    assert fclient.post("/api/plans/9999/complete").status_code == 404


def test_tasks_unfinished_carry_over(fclient):
    """未完成任务在后续日期持续显示；已完成任务不在之后日期显示（PRD §2.3）。"""

    prev = "2026-11-02"
    unfinished = fclient.post("/api/tasks", json={"task_date": prev, "title": "未完成"}).json()
    finished = fclient.post("/api/tasks", json={"task_date": prev, "title": "已完成"}).json()
    fclient.patch(f"/api/tasks/{finished['id']}", json={"done": True})

    daily = fclient.get(f"/api/tasks/daily?date={DATE}").json()
    assert [t["id"] for t in daily] == [unfinished["id"]]

    # 完成逾期任务后，当天视图不再显示
    fclient.patch(f"/api/tasks/{unfinished['id']}", json={"done": True})
    assert fclient.get(f"/api/tasks/daily?date={DATE}").json() == []
    # 历史日期仍显示当日任务（含已完成）
    assert len(fclient.get(f"/api/tasks/daily?date={prev}").json()) == 2


def test_plan_404_and_422(fclient):
    assert fclient.get("/api/plans/9999").status_code == 404
    assert fclient.patch("/api/plans/9999", json={"title": "x"}).status_code == 404
    assert fclient.post("/api/plans", json={"title": ""}).status_code == 422
    assert fclient.post("/api/plans", json={"title": "x", "target_date": "2026-13-01"}).status_code == 422


def test_plan_and_task_fully_independent(fclient):
    """需求三：长期计划与每日任务无任何关联；删除计划不影响任务。"""
    plan = fclient.post("/api/plans", json={"title": "P"}).json()
    task = fclient.post("/api/tasks", json={"task_date": DATE, "title": "t"}).json()
    # 关联参数已不再存在于 Schema（旧入参被忽略），响应不再返回 plan_id
    assert "plan_id" not in task
    assert fclient.delete(f"/api/plans/{plan['id']}").status_code == 204
    daily = fclient.get(f"/api/tasks/daily?date={DATE}").json()
    assert len(daily) == 1 and daily[0]["id"] == task["id"]


def test_plan_goal_crud(fclient):
    """需求八：具体目标新增、编辑、清空与持久化。"""
    plan = fclient.post("/api/plans", json={"title": "英语", "goal": "每天阅读 20 分钟"}).json()
    assert plan["goal"] == "每天阅读 20 分钟"
    assert plan["target_date"] is None  # 未设日期为 null，不显示占位

    updated = fclient.patch(f"/api/plans/{plan['id']}", json={"goal": "新目标"}).json()
    assert updated["goal"] == "新目标"
    cleared = fclient.patch(f"/api/plans/{plan['id']}", json={"goal": ""}).json()
    assert cleared["goal"] is None

    # 历史计划同样可查看目标
    fclient.patch(f"/api/plans/{plan['id']}", json={"goal": "历史目标"})
    fclient.post(f"/api/plans/{plan['id']}/complete")
    history = fclient.get("/api/plans/history").json()
    assert history[0]["goal"] == "历史目标"


def test_tasks_daily_crud(fclient):
    t1 = fclient.post("/api/tasks", json={"task_date": DATE, "title": "写文档"}).json()
    t2 = fclient.post("/api/tasks", json={"task_date": DATE, "title": " Review "}).json()
    daily = fclient.get(f"/api/tasks/daily?date={DATE}").json()
    assert [t["id"] for t in daily] == [t1["id"], t2["id"]]

    done = fclient.patch(f"/api/tasks/{t1['id']}", json={"done": True}).json()
    assert done["done"] is True

    assert fclient.delete(f"/api/tasks/{t2['id']}").status_code == 204
    assert fclient.get(f"/api/tasks/daily?date={DATE}").json()[0]["id"] == t1["id"]


def test_tasks_move_via_api(fclient):
    task = fclient.post("/api/tasks", json={"task_date": DATE, "title": "t"}).json()
    moved = fclient.post(f"/api/tasks/{task['id']}/move", json={"target_date": "2026-11-05"}).json()
    assert moved["task_date"] == "2026-11-05"
    assert moved["moved_from_date"] == DATE
    assert fclient.get(f"/api/tasks/daily?date={DATE}").json() == []
    assert len(fclient.get("/api/tasks/daily?date=2026-11-05").json()) == 1


def test_tasks_reorder_and_conflict(fclient):
    a = fclient.post("/api/tasks", json={"task_date": DATE, "title": "a"}).json()
    b = fclient.post("/api/tasks", json={"task_date": DATE, "title": "b"}).json()
    result = fclient.put("/api/tasks/reorder", json={"date": DATE, "ordered_ids": [b["id"], a["id"]]})
    assert result.status_code == 200
    assert [t["id"] for t in result.json()] == [b["id"], a["id"]]

    other = fclient.post("/api/tasks", json={"task_date": "2026-11-09", "title": "x"}).json()
    conflict = fclient.put(
        "/api/tasks/reorder", json={"date": DATE, "ordered_ids": [a["id"], other["id"]]}
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "reorder_mismatch"


def test_tasks_404_422(fclient):
    assert fclient.patch("/api/tasks/9999", json={"done": True}).status_code == 404
    assert fclient.post("/api/tasks", json={"task_date": "bad", "title": "x"}).status_code == 422
    assert (
        fclient.post("/api/tasks/9999/move", json={"target_date": "2026-11-04"}).status_code == 404
    )
