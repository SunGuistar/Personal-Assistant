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
    """删除历史长期计划不影响每日任务（两模块完全独立）。"""
    plan = fclient.post("/api/plans", json={"title": "P"}).json()
    task = fclient.post("/api/tasks", json={"task_date": DATE, "title": "t"}).json()
    fclient.post(f"/api/plans/{plan['id']}/complete")

    assert fclient.delete(f"/api/plans/{plan['id']}").status_code == 204
    assert fclient.get(f"/api/tasks/{task['id']}").status_code == 200
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


def test_unified_reorder_today_and_overdue_interleaved(fclient):
    """需求二：今日任务与逾期任务统一排序、可自由穿插，且不改日期/状态。"""
    o1 = fclient.post("/api/tasks", json={"task_date": PREV, "title": "o1"}).json()
    o2 = fclient.post("/api/tasks", json={"task_date": PREV, "title": "o2"}).json()
    t1 = fclient.post("/api/tasks", json={"task_date": DATE, "title": "t1"}).json()
    t2 = fclient.post("/api/tasks", json={"task_date": DATE, "title": "t2"}).json()

    # 今日任务插到逾期任务之前：[t1, o1, t2, o2]
    result = fclient.put(
        "/api/tasks/reorder",
        json={"date": DATE, "ordered_ids": [t1["id"], o1["id"], t2["id"], o2["id"]]},
    )
    assert result.status_code == 200
    assert [t["id"] for t in result.json()] == [t1["id"], o1["id"], t2["id"], o2["id"]]

    # 逾期任务插入今日任务之间：[o1, t1, o2, t2]
    result = fclient.put(
        "/api/tasks/reorder",
        json={"date": DATE, "ordered_ids": [o1["id"], t1["id"], o2["id"], t2["id"]]},
    )
    assert [t["id"] for t in result.json()] == [o1["id"], t1["id"], o2["id"], t2["id"]]

    # 只改顺序：日期、完成状态、标题不变
    for tid, orig in [(o1["id"], o1), (o2["id"], o2), (t1["id"], t1)]:
        row = fclient.get(f"/api/tasks/{tid}").json()
        assert row["task_date"] == orig["task_date"] and row["done"] is False and row["title"] == orig["title"]

    # 排序列表缺少可见任务 → 409
    conflict = fclient.put(
        "/api/tasks/reorder", json={"date": DATE, "ordered_ids": [o1["id"], t1["id"]]}
    )
    assert conflict.status_code == 409


