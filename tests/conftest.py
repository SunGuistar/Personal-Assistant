"""pytest 公共 Fixture。

数据隔离（PRD §2.6 / AGENTS §5）：所有测试使用临时目录的 hub.db；
真实聊天库的 mtime 在模块导入时快照，隔离守卫测试断言其未被触碰。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parent.parent

REAL_CHAT_DBS = [
    ROOT_DIR / "GetWechatInfo" / "DataInfo" / "chat_snapshot.sqlite3",
    ROOT_DIR / "GetWechatInfo" / "DataInfo" / "chat_snapshot_normalized.sqlite3",
]

# 模块导入时快照真实库 mtime（纳秒级），任何时刻的守卫测试都与之比对
REAL_DB_MTIMES = {
    str(path): path.stat().st_mtime_ns for path in REAL_CHAT_DBS if path.exists()
}


@pytest.fixture(autouse=True)
def isolated_morning_external_dependencies(request, monkeypatch):
    """晨报默认零外网/付费调用；生成测试使用独立内存向量库。

    stage3 是既有本地 Qdrant 集成测试，限定 tmp_mr_* 集合，自行管理生命周期。
    其余晨报用例的未 Mock HTTP 一律失败，防止临时 SQLite 误连正式向量库。
    """
    if not request.path.name.startswith("test_morning"):
        yield
        return
    import respx
    from qdrant_client import QdrantClient
    from app.morning_report.services import report_service
    from app.morning_report.services.qdrant_store import QdrantStore

    clients = []

    def memory_store(*args, **kwargs):
        store = QdrantStore.__new__(QdrantStore)
        store.client = QdrantClient(":memory:")
        store.dense_dims = 8
        clients.append(store.client)
        return store

    class FakeEmbedding:
        dims = 8
        model_name = "fake-morning-isolated"

        def embed_dense(self, texts):
            return [[1.0] + [0.0] * 7 for _ in texts]

        def embed_sparse(self, texts):
            return [([1], [1.0]) for _ in texts]

    monkeypatch.setattr(report_service, "QdrantStore", memory_store)
    monkeypatch.setattr(report_service, "DefaultEmbeddingProvider", FakeEmbedding)
    try:
        if request.path.name == "test_morning_stage3_rag.py":
            yield
        else:
            with respx.mock(assert_all_called=False, assert_all_mocked=True):
                yield
    finally:
        for client in clients:
            client.close()


def _run_alembic_upgrade(db_url: str) -> None:
    os.environ["PH_DATABASE_URL"] = db_url
    alembic_cfg = Config(str(ROOT_DIR / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")


@pytest.fixture(scope="session")
def app_settings(tmp_path_factory):
    from app.config import Settings

    data_dir = tmp_path_factory.mktemp("hub-data")
    return Settings(data_dir=data_dir, static_dir=ROOT_DIR / "web" / "dist")


@pytest.fixture(scope="session")
def client(app_settings):
    _run_alembic_upgrade(app_settings.db_url)

    from app.main import create_app

    app = create_app(app_settings)
    with TestClient(app) as test_client:
        yield test_client
    app.state.engine.dispose()


@pytest.fixture()
def fclient(tmp_path):
    """函数级隔离客户端：每个用例独立的临时库（API 集成测试用）。"""

    from app.config import Settings
    from app.main import create_app

    settings = Settings(data_dir=tmp_path / "data", static_dir=ROOT_DIR / "web" / "dist")
    _run_alembic_upgrade(settings.db_url)
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
    app.state.engine.dispose()


@pytest.fixture(scope="session")
def task_runner(client):
    return client.app.state.task_runner
