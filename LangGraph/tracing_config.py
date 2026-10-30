"""LangSmith 追踪的本地化调优：收敛报错日志 + 增强后台上传重试。

背景（langsmith 0.14 实测）：
- 上传失败时 SDK 用 logger.warning 打印整段异常：完整堆栈 + 脱敏 API Key +
  几十条 trace id 列表，动辄上千字符刷屏。这是标准 logging，可用过滤器截断。
- 后台批量上传本身有重试（_send_multipart_req 默认 attempts=3），
  但读超时 _TRACING_SEND_TIMEOUT=(3, 10) 与重试次数都是模块级常量，
  不开放环境变量配置，只能在运行时微调。

agent.py 启动初期调用 configure_tracing() 即可。
"""

from __future__ import annotations

import logging

_LOG_MAX_CHARS = 200


class _CompactLangsmithFilter(logging.Filter):
    """截断 langsmith 家族 logger 的超长记录，只留首行摘要。"""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if len(message) > _LOG_MAX_CHARS:
            head = message.splitlines()[0][: _LOG_MAX_CHARS - 30]
            record.msg = f"{head}……（已截断，原文 {len(message)} 字符）"
            record.args = ()
        return True


def _compact_logging() -> None:
    """截断 langsmith 家族 logger 的超长记录。

    过滤器挂在 handler 上而非 logger 上：logger.filter 只对直接发到该
    logger 的记录生效，子 logger（langsmith.client 等）传播上来的记录
    只有经过 handler 时才会被过滤。
    """

    logger = logging.getLogger("langsmith")
    if getattr(logger, "_compact_configured", False):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(_CompactLangsmithFilter())
    logger.addHandler(handler)
    logger.propagate = False  # 不再经 root，避免双份输出
    logger._compact_configured = True


def _strengthen_retries() -> None:
    """提高后台上传的重试次数与读超时（官方常量不可配置，运行时调整）。"""

    from langsmith import client as ls_client

    # 读超时 10s -> 30s：弱网环境下 multipart 批量包（可达数百 KB）更可能传完
    ls_client._TRACING_SEND_TIMEOUT = (5, 30)

    # 重试 3 次 -> 5 次
    original = ls_client.Client._send_multipart_req

    def _send_with_more_attempts(self, *args, **kwargs):
        kwargs.setdefault("attempts", 5)
        return original(self, *args, **kwargs)

    ls_client.Client._send_multipart_req = _send_with_more_attempts

    compressed_original = ls_client.Client._send_compressed_multipart_req

    def _send_compressed_with_more_attempts(self, *args, **kwargs):
        kwargs.setdefault("attempts", 5)
        return compressed_original(self, *args, **kwargs)

    ls_client.Client._send_compressed_multipart_req = _send_compressed_with_more_attempts


def configure_tracing() -> None:
    _compact_logging()
    _strengthen_retries()
