"""WeChatDataAnalysis 适配器：运行状态检查与自动启动（D5）。

- status()：健康检查（读 /api/chat/accounts），返回结构化状态
- ensure_running()：未运行时启动设置中配置并校验的桌面程序（D5：
  仅启动白名单校验过的 exe），轮询 API 就绪；找不到环境/启动失败/
  超时均抛领域异常（明确错误，绝不自动创建环境）
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

from ..exceptions import DomainError
from app.wechat_agent.data_api.wechat_data_api import WeChatDataAPIClient, WeChatDataAPIError

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://127.0.0.1:10392"
READY_TIMEOUT_SECONDS = 60.0
POLL_INTERVAL = 1.0


class WechatSourceAdapter:
    """封装 WeChatDataAnalysis 本地 API 客户端 + 桌面程序启动。"""

    def __init__(
        self,
        *,
        exe_path: str = "",
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 10.0,
        ready_timeout: float = READY_TIMEOUT_SECONDS,
    ) -> None:
        self.exe_path = exe_path.strip()
        self.client = WeChatDataAPIClient(base_url, timeout=timeout)
        self.ready_timeout = ready_timeout

    # ---- 状态 ----

    def status(self) -> dict:
        try:
            payload = self.client.list_accounts()
        except WeChatDataAPIError as exc:
            return {"running": False, "message": str(exc)}
        accounts = payload.get("accounts") or []
        return {"running": True, "base_url": self.client.base_url, "accounts": accounts}

    # ---- 启动 ----

    def _validate_exe(self) -> Path:
        if not self.exe_path:
            raise DomainError(
                "未配置 WeChatDataAnalysis 程序路径，请在设置中配置后重试",
                code="source_not_configured",
                status_code=502,
            )
        exe = Path(self.exe_path)
        if not exe.is_file():
            raise DomainError(
                f"配置的 WeChatDataAnalysis 程序不存在: {exe}",
                code="source_exe_missing",
                status_code=502,
            )
        if exe.suffix.lower() != ".exe":
            raise DomainError(
                f"仅允许启动 .exe 程序: {exe.name}",
                code="source_exe_invalid",
                status_code=502,
            )
        return exe

    def ensure_running(self) -> dict:
        """已运行直接返回；否则按配置启动并等待 API 就绪。"""

        current = self.status()
        if current["running"]:
            return {**current, "started": False}

        exe = self._validate_exe()
        logger.info("启动 WeChatDataAnalysis: %s", exe)
        try:
            subprocess.Popen(
                [str(exe)],
                cwd=str(exe.parent),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            raise DomainError(
                f"WeChatDataAnalysis 启动失败: {exc}",
                code="source_start_failed",
                status_code=502,
            )

        deadline = time.monotonic() + self.ready_timeout
        while time.monotonic() < deadline:
            current = self.status()
            if current["running"]:
                return {**current, "started": True}
            time.sleep(POLL_INTERVAL)
        raise DomainError(
            f"WeChatDataAnalysis {self.ready_timeout:.0f}s 内 API 未就绪，请手动检查该程序",
            code="source_not_ready",
            status_code=504,
        )
