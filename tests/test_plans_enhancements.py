"""本轮需求专项测试（需求一/二/四/六）：

- 重要标记：切换持久化、重要置顶、重要/普通内部手动排序、取消重要回落；
- 长期计划：标记完成进历史（含存量 completed 合理入历史、完成时间未知不伪造）、
  历史删除不级联每日任务；
- 每日任务：历史未完成（逾期）任务可排序且不改日期/状态、完成时间记录、
  取消完成同步离开历史、历史按日期筛选；
- 与 list_daily/list_plans 排序口径一致（后端返回即展示顺序）。
"""

from __future__ import annotations

DATE = "2026-11-03"
PREV = "2026-11-02"


# ---------- 长期计划：重要与排序 ----------

def test_plan_important_toggle_and_persist(fclient):
    normal = fclient.post("/api/plans", json={"title": "普通"}).json()
    important = fclient.post("/api/plans", json={"title": "重要", "is_important": True}).json()
    assert important["is_important"] is True

    listed = fclient.get("/api/plans").json()
    assert [p["id"] for p in listed] == [important["id"], normal["id"]]  # 重要置顶

    # 取消重要 → 回落普通区域（保持相对顺序，重要仍在前）
    fclient.patch(f"/api/plans/{important['id']}", json={"is_important": False})
    listed = fclient.get("/api/plans").json()
    assert all(p["is_important"] is False for p in listed)
    assert {p["id"] for p in listed} == {important["id"], normal["id"]}

    # 重新标记重要并刷新查询（持久化）
    fclient.patch(f"/api/plans/{normal['id']}", json={"is_important": True})
    listed = fclient.get("/api/plans").json()
    assert listed[0]["id"] == normal["id"] and listed[0]["is_important"] is True


def test_plan_reorder_within_groups(fclient):
    a = fclient.post("/api/plans", json={"title": "a"}).json()
    b = fclient.post("/api/plans", json={"title": "b", "is_important": True}).json()
    c = fclient.post("/api/plans", json={"title": "c", "is_important": True}).json()
    d = fclient.post("/api/plans", json={"title": "d"}).json()

    # 展示顺序：重要(b,c) 在前，普通(a,d) 在后；普通内部倒序
    result = fclient.put("/api/plans/reorder", json={"ordered_ids": [b["id"], c["id"], d["id"], a["id"]]})
    assert result.status_code == 200
    assert [p["id"] for p in result.json()] == [b["id"], c["id"], d["id"], a["id"]]

    # 重要内部排序：c 上移为 [c, b]
    result = fclient.put("/api/plans/reorder", json={"ordered_ids": [c["id"], b["id"], d["id"], a["id"]]})
    assert [p["id"] for p in result.json()] == [c["id"], b["id"], d["id"], a["id"]]

    # 列表外 id → 409
    conflict = fclient.put("/api/plans/reorder", json={"ordered_ids": [c["id"], b["id"], d["id"], 9999]})
    assert conflict.status_code == 409


# ---------- 长期计划：历史 ----------

def test_plan_history_ordering_and_unknown_time(fclient):
    """存量完成时间未知（completed_at=NULL）排最后，不伪造时间。"""
    # 直接构造迁移前存量数据：status=completed 且 completed_at=NULL
    with fclient.app.state.session_factory() as session:
        from app.models import LongTermPlan

        session.add(LongTermPlan(title="存量", description="", status="completed", sort_order=1))
        session.commit()
    legacy = fclient.get("/api/plans/history").json()[0]
    assert legacy["completed_at"] is None  # 未知不伪造，前端显示"完成时间未知"

    new = fclient.post("/api/plans", json={"title": "新完成"}).json()
    fclient.post(f"/api/plans/{new['id']}/complete")
    history = fclient.get("/api/plans/history").json()
    assert [p["id"] for p in history] == [new["id"], legacy["id"]]  # 完成时间倒序，未知在最后


def test_delete_history_plan_keeps_tasks(fclient):
    """删除历史长期计划：关联每日任务保留、仅解除关联（需求二.4.3）。"""
    plan = fclient.post("/api/plans", json={"title": "P"}).json()
    task = fclient.post("/api/tasks", json={"task_date": DATE, "title": "t", "plan_id": plan["id"]}).json()
    fclient.post(f"/api/plans/{plan['id']}/complete")

    assert fclient.delete(f"/api/plans/{plan['id']}").status_code == 204
    kept = fclient.get(f"/api/tasks/{task['id']}").json()
    assert kept["plan_id"] is None  # 任务保留，仅解除关联
    assert fclient.get("/api/plans/history").json() == []


# ---------- 每日任务：重要与逾期排序 ----------

