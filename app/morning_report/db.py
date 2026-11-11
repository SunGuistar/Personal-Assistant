"""晨报独立 SQLite：engine、Base 与轻量迁移器。

hub.db 走 Alembic（AGENTS §2）；晨报库是独立新库，使用本模块内置迁移器：
schema_migrations 版本表 + 有序迁移步骤（后续阶段追加步骤，禁止修改已发布步骤）。
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger(__name__)


class MRBase(DeclarativeBase):
    pass


def make_engine(db_path: Path | str) -> object:
    return create_engine(f"sqlite:///{Path(db_path)}", connect_args={"check_same_thread": False})


def make_session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def _migrations_table(meta: MetaData) -> Table:
    return Table(
        "schema_migrations",
        meta,
        Column("version", Integer, primary_key=True),
        Column("applied_at", String),
    )


# 迁移步骤：(version, name, apply_fn(engine))；apply_fn 用 MRBase.metadata.create_all 起步，
# 后续阶段只做追加式步骤（新表/新列），不回改历史步骤。
def _v1_init(engine) -> None:
    from . import models  # noqa: F401  确保所有表注册到 MRBase.metadata

    MRBase.metadata.create_all(engine)


def _v2_run_stages(engine) -> None:
    from . import models  # noqa: F401  RunStage 注册到 metadata

    from sqlalchemy import inspect

    run_stages = MRBase.metadata.tables.get("run_stages")
    if run_stages is not None and not inspect(engine).has_table("run_stages"):
        run_stages.create(engine)


def _v3_stop_fields(engine) -> None:
    from sqlalchemy import inspect, text

    cols = {c["name"] for c in inspect(engine).get_columns("run_records")}
    with engine.begin() as conn:
        if "stop_reason" not in cols:
            conn.execute(text("ALTER TABLE run_records ADD COLUMN stop_reason TEXT"))
        if "stopped_at" not in cols:
            conn.execute(text("ALTER TABLE run_records ADD COLUMN stopped_at TEXT"))


MIGRATIONS: list[tuple[int, str, object]] = [
    (1, "init_core_tables", _v1_init),
    (2, "run_stages", _v2_run_stages),
    (3, "stop_fields", _v3_stop_fields),
]


def run_migrations(engine) -> list[int]:
    """按序应用未执行的迁移；返回本次应用的版本号列表（幂等）。"""

    applied: list[int] = []
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version INTEGER PRIMARY KEY, applied_at TEXT)"
        ))
        done = {row[0] for row in conn.execute(text("SELECT version FROM schema_migrations"))}
        for version, name, fn in MIGRATIONS:
            if version in done:
                continue
            logger.info("晨报库迁移 %s (v%d) 应用", name, version)
            fn(engine)
            conn.execute(
                text("INSERT INTO schema_migrations (version, applied_at) VALUES (:v, datetime('now'))"),
                {"v": version},
            )
            applied.append(version)
    if applied:
        logger.info("晨报库迁移完成: %s", applied)
    return applied


def current_version(engine) -> int:
    with engine.connect() as conn:
        try:
            row = conn.execute(select(text("MAX(version)")).select_from(text("schema_migrations"))).first()
        except Exception:
            return 0
    return row[0] or 0
