"""密钥环境文件统一加载（AGENTS §5）。

权威密钥文件放在**用户目录** ``~/.personal-hub/.env``（在仓库之外，项目目录
被删除/移动也不丢密钥）；项目根 ``.env`` 仅作可选的本地覆盖（优先级：
项目 .env > 用户目录 .env）。键名清单见项目根 ``.env.example``。

用户目录可用环境变量 PH_USER_ENV_DIR 覆盖（测试与多机迁移用）。
本模块不依赖 app/ 包，供 app/ 与现有 LangGraph/ 等模块共用；
阶段 3 目录迁移后随微信模块迁入 app/wechat_agent/。
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ENV_FILE = Path(__file__).resolve().parent / ".env"


def user_env_file() -> Path:
    override = os.environ.get("PH_USER_ENV_DIR", "").strip()
    base = Path(override) if override else Path.home() / ".personal-hub"
    return base / ".env"


def load_hub_env() -> None:
    """加载顺序：先用户目录（不覆盖已有环境变量），后项目根（允许覆盖）。

    幂等，可重复调用；文件不存在时静默跳过。
    """

    from dotenv import load_dotenv

    user_file = user_env_file()
    if user_file.exists():
        load_dotenv(user_file, override=False)
    if PROJECT_ENV_FILE.exists():
        load_dotenv(PROJECT_ENV_FILE, override=True)
