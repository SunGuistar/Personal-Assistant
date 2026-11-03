"""统一错误格式：{detail: {code, message}}。"""


def test_unknown_api_route_404_shape(client):
    # 统一错误格式约束 /api/* 路径；前端非 API 路径由 SPA 回退到 index.html（见 ARCH §3.5）
    response = client.get("/api/no-such-route")
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["code"] == "not_found"
    assert detail["message"]


def test_validation_error_shape(client):
    response = client.get("/api/tasks/not-an-int")
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "validation_error"
    assert detail["message"]
