"""首页及 SPA 回退必须重新校验，条件请求也保留缓存策略。"""
import pytest
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from app.main import SPAStaticFiles


@pytest.fixture
def static_client(tmp_path):
    (tmp_path / 'index.html').write_text('<html>current</html>', encoding='utf-8')
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'assets' / 'index-abc123.js').write_text('current()', encoding='utf-8')
    app = Starlette(routes=[Mount('/', app=SPAStaticFiles(directory=tmp_path, html=True))])
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize('path', ['/', '/index.html', '/knowledge'])
def test_html_revalidates_including_not_modified(static_client, path):
    response = static_client.get(path)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-cache'
    cached = static_client.get(path, headers={'If-None-Match': response.headers['etag']})
    assert cached.status_code == 304
    assert cached.headers['cache-control'] == 'no-cache'


def test_script_keeps_existing_cache_behavior(static_client):
    response = static_client.get('/assets/index-abc123.js')
    assert response.status_code == 200
    assert 'cache-control' not in response.headers
    assert static_client.get('/assets/index-abc123.js', headers={'If-None-Match': response.headers['etag']}).status_code == 304


def test_api_miss_does_not_return_html(static_client):
    assert static_client.get('/api/missing').status_code == 404
