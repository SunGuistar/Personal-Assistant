"""每日题单使用隔离临时库，默认零外网。"""
from datetime import datetime, timedelta, timezone

from app.services import daily_question_rounds_service as rounds


def test_round_is_fixed_persistent_and_rotates(fclient, monkeypatch):
    day = datetime(2026, 11, 14, 12, tzinfo=timezone(timedelta(hours=8)))
    monkeypatch.setattr(rounds, "_now", lambda: day)
    ids = [fclient.post("/api/daily_questions", json={"question": str(i), "answer": "a"}).json()["id"] for i in range(3)]
    first = fclient.get("/api/daily_questions/today").json()
    assert [q["id"] for q in first["queue"]] == ids
    assert first["total"] == 3 and first["completed"] == 0
    late = fclient.post("/api/daily_questions", json={"question": "late", "answer": "a"}).json()["id"]

    def submit(state, remembered):
        return fclient.post("/api/daily_questions/today/review", json=dict(
            question_id=state["queue"][0]["id"], remembered=remembered,
            version=state["version"], review_date=state["review_date"]))

    state = submit(first, False).json()
    assert [q["id"] for q in state["queue"]] == [ids[1], ids[2], ids[0]]
    assert state["total"] == 3 and state["completed"] == 0
    assert submit(first, False).status_code == 409
    assert next(q for q in fclient.get("/api/daily_questions").json() if q["id"] == ids[0])["forgotten_count"] == 1
    assert state == fclient.get("/api/daily_questions/today").json()
    # 全新连接模拟重启，题单顺序与进度仍从数据库恢复。
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    engine = create_engine(fclient.app.state.engine.url)
    try:
        with Session(engine) as session:
            restored = rounds.today(session)
            assert restored["completed"] == 0
            assert [q.id for q in restored["queue"]] == [ids[1], ids[2], ids[0]]
    finally:
        engine.dispose()
    # 知识库反馈改变到期时间，也不能改变已固定的题单。
    fclient.post(f"/api/daily_questions/{ids[1]}/review", json={"remembered": True})
    assert state["total"] == fclient.get("/api/daily_questions/today").json()["total"]
    for completed in range(1, 4):
        state = submit(state, True).json()
        assert state["completed"] == completed and state["total"] == 3
    assert state["queue"] == []
    # 额外练习只影响学习记录，不重置当日完成进度。
    fclient.post(f"/api/daily_questions/{ids[0]}/review", json={"remembered": False})
    assert fclient.get("/api/daily_questions/today").json() == state
    monkeypatch.setattr(rounds, "_now", lambda: day + timedelta(days=1))
    tomorrow = fclient.get("/api/daily_questions/today").json()
    assert tomorrow["review_date"] == "2026-11-15" and tomorrow["completed"] == 0
    assert late in [q["id"] for q in tomorrow["queue"]]
    assert fclient.post("/api/daily_questions/today/review", json=dict(question_id=ids[0], remembered=True,
        version=state["version"], review_date=state["review_date"])).status_code == 409


def test_eligibility_order_and_beijing_midnight(fclient, monkeypatch):
    from app.models.daily_question import DailyQuestion
    clock = datetime(2026, 11, 14, 23, 59, tzinfo=timezone(timedelta(hours=8)))
    monkeypatch.setattr(rounds, "_now", lambda: clock)
    ids = [fclient.post("/api/daily_questions", json={"question": str(i), "answer": "a"}).json()["id"] for i in range(4)]
    with fclient.app.state.session_factory() as session:
        session.get(DailyQuestion, ids[1]).due_at = "2026-11-14T01:00:00+08:00"
        session.get(DailyQuestion, ids[2]).due_at = "2026-11-14T00:00:00+08:00"
        session.get(DailyQuestion, ids[3]).due_at = "2026-11-15T00:00:00+08:00"
        session.commit()
    assert [q["id"] for q in fclient.get("/api/daily_questions/today").json()["queue"]] == [ids[2], ids[1], ids[0]]
    clock += timedelta(minutes=1)
    state = fclient.get("/api/daily_questions/today").json()
    assert state["review_date"] == "2026-11-15"
    assert [q["id"] for q in state["queue"]] == [ids[2], ids[1], ids[3], ids[0]]


def test_empty_round_stays_empty_until_next_day(fclient):
    first = fclient.get("/api/daily_questions/today").json()
    assert first["total"] == first["completed"] == 0 and first["queue"] == []
    assert first["has_questions"] is False
    fclient.post("/api/daily_questions", json={"question": "q", "answer": "a"})
    later = fclient.get("/api/daily_questions/today").json()
    assert later["queue"] == [] and later["has_questions"] is True


def test_failed_review_rolls_back_round(fclient, monkeypatch):
    from app.exceptions import DomainError
    fclient.post("/api/daily_questions", json={"question": "q", "answer": "a"})
    state = fclient.get("/api/daily_questions/today").json()

    def fail(*args, **kwargs):
        raise DomainError("保存失败", code="test_failure", status_code=400)

    monkeypatch.setattr(rounds, "review_question", fail)
    result = fclient.post("/api/daily_questions/today/review", json=dict(question_id=state["queue"][0]["id"],
        remembered=True, review_date=state["review_date"], version=state["version"]))
    assert result.status_code == 400
    assert fclient.get("/api/daily_questions/today").json() == state
