"""晨报独立 SQLite 数据模型（表 snake_case 复数、ISO8601 文本时间、短枚举）。

状态枚举（与 tasks.status 风格一致）：
- run_records.status: pending/running/success/failed/degraded
- news_items.category: domestic/international/ai
- news_items.content_status: fulltext/summary/missing
- news_items.dedupe_status: unique/duplicate_merged
- report_versions.status: published/blocked
- evaluations.status: ok/failed
- index_state.status: ok/failed/dirty
"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, Float, Integer, JSON, String, Text

from .db import MRBase


def _ts() -> str:
    from datetime import datetime, timezone, timedelta

    return datetime.now(timezone(timedelta(hours=8))).isoformat()


class RunRecord(MRBase):
    __tablename__ = "run_records"

    id = Column(Integer, primary_key=True)
    run_date = Column(String(10), nullable=False, index=True)  # YYYY-MM-DD（北京时间）
    kind = Column(String(16), nullable=False)  # collect/generate
    status = Column(String(16), nullable=False, default="pending")
    window_start = Column(String(32))  # ISO8601 CST
    window_end = Column(String(32))
    snapshot_id = Column(String(64))
    started_at = Column(String(32))
    finished_at = Column(String(32))
    error = Column(Text)
    stop_reason = Column(String(64))  # 用户主动停止等（迁移 v3 追加）
    stopped_at = Column(String(32))
    created_at = Column(String(32), default=_ts)


class RunLog(MRBase):
    __tablename__ = "run_logs"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, index=True, nullable=False)
    at = Column(String(32), default=_ts)
    stage = Column(String(32), nullable=False)  # collect/index/analysis/.../publish
    level = Column(String(8), nullable=False, default="info")  # info/warning/error
    message = Column(Text, nullable=False)
    detail = Column(JSON)  # 技术详情（模型/耗时/token 等），不含私密正文


class NewsItem(MRBase):
    __tablename__ = "news_items"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, index=True, nullable=False)
    category = Column(String(16), nullable=False)  # domestic/international/ai
    title = Column(Text, nullable=False)
    summary = Column(Text)
    source_name = Column(String(128))
    source_url = Column(Text)
    published_at = Column(String(32), index=True)  # ISO8601 CST，原始发布时间
    collected_at = Column(String(32), default=_ts)
    is_important = Column(Boolean, nullable=False, default=False, server_default="0")
    content_status = Column(String(16), default="summary")
    content_hash = Column(String(64), index=True)  # sha1(规范化标题+来源)，精确去重键
    event_group_id = Column(Integer, index=True)  # 同事件归组（保守，不删原始）
    dedupe_status = Column(String(20), default="unique")
    raw_ref = Column(JSON)  # 来源原始字段（AIHOT item / 归档行），便于追溯


class NewsFavoriteSetting(MRBase):
    __tablename__ = "news_favorite_settings"

    id = Column(Integer, primary_key=True)
    news_key = Column(String(80), nullable=False, unique=True)
    note = Column(Text, nullable=False, default="", server_default="")
    is_highlighted = Column(Boolean, nullable=False, default=False, server_default="0")
    created_at = Column(String(32), default=_ts)
    updated_at = Column(String(32), default=_ts, onupdate=_ts)


class EventGroup(MRBase):
    __tablename__ = "event_groups"

    id = Column(Integer, primary_key=True)
    category = Column(String(16), nullable=False)
    key_terms = Column(JSON, nullable=False)  # 归组依据的关键词
    representative_item_id = Column(Integer)
    created_at = Column(String(32), default=_ts)


class ReportVersion(MRBase):
    __tablename__ = "report_versions"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, index=True)
    report_date = Column(String(10), nullable=False, index=True)  # 所属晨报日
    version_no = Column(Integer, nullable=False, default=1)
    is_primary = Column(Boolean, nullable=False, default=False)
    status = Column(String(16), nullable=False, default="published")
    title = Column(Text)
    sections = Column(JSON, nullable=False)  # 五部分结构化内容
    content_md = Column(Text, nullable=False)  # 权威完整正文（Markdown）
    window_start = Column(String(32))
    window_end = Column(String(32))
    snapshot_id = Column(String(64), index=True)
    fact_check = Column(JSON)  # 已停用，仅保留历史数据兼容；新版本不写入
    generation_mode = Column(String(16), default="auto")  # auto/manual
    created_at = Column(String(32), default=_ts)


class Evaluation(MRBase):
    __tablename__ = "evaluations"

    id = Column(Integer, primary_key=True)
    version_id = Column(Integer, index=True, nullable=False)
    status = Column(String(8), nullable=False, default="ok")
    scores = Column(JSON)  # 五维 0-100
    composite = Column(Integer)  # 程序计算：等权平均四舍五入（quality_score_v1）
    comment = Column(Text)
    model = Column(String(64))
    rule_version = Column(String(32), default="quality_score_v1")
    created_at = Column(String(32), default=_ts)


class Memory(MRBase):
    """停用的历史表映射：仅保留结构兼容，晨报运行时不再读取或写入。"""
    __tablename__ = "memories"

    id = Column(Integer, primary_key=True)
    kind = Column(String(20), nullable=False)  # interest/action_pref/supplement_goal/other
    content = Column(Text, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    confirmed = Column(Boolean, nullable=False, default=True)
    source = Column(String(10), default="manual")  # manual/chat
    created_at = Column(String(32), default=_ts)
    updated_at = Column(String(32), default=_ts)


class StageCache(MRBase):
    __tablename__ = "stage_cache"

    id = Column(Integer, primary_key=True)
    node_key = Column(String(64), nullable=False, index=True)
    fingerprint = Column(String(64), nullable=False, index=True)  # sha1(输入依赖序列化)
    output = Column(JSON, nullable=False)
    model = Column(String(64))
    prompt_version = Column(String(32), default="v1")
    created_at = Column(String(32), default=_ts)
    expires_at = Column(String(32), nullable=False)


class EmbeddingCache(MRBase):
    __tablename__ = "embedding_cache"

    id = Column(Integer, primary_key=True)
    content_hash = Column(String(64), nullable=False, index=True)  # sha1(规范化文本)
    model = Column(String(64), nullable=False)
    dims = Column(Integer, nullable=False)
    vector = Column(JSON, nullable=False)
    created_at = Column(String(32), default=_ts)


class IndexState(MRBase):
    __tablename__ = "index_state"

    id = Column(Integer, primary_key=True)
    collection_name = Column(String(64), nullable=False, unique=True)
    status = Column(String(8), nullable=False, default="ok")  # ok/failed/dirty
    last_synced_at = Column(String(32))
    note = Column(Text)


class TokenUsage(MRBase):
    __tablename__ = "token_usage"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, index=True)
    node = Column(String(64), nullable=False)
    provider = Column(String(16), nullable=False)  # deepseek/dashscope
    model = Column(String(64), nullable=False)
    input_tokens = Column(Integer)
    output_tokens = Column(Integer)
    cache_hit_tokens = Column(Integer)
    cache_miss_tokens = Column(Integer)
    elapsed_ms = Column(Integer)
    cost_usd = Column(Float)
    price_tier = Column(String(10))  # peak/off_peak/unknown
    created_at = Column(String(32), default=_ts)


class PersonalEventSnapshot(MRBase):
    """“我的昨日”证据快照（只读 hub 数据的当期副本，不倒推历史）。"""

    __tablename__ = "personal_event_snapshots"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, index=True, nullable=False)
    snapshot_id = Column(String(64), nullable=False, index=True)
    source_table = Column(String(32), nullable=False)  # plans/tasks/important_info/reading
    record_id = Column(Integer, nullable=False)
    event_time = Column(String(32))  # 证据时间（有则填）
    summary = Column(Text, nullable=False)
    payload = Column(JSON)
    created_at = Column(String(32), default=_ts)


class RunStage(MRBase):
    """阶段进度状态（驱动前端进度面板；技术日志仍在 run_logs）。

    status: pending/running/success/warning/failed/skipped/interrupted
    skipped = 降级跳过（附 reason）；interrupted = 进程重启遗留，待确认。
    """

    __tablename__ = "run_stages"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, index=True, nullable=False)
    stage = Column(String(32), nullable=False, index=True)
    sort_order = Column(Integer, nullable=False, default=0)
    parent_stage = Column(String(32))  # 并行组标识（如 parallel_research）
    title = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False, default="pending")
    summary = Column(Text)  # 一行关键信息（给主面板）
    reason = Column(Text)  # 失败/降级/中断原因
    started_at = Column(String(32))
    finished_at = Column(String(32))
    elapsed_ms = Column(Integer)
    attempts = Column(Integer, default=0)
    last_event_at = Column(String(32), index=True)  # 活跃心跳（卡住监测）
    data = Column(JSON)  # 结构化结果（数量、评分等，已脱敏）
    created_at = Column(String(32), default=_ts)