def test_task_important_pinned_and_toggle(fclient):
    a = fclient.post("/api/tasks", json={"task_date": DATE, "title": "a"}).json()
    b = fclient.post("/api/tasks", json={"task_date": DATE, "title": "b"}).json()
    fclient.patch(f"/api/tasks/{a['id']}", json={"is_important": True})
    daily = fclient.get(f"/api/tasks/daily?date={DATE}").json()
    assert [t["id"] for t in daily] == [a["id"], b["id"]]  # 重要置顶

    fclient.patch(f"/api/tasks/{a['id']}", json={"is_important": False})
    daily = fclient.get(f"/api/tasks/daily?date={DATE}").json()
    assert {t["id"] for t in daily} == {a["id"], b["id"]}
    assert all(t["is_important"] is False for t in daily)  # 回落普通区域


def test_overdue_tasks_reorderable_without_side_effects(fclient):
    """需求四：历史未完成任务可上下调整，且不改日期/状态。"""
    o1 = fclient.post("/api/tasks", json={"task_date": PREV, "title": "o1"}).json()
    o2 = fclient.post("/api/tasks", json={"task_date": PREV, "title": "o2"}).json()
    today = fclient.post("/api/tasks", json={"task_date": DATE, "title": "today"}).json()

    # 逾期分区重排（scope=overdue）
    result = fclient.put(
        "/api/tasks/reorder",
        json={"date": DATE, "scope": "overdue", "ordered_ids": [o2["id"], o1["id"]]},
    )
    assert result.status_code == 200
    overdue = [t for t in result.json() if t["task_date"] < DATE]
    assert [t["id"] for t in overdue] == [o2["id"], o1["id"]]

    # 只改顺序：日期、完成状态、标题不变
    for tid, orig in [(o1["id"], o1), (o2["id"], o2)]:
        row = fclient.get(f"/api/tasks/{tid}").json()
        assert row["task_date"] == PREV and row["done"] is False and row["title"] == orig["title"]

    # 逾期 id 不能混入 today 排序（409）
    conflict = fclient.put(
        "/api/tasks/reorder",
        json={"date": DATE, "scope": "today", "ordered_ids": [today["id"], o1["id"]]},
    )
    assert conflict.status_code == 409


def test_overdue_important_still_pinned(fclient):
    o_important = fclient.post("/api/tasks", json={"task_date": PREV, "title": "oi", "is_important": True}).json()
    fclient.post("/api/tasks", json={"task_date": DATE, "title": "t1"})
    fclient.post("/api/tasks", json={"task_date": DATE, "title": "t2"})
    daily = fclient.get(f"/api/tasks/daily?date={DATE}").json()
    assert daily[0]["id"] == o_important["id"]  # 重要任务（含逾期）整体置顶


# ---------- 每日任务：历史 ----------

def test_task_history_records_and_un_done(fclient):
    """需求六：完成记录完成时间、进历史；取消完成同步离开历史。"""
    t = fclient.post("/api/tasks", json={"task_date": DATE, "title": "t"}).json()
    fclient.patch(f"/api/tasks/{t['id']}", json={"done": True})
    row = fclient.get(f"/api/tasks/{t['id']}").json()
    assert row["completed_at"]  # 记录完成时间

    history = fclient.get("/api/tasks/history").json()
    assert [h["id"] for h in history] == [t["id"]]

    # 未完成的过去日期任务不进入已完成历史
    unfinished = fclient.post("/api/tasks", json={"task_date": PREV, "title": "u"}).json()
    assert fclient.get("/api/tasks/history").json()[0]["id"] == t["id"]
    assert all(h["id"] != unfinished["id"] for h in fclient.get("/api/tasks/history").json())

    # 按日期筛选
    assert fclient.get(f"/api/tasks/history?date={DATE}").json()[0]["id"] == t["id"]
    assert fclient.get(f"/api/tasks/history?date={PREV}").json() == []

    # 取消完成：离开历史、回到当日视图
    fclient.patch(f"/api/tasks/{t['id']}", json={"done": False})
    assert fclient.get("/api/tasks/history").json() == []
    row = fclient.get(f"/api/tasks/{t['id']}").json()
    assert row["completed_at"] is None
    daily = fclient.get(f"/api/tasks/daily?date={DATE}").json()
    assert any(x["id"] == t["id"] and x["done"] is False for x in daily)


def test_task_history_ordering_completed_at_desc(fclient):
    t1 = fclient.post("/api/tasks", json={"task_date": DATE, "title": "1"}).json()
    t2 = fclient.post("/api/tasks", json={"task_date": DATE, "title": "2"}).json()
    fclient.patch(f"/api/tasks/{t1['id']}", json={"done": True})
    fclient.patch(f"/api/tasks/{t2['id']}", json={"done": True})
    history = fclient.get("/api/tasks/history").json()
    assert [h["id"] for h in history] == [t2["id"], t1["id"]]  # 最近完成在前
