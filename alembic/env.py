"""Alembic 环境：URL 解析顺序 PH_DATABASE_URL 环境变量 > PH_DATA_DIR 配置。

测试通过设置 PH_DATABASE_URL 指向临时库实现隔离（PRD §2.6）。
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import app.models  # noqa: F401  确保模型元数据注册
from app.config import ROOT_DIR, Settings
from app.db import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def resolve_url() -> str:
    override = os.environ.get("PH_DATABASE_URL", "").strip()
    url = override or Settings().db_url
    # SQLite 不会自动建目录；迁移入口独立于 app，需自行保证父目录存在
    from pathlib import Path

    db_file = Path(url.replace("sqlite:///", "", 1))
    db_file.parent.mkdir(parents=True, exist_ok=True)
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=resolve_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = resolve_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
