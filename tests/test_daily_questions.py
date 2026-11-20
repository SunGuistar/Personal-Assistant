"""每日一问 API（迁移后的隔离临时库）。"""
import pytest


def test_create_update_and_reload(fclient):
    assert fclient.get("/api/daily_questions").json() == []
    created = fclient.post("/api/daily_questions", json={"question": " 问题？ ", "answer": " 答案 "})
    assert created.status_code == 201
    item = created.json()
    assert item["question"] == "问题？"
    assert item["answer"] == "答案"
    assert item["created_at"] and item["updated_at"]
    other = fclient.post("/api/daily_questions", json={"question": "第二问", "answer": "第二答"}).json()
    assert [q["id"] for q in fclient.get("/api/daily_questions").json()] == [other["id"], item["id"]]
    updated = fclient.put(f"/api/daily_questions/{item['id']}", json={"question": "新问题", "answer": "新答案\n第二行"})
    assert updated.status_code == 200
    reloaded = fclient.get("/api/daily_questions").json()[1]
    assert reloaded["question"] == "新问题"
    assert reloaded["answer"] == "新答案\n第二行"
    assert reloaded["created_at"] == item["created_at"]
    assert fclient.put("/api/daily_questions/99999", json={"question": "问", "answer": "答"}).status_code == 404


@pytest.mark.parametrize("body", [{}, {"question": "问"}, {"question": " ", "answer": "答"}, {"question": "问", "answer": " "}, {"question": None, "answer": "答"}, {"question": "问" * 501, "answer": "答"}])
def test_invalid_question(fclient, body):
    assert fclient.post("/api/daily_questions", json=body).status_code == 422
    assert fclient.put("/api/daily_questions/1", json=body).status_code == 422


def test_delete_question_removes_database_row_and_pending_round_references(fclient):
    from app.models.daily_question import DailyQuestion

    first, second = [fclient.post("/api/daily_questions", json={"question": title, "answer": "答"}).json()
                     for title in ("待删除题", "保留题")]
    before = fclient.get("/api/daily_questions/today").json()
    response = fclient.request("DELETE", f"/api/daily_questions/{first['id']}", json={"confirmed": True})
    assert response.status_code == 204
    with fclient.app.state.session_factory() as session:
        assert session.get(DailyQuestion, first["id"]) is None
        assert session.get(DailyQuestion, second["id"]) is not None
    assert [q["id"] for q in fclient.get("/api/daily_questions").json()] == [second["id"]]
    after = fclient.get("/api/daily_questions/today").json()
    assert [q["id"] for q in after["queue"]] == [second["id"]]
    assert after["total"] == 1 and after["completed"] == 0
    assert after["version"] == before["version"] + 1
    assert fclient.post("/api/daily_questions/today/review", json={
        "question_id": first["id"], "remembered": True,
        "review_date": before["review_date"], "version": before["version"],
    }).status_code == 409
    assert fclient.post("/api/daily_questions/today/review", json={
        "question_id": second["id"], "remembered": True,
        "review_date": after["review_date"], "version": after["version"],
    }).json()["completed"] == 1


@pytest.mark.parametrize("body,status", [({}, 422), ({"confirmed": "true"}, 422),
                                        ({"confirmed": False}, 400)])
def test_delete_requires_explicit_confirmation(fclient, body, status):
    item = fclient.post("/api/daily_questions", json={"question": "问", "answer": "答"}).json()
    assert fclient.request("DELETE", f"/api/daily_questions/{item['id']}", json=body).status_code == status
    assert fclient.get("/api/daily_questions").json() == [item]


def test_delete_last_question_and_unknown_question(fclient):
    item = fclient.post("/api/daily_questions", json={"question": "问", "answer": "答"}).json()
    fclient.get("/api/daily_questions/today")
    assert fclient.request("DELETE", f"/api/daily_questions/{item['id']}", json={"confirmed": True}).status_code == 204
    state = fclient.get("/api/daily_questions/today").json()
    assert state["queue"] == [] and state["total"] == state["completed"] == 0
    assert state["has_questions"] is False
    assert fclient.request("DELETE", f"/api/daily_questions/{item['id']}", json={"confirmed": True}).status_code == 404


def test_delete_preserves_completed_progress_and_rolls_back_on_failure(fclient, monkeypatch):
    from app.exceptions import DomainError
    from app.models.daily_question import DailyQuestion
    from sqlalchemy.orm import Session

    ids = [fclient.post("/api/daily_questions", json={"question": str(i), "answer": "答"}).json()["id"] for i in range(3)]
    state = fclient.get("/api/daily_questions/today").json()
    state = fclient.post("/api/daily_questions/today/review", json={
        "question_id": ids[0], "remembered": True, "review_date": state["review_date"], "version": state["version"],
    }).json()
    original_delete = Session.delete

    def fail_delete(session, instance):
        if isinstance(instance, DailyQuestion):
            raise DomainError("模拟删除失败", code="test_failure", status_code=400)
        return original_delete(session, instance)

    with monkeypatch.context() as patch:
        patch.setattr(Session, "delete", fail_delete)
        assert fclient.request("DELETE", f"/api/daily_questions/{ids[1]}", json={"confirmed": True}).status_code == 400
    assert fclient.get("/api/daily_questions/today").json() == state
    assert len(fclient.get("/api/daily_questions").json()) == 3
    assert fclient.request("DELETE", f"/api/daily_questions/{ids[1]}", json={"confirmed": True}).status_code == 204
    after = fclient.get("/api/daily_questions/today").json()
    assert after["completed"] == 1 and after["total"] == 2
    assert [q["id"] for q in after["queue"]] == [ids[2]]
