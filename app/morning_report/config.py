"""晨报模块独立配置（与 hub Settings 分离，但复用 env_bootstrap 已加载的环境变量）。

环境变量前缀 PH_MR_；测试显式构造覆盖路径与开关。
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class MRCollections(BaseSettings):
    """Qdrant Collection 名（snake_case，与 chat_chunks/rag_state 风格一致）。"""

    tech_news: str = "morning_tech_news"
    reports: str = "morning_reports"


class MRSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PH_MR_", extra="ignore")

    # 独立 SQLite
    db_filename: str = "morning_report.db"

    # Qdrant（必须用 127.0.0.1，禁止 localhost：Windows IPv6 每请求卡 ~21s）
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_api_key: str = ""

    # 每天 08:00（Asia/Shanghai）常态采集+生成
    schedule_enabled: bool = True
    schedule_hour: int = 8
    schedule_minute: int = 0

    # 模型路由（V0.6 §6.1 / V0.6.1 §6.1）
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_model: str = "qwen-flash"
    quality_eval_model: str = "qwen-flash"

    # Embedding（DashScope text-embedding-v4，1024 维；T13 实测）
    embedding_model: str = "text-embedding-v4"
    embedding_dims: int = 1024
    # Sparse/BM25（fastembed 本地模型，零外网零付费）
    sparse_model: str = "Qdrant/bm25"

    # 阶段缓存有效期（小时，V0.5 §5.2：最长 12h）
    stage_cache_ttl_hours: int = 12

    # 阶段"较长时间未更新"提醒阈值（秒，仅提示不判失败）
    progress_stall_seconds: int = 150

    collections: MRCollections = MRCollections()


@lru_cache(maxsize=1)
def get_mr_settings() -> MRSettings:
    return MRSettings()


def reset_mr_settings_cache() -> None:
    get_mr_settings.cache_clear()
