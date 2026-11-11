"""集中配置（pydantic-settings）。

所有环境相关参数经此处读取；敏感信息（API Key）不在此出现，仍走 .env + os.environ。
测试通过显式构造 Settings 覆盖路径，实现对真实数据的隔离（见 tests/conftest.py）。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from env_bootstrap import load_hub_env

load_hub_env()  # 密钥权威源在用户目录 ~/.personal-hub/.env；须在 Settings() 读环境变量前完成

ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PH_", env_file=str(ROOT_DIR / ".env"), extra="ignore")

    hub_host: str = "127.0.0.1"
    hub_port: int = 8621  # V2 工作区默认 8621（main 工作区占用 8620；可用 PH_HUB_PORT 覆盖）

    data_dir: Path = ROOT_DIR / "data"
    static_dir: Path = ROOT_DIR / "web" / "dist"
    log_dir: Path | None = None  # 默认 data_dir/logs

    news_refresh_minutes: int = 30  # 资讯缓存有效期（PRD §2.2：默认 30 分钟）
    # 阅读管理：笔记附件上传限制（PRD §2.4）
    upload_max_mb: int = 50

    # 阶段 3 使用：WeChatDataAnalysis 桌面程序路径（D5，仅启动经配置与校验的程序）
    wechat_analysis_exe: str = ""

    # 阶段 5 使用：永久保护的消息日期（Asia/Shanghai 本地日期，逗号分隔，可扩展）
    protected_dates: str = "2026-10-27"

    @property
    def protected_date_list(self) -> list[str]:
        return [d.strip() for d in self.protected_dates.split(",") if d.strip()]

    @property
    def logs_path(self) -> Path:
        return self.log_dir or (self.data_dir / "logs")

    @property
    def reading_notes_dir(self) -> Path:
        return self.data_dir / "reading_notes"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'hub.db'}"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.logs_path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """默认实例（生产入口使用）；测试请显式构造并注入 create_app。"""

    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
