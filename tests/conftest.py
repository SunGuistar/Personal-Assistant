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


@pytest.fixture(scope="session")
def task_runner(client):
    return client.app.state.task_runner
