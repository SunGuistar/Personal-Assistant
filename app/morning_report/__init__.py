"""今日晨报 V2.0 模块（产品依据：Docs/V0.6产品设计.md）。

分层：api/（薄路由）→ services/（业务）→ adapters/（外部源）→ graph/（LangGraph 工作流）。
独立 SQLite（见 db.py），hub.db 一律只读（services/hub_readonly.py）。
"""

from __future__ import annotations

from .config import MRCollections, MRSettings, get_mr_settings

__all__ = ["MRCollections", "MRSettings", "get_mr_settings"]
