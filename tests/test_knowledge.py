"""知识库复习与旧题兼容，使用隔离库。"""
from datetime import datetime, timezone


def test_review_schedule_and_edit_reset(fclient):
    q = fclient.post("/api/daily_questions", json={"question": "如何回忆", "answer": "先想再看", "tags": "记忆"}).json()
    assert q["review_count"] == 0 and q["due_at"] is None
    for expected_days in (1, 3, 7, 14, 30, 30):
        r = fclient.post(f"/api/daily_questions/{q['id']}/review", json={"remembered": True})
        assert r.status_code == 200
        q = r.json()
        days = (datetime.fromisoformat(q["due_at"]) - datetime.now(timezone.utc)).total_seconds() / 86400
        assert expected_days - .01 < days <= expected_days
    q = fclient.post(f"/api/daily_questions/{q['id']}/review", json={"remembered": False}).json()
    assert q["review_level"] == 0 and q["review_count"] == 7
    seconds = (datetime.fromisoformat(q["due_at"]) - datetime.now(timezone.utc)).total_seconds()
    assert 590 < seconds <= 600
    q = fclient.put(f"/api/daily_questions/{q['id']}", json={"question": "改问题", "answer": "新答案", "tags": "新标签"}).json()
    assert q["due_at"] is None and q["review_level"] == 0
    assert q["review_count"] == 7 and q["tags"] == "新标签"
    assert fclient.get("/api/daily_questions").json()[0] == q


def test_review_invalid_and_missing(fclient):
    assert fclient.post("/api/daily_questions/999/review", json={"remembered": True}).status_code == 404
    assert fclient.post("/api/daily_questions/999/review", json={"remembered": "false"}).status_code == 422