def test_unified_reorder_does_not_break_important_priority(fclient):
    """重要任务始终在前；把普通任务排到重要之前的请求被拒绝（409）。"""
    normal = fclient.post("/api/tasks", json={"task_date": DATE, "title": "n"}).json()
    imp = fclient.post("/api/tasks", json={"task_date": DATE, "title": "i", "is_important": True}).json()
    # 展示顺序重要在前
    assert [t["id"] for t in fclient.get(f"/api/tasks/daily?date={DATE}").json()] == [imp["id"], normal["id"]]
    # 尝试把普通任务排到重要之前 → 越界 409（前端在分组边界禁用上移/下移，不会发出此类请求）
    conflict = fclient.put(
        "/api/tasks/reorder", json={"date": DATE, "ordered_ids": [normal["id"], imp["id"]]}
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "reorder_cross_group"


def test_overdue_important_still_pinned(fclient):
    o_important = fclient.post("/api/tasks", json={"task_date": PREV, "title": "oi", "is_important": True}).json()
    fclient.post("/api/tasks", json={"task_date": DATE, "title": "t1"})
    fclient.post("/api/tasks", json={"task_date": DATE, "title": "t2"})
    daily = fclient.get(f"/api/tasks/daily?date={DATE}").json()
    assert daily[0]["id"] == o_important["id"]  # 重要任务（含逾期）整体置顶


# ---------- 每日任务：历史 ----------

def test_task_done_toggle_and_history(fclient):
    """需求二/三：完成可反复切换；取消完成回到未完成区并离开历史。"""
    t = fclient.post("/api/tasks", json={"task_date": DATE, "title": "t"}).json()
    done = fclient.patch(f"/api/tasks/{t['id']}", json={"done": True}).json()
    assert done["done"] is True and done["completed_at"]  # 完成记完成时间
    assert [h["id"] for h in fclient.get("/api/tasks/history").json()] == [t["id"]]

    # 未完成的历史任务（来自更早日期）不进入历史
    unfinished = fclient.post("/api/tasks", json={"task_date": PREV, "title": "u"}).json()
    assert all(h["id"] != unfinished["id"] for h in fclient.get("/api/tasks/history").json())

    # 历史按日期筛选
    assert fclient.get(f"/api/tasks/history?date={DATE}").json()[0]["id"] == t["id"]
    assert fclient.get(f"/api/tasks/history?date={PREV}").json() == []

    # 取消完成：清除完成时间、离开历史、回到当日未完成列表（不再 409）
    undone = fclient.patch(f"/api/tasks/{t['id']}", json={"done": False}).json()
    assert undone["done"] is False and undone["completed_at"] is None
    assert fclient.get("/api/tasks/history").json() == []
    daily = fclient.get(f"/api/tasks/daily?date={DATE}").json()
    assert any(x["id"] == t["id"] and x["done"] is False for x in daily)


def test_done_tasks_sink_to_bottom_even_if_important(fclient):
    """需求三：已完成任务整体置底，重要已完成也不例外。"""
    normal = fclient.post("/api/tasks", json={"task_date": DATE, "title": "n"}).json()
    imp_done = fclient.post("/api/tasks", json={"task_date": DATE, "title": "id", "is_important": True}).json()
    fclient.patch(f"/api/tasks/{imp_done['id']}", json={"done": True})
    daily = fclient.get(f"/api/tasks/daily?date={DATE}").json()
    assert daily[-1]["id"] == imp_done["id"]  # 重要但已完成 → 末尾
    assert daily[0]["id"] == normal["id"]
    assert daily[0]["done"] is False

    # 取消完成后重新参与正常排序（重要回到顶部）
    fclient.patch(f"/api/tasks/{imp_done['id']}", json={"done": False})
    daily = fclient.get(f"/api/tasks/daily?date={DATE}").json()
    assert daily[0]["id"] == imp_done["id"] and daily[0]["done"] is False


def test_task_type_ordering_and_important_priority(fclient):
    """需求四：未完成内 重要 > 类型(日常/功能添加/功能优化/奇思妙想) > 手动。"""
    idea = fclient.post("/api/tasks", json={"task_date": DATE, "title": "奇思", "task_type": "idea"}).json()
    opt = fclient.post("/api/tasks", json={"task_date": DATE, "title": "优化", "task_type": "feature_optimize"}).json()
    add = fclient.post("/api/tasks", json={"task_date": DATE, "title": "添加", "task_type": "feature_add"}).json()
    daily_t = fclient.post("/api/tasks", json={"task_date": DATE, "title": "日常"}).json()
    assert daily_t["task_type"] == "daily"  # 默认类型

    daily = fclient.get(f"/api/tasks/daily?date={DATE}").json()
    assert [t["id"] for t in daily] == [daily_t["id"], add["id"], opt["id"], idea["id"]]

    # 重要置顶优先于类型：重要的"奇思妙想"排到最前
    fclient.patch(f"/api/tasks/{idea['id']}", json={"is_important": True})
    daily = fclient.get(f"/api/tasks/daily?date={DATE}").json()
    assert daily[0]["id"] == idea["id"]

    # 非法类型：Schema 枚举拦截（422）
    bad = fclient.patch(f"/api/tasks/{daily_t['id']}", json={"task_type": "urgent"})
    assert bad.status_code == 422


def test_reorder_within_type_and_cross_group_rejected(fclient):
    """需求四：同类型内部可手动排序，跨类型/重要/完成边界 409。"""
    a = fclient.post("/api/tasks", json={"task_date": DATE, "title": "a"}).json()
    b = fclient.post("/api/tasks", json={"task_date": DATE, "title": "b"}).json()
    c = fclient.post("/api/tasks", json={"task_date": DATE, "title": "c", "task_type": "feature_add"}).json()

    # 同类型内部交换：a↔b（均为日常）
    result = fclient.put("/api/tasks/reorder", json={"date": DATE, "ordered_ids": [b["id"], a["id"], c["id"]]})
    assert result.status_code == 200
    assert [t["id"] for t in result.json()] == [b["id"], a["id"], c["id"]]

    # 跨类型边界（把 feature_add 插到日常之前）→ 409
    conflict = fclient.put("/api/tasks/reorder", json={"date": DATE, "ordered_ids": [c["id"], b["id"], a["id"]]})
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "reorder_cross_group"

    # 修改类型后立即按新类型重排
    fclient.patch(f"/api/tasks/{a['id']}", json={"task_type": "idea"})
    daily = fclient.get(f"/api/tasks/daily?date={DATE}").json()
    assert daily[0]["id"] == b["id"] and daily[-1]["id"] == a["id"]


def test_legacy_task_type_migration_default(fclient):
    """需求四.1.5：历史任务迁移后默认日常（直接构造迁移前形态验证模型默认）。"""
    with fclient.app.state.session_factory() as session:
        from app.models import DailyTask

        session.add(DailyTask(task_date=DATE, title="存量", sort_order=1))
        session.commit()
    daily = fclient.get(f"/api/tasks/daily?date={DATE}").json()
    legacy = next(t for t in daily if t["title"] == "存量")
    assert legacy["task_type"] == "daily"


def test_task_history_ordering_completed_at_desc(fclient):
    t1 = fclient.post("/api/tasks", json={"task_date": DATE, "title": "1"}).json()
    t2 = fclient.post("/api/tasks", json={"task_date": DATE, "title": "2"}).json()
    fclient.patch(f"/api/tasks/{t1['id']}", json={"done": True})
    fclient.patch(f"/api/tasks/{t2['id']}", json={"done": True})
    history = fclient.get("/api/tasks/history").json()
    assert [h["id"] for h in history] == [t2["id"], t1["id"]]  # 最近完成在前
