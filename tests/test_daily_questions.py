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
