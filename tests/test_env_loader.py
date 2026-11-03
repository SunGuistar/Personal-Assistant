"""env_bootstrap 的加载优先级与覆盖行为。"""

from __future__ import annotations

import os
from pathlib import Path

import env_bootstrap
from env_bootstrap import load_hub_env, user_env_file


def _cleanup(*names: str) -> None:
    for name in names:
        os.environ.pop(name, None)


def test_user_env_dir_loaded(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("PH_TEST_USER_ONLY=from_user_dir\n", encoding="utf-8")
    monkeypatch.setenv("PH_USER_ENV_DIR", str(tmp_path))
    load_hub_env()
    try:
        assert os.environ["PH_TEST_USER_ONLY"] == "from_user_dir"
    finally:
        _cleanup("PH_TEST_USER_ONLY")


def test_project_env_overrides_user_env(tmp_path, monkeypatch):
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    (user_dir / ".env").write_text("PH_TEST_PRIO=user\n", encoding="utf-8")
    project_file = tmp_path / ".env"
    project_file.write_text("PH_TEST_PRIO=project\n", encoding="utf-8")
    monkeypatch.setenv("PH_USER_ENV_DIR", str(user_dir))
    monkeypatch.setattr(env_bootstrap, "PROJECT_ENV_FILE", project_file)
    load_hub_env()
    try:
        assert os.environ["PH_TEST_PRIO"] == "project"
    finally:
        _cleanup("PH_TEST_PRIO")


def test_missing_files_no_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("PH_USER_ENV_DIR", str(tmp_path / "not-exist"))
    monkeypatch.setattr(env_bootstrap, "PROJECT_ENV_FILE", tmp_path / "not-exist.env")
    load_hub_env()  # 不抛异常即通过


def test_default_user_env_location(monkeypatch):
    monkeypatch.delenv("PH_USER_ENV_DIR", raising=False)
    assert user_env_file() == Path.home() / ".personal-hub" / ".env"
