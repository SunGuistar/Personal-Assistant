"""微信模块引用别名：同一基线测试在目录迁移前后运行无需改 import。

迁移后优先从新包 app.wechat_agent 导入；迁移前回落到旧路径 LangGraph。
本文件自身在 3.2 迁移完成后更新优先级（新路径在前）。
"""

from __future__ import annotations

import pytest

try:  # 迁移后（阶段 3.2 起）
    from app.wechat_agent.agent import build_agent, build_system_prompt  # noqa: F401
    from app.wechat_agent.chat_tools.chat_tools import ALL_TOOLS  # noqa: F401
    from app.wechat_agent.normal_tools.chunking import Chunk, chunk_messages  # noqa: F401
    from app.wechat_agent.normal_tools.report_render import render_html  # noqa: F401
    from app.wechat_agent.structured.structured_message import (  # noqa: F401
        StructuredMessage,
        from_raw_rows,
        to_llm_text,
    )
    MIGRATED = True
except ImportError:  # 迁移前
    from LangGraph.agent import build_agent, build_system_prompt  # noqa: F401
    from LangGraph.Chat_tools.chat_tools import ALL_TOOLS  # noqa: F401
    from LangGraph.Normal_Tools.chunking import Chunk, chunk_messages  # noqa: F401
    from LangGraph.Normal_Tools.report_render import render_html  # noqa: F401
    from Tool.structured_message import (  # noqa: F401
        StructuredMessage,
        from_raw_rows,
        to_llm_text,
    )
    MIGRATED = False
