"""日志装配：按天滚动文件 + 控制台。

隐私白名单（AGENTS §6）：文件日志只记时间/任务ID/操作类型/数量/结果/耗时/非敏感错误。
调用方负责不把消息正文、Agent 回答、密钥写入日志；本模块只做通道装配。
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def setup_logging(log_dir: Path, level: int = logging.INFO) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if root.handlers:  # 重复装配（测试多 app）时先清空
        for handler in root.handlers[:]:
            root.removeHandler(handler)
    root.setLevel(level)

    file_handler = TimedRotatingFileHandler(
        log_dir / "hub.log", when="midnight", backupCount=7, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(file_handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(console)

    # 收敛第三方噪音
    for noisy in ("uvicorn.access",):
        logging.getLogger(noisy).setLevel(logging.WARNING)
