"""经验库隔离 API 测试，不访问模型或个人正文日志。"""
import pytest


@pytest.mark.parametrize('method,path', [('GET', '/api/experiences'), ('POST', '/api/experiences'), ('PUT', '/api/experiences/1')])
def test_experience_missing_table_is_explicit_and_not_created(fclient, tmp_path, method, path):
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.orm import Session
    from app.api.deps import get_session

    engine = create_engine(f'sqlite:///{tmp_path / "unmigrated.db"}')
    def unmigrated_session():
        with Session(engine) as session:
            yield session
    fclient.app.dependency_overrides[get_session] = unmigrated_session
    try:
        response = fclient.request(method, path, **({} if method == 'GET' else {'json': dict(title='问题', problem='现象', solution='方法')}))
        assert response.status_code == 503
        assert response.json()['detail']['code'] == 'experiences_schema_missing'
        assert '迁移' in response.json()['detail']['message']
        assert not inspect(engine).has_table('experiences')
    finally:
        fclient.app.dependency_overrides.pop(get_session, None)
        engine.dispose()


def test_experience_create_update_and_persistence(fclient):
    assert fclient.get('/api/experiences').json() == []
    body = {'title': ' Windows 连接问题 ', 'problem': '连接超时', 'solution': '使用 127.0.0.1', 'tags': 'Windows，网络'}
    response = fclient.post('/api/experiences', json=body)
    assert response.status_code == 201
    item = response.json()
    assert item['title'] == 'Windows 连接问题'
    assert item['created_at'] and item['updated_at']
    body.update(title='修正连接地址', solution='改为 IPv4 回环地址')
    updated = fclient.put(f"/api/experiences/{item['id']}", json=body)
    assert updated.status_code == 200
    assert updated.json()['created_at'] == item['created_at']
    assert fclient.get('/api/experiences').json() == [updated.json()]


@pytest.mark.parametrize('field', ['title', 'problem', 'solution'])
def test_experience_rejects_blank_required_fields(fclient, field):
    body = dict(title='问题', problem='现象', solution='处理方法')
    body[field] = '   '
    assert fclient.post('/api/experiences', json=body).status_code == 422
    assert fclient.get('/api/experiences').json() == []


def test_experience_missing_update_and_no_delete_endpoint(fclient):
    body = dict(title='问题', problem='现象', solution='处理方法')
    response = fclient.put('/api/experiences/999', json=body)
    assert response.status_code == 404
    assert response.json()['detail']['code'] == 'not_found'
    assert fclient.delete('/api/experiences/999').status_code == 405
