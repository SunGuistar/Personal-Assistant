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
    assert plan["progress"] == 0.0

    plan_id = plan["id"]
    assert fclient.get(f"/api/plans/{plan_id}").status_code == 200
    patched = fclient.patch(f"/api/plans/{plan_id}", json={"status": "completed"})
    assert patched.json()["status"] == "completed"

    listed = fclient.get("/api/plans").json()
    assert any(item["id"] == plan_id for item in listed)

    assert fclient.delete(f"/api/plans/{plan_id}").status_code == 204
    assert fclient.get(f"/api/plans/{plan_id}").status_code == 404


def test_plan_progress_via_api(fclient):
    plan = fclient.post("/api/plans", json={"title": "P"}).json()
    t1 = fclient.post("/api/tasks", json={"task_date": DATE, "title": "a", "plan_id": plan["id"]}).json()
    fclient.post("/api/tasks", json={"task_date": DATE, "title": "b", "plan_id": plan["id"]})
    assert fclient.get(f"/api/plans/{plan['id']}").json()["progress"] == 0.0
    fclient.patch(f"/api/tasks/{t1['id']}", json={"done": True})
    assert fclient.get(f"/api/plans/{plan['id']}").json()["progress"] == 0.5


def test_plan_404_and_422(fclient):
    assert fclient.get("/api/plans/9999").status_code == 404
    assert fclient.patch("/api/plans/9999", json={"title": "x"}).status_code == 404
    assert fclient.post("/api/plans", json={"title": ""}).status_code == 422
    assert fclient.post("/api/plans", json={"title": "x", "target_date": "2026-13-01"}).status_code == 422


def test_delete_plan_keeps_tasks(fclient):
    plan = fclient.post("/api/plans", json={"title": "P"}).json()
    fclient.post("/api/tasks", json={"task_date": DATE, "title": "t", "plan_id": plan["id"]})
    fclient.delete(f"/api/plans/{plan['id']}")
    daily = fclient.get(f"/api/tasks/daily?date={DATE}").json()
    assert len(daily) == 1 and daily[0]["plan_id"] is None


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
