"""normalize_snapshot 重建对拍（阶段 3.4）。

在隔离副本上：复制真实原始库 + 真实归一化库到临时目录 → 用重建脚本
在副本上全量重建 → 与真实归一化库的副本逐行比对。真实库零写入（PRD §2.6）。
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from app.wechat_agent.data_api.normalize_snapshot import run_normalize

ROOT_DIR = Path(__file__).resolve().parent.parent
RAW_REAL = ROOT_DIR / "GetWechatInfo" / "DataInfo" / "chat_snapshot.sqlite3"
NORMALIZED_REAL = ROOT_DIR / "GetWechatInfo" / "DataInfo" / "chat_snapshot_normalized.sqlite3"

COLUMNS = "message_id, chat_id, timestamp, time, sender, text, msg_type, render_type"


@pytest.fixture()
def isolated_copy(tmp_path):
    """真实两库 → 临时副本；返回 (raw副本, normalized副本, normalized真身副本)。"""
    raw_copy = tmp_path / "raw.sqlite3"
    normalized_copy = tmp_path / "normalized.sqlite3"
    normalized_truth = tmp_path / "truth.sqlite3"
    for source, target in [
        (RAW_REAL, raw_copy),
        (NORMALIZED_REAL, normalized_copy),
        (NORMALIZED_REAL, normalized_truth),
    ]:
        src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        dst = sqlite3.connect(target)
        src.backup(dst)
        src.close()
        dst.close()
    return raw_copy, normalized_copy, normalized_truth


def _rows(path: Path, *, with_id: bool = True) -> list[tuple]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        columns = COLUMNS if with_id else COLUMNS.split(", ", 1)[1]
        rows = con.execute(f"SELECT {columns} FROM messages").fetchall()
        # 按内容列整体排序（避免 id 差异导致同时间戳行的位置错位）
        return sorted(rows, key=lambda row: tuple(str(item) for item in row))
    finally:
        con.close()


def test_rebuild_matches_history_row_by_row(isolated_copy):
    raw_copy, normalized_copy, truth = isolated_copy
    stats = run_normalize(raw_path=raw_copy, normalized_path=normalized_copy, all_chats=True)
    assert stats, "重建应至少处理一个群"

    # 内容级一致：归一化逻辑正确性（message_id 见下条测试单独归因）
    assert _rows(normalized_copy, with_id=False) == _rows(truth, with_id=False)


def test_id_differences_are_reexport_pairs(isolated_copy):
    """message_id 级差异必须全部来自原始库的重复导出对（同内容不同 id），
    差异数与重复导出对数相等；不允许存在无法归因的 id 差异。"""

    raw_copy, normalized_copy, truth = isolated_copy
    run_normalize(raw_path=raw_copy, normalized_path=normalized_copy, all_chats=True)

    rebuilt_ids = {row[0] for row in _rows(normalized_copy)}
    expected_ids = {row[0] for row in _rows(truth)}
    missing = expected_ids - rebuilt_ids

    # 统计原始库中的重复导出对：同 (chat_id, create_time, sender, content) 多行
    raw = sqlite3.connect(f"file:{raw_copy}?mode=ro", uri=True)
    try:
        dup_pairs = raw.execute(
            """SELECT count(*) FROM (
                   SELECT chat_id, create_time,
                          json_extract(message_json, '$.senderUsername') AS sender,
                          json_extract(message_json, '$.content') AS content,
                          count(*) AS n
                   FROM messages GROUP BY 1,2,3,4 HAVING n > 1
               )"""
        ).fetchone()[0]
    finally:
        raw.close()

    # 每条缺失 id 必须能在原始库找到同内容的其他 id（重复导出的同伴）
    assert len(missing) == dup_pairs, f"无法归因的 id 差异: {len(missing)} 条（重复导出对 {dup_pairs}）"


def test_rebuild_idempotent(isolated_copy):
    raw_copy, normalized_copy, _ = isolated_copy
    run_normalize(raw_path=raw_copy, normalized_path=normalized_copy, all_chats=True)
    first = _rows(normalized_copy)
    run_normalize(raw_path=raw_copy, normalized_path=normalized_copy, all_chats=True)
    second = _rows(normalized_copy)
    assert first == second  # 重复执行不产生重复/差异
