"""数据隔离守卫（PRD §2.6）：测试会话不得触碰唯一真实聊天数据。"""

from __future__ import annotations

from pathlib import Path

from conftest import REAL_CHAT_DBS, REAL_DB_MTIMES


def test_settings_use_isolated_db(app_settings):
    db_file = Path(app_settings.db_url.replace("sqlite:///", ""))
    real_dirs = {path.parent for path in REAL_CHAT_DBS}
    assert db_file.name == "hub.db"
    assert db_file.parent not in real_dirs
    for real_dir in real_dirs:
        assert real_dir not in db_file.parents


def test_real_chat_dbs_untouched():
    for path_str, mtime_ns in REAL_DB_MTIMES.items():
        path = Path(path_str)
        assert path.exists(), f"真实库消失: {path}"
        assert path.stat().st_mtime_ns == mtime_ns, f"真实库被修改: {path}"
