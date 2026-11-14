"""启动阶段计时：仅保存阶段名、状态、耗时和异常类型。"""
from contextlib import contextmanager
from functools import wraps
import json
import logging
import os
from pathlib import Path
import time
import threading

logger = logging.getLogger(__name__)
_TRACE_LOCK = threading.Lock()


def _emit(name, status, started, error_type=None):
    event = dict(stage=name, status=status, duration_s=round(time.perf_counter() - started, 4))
    if error_type:
        event["error_type"] = error_type
    logger.info("startup %s", json.dumps(event, ensure_ascii=False))
    target = os.environ.get("PH_STARTUP_TRACE")
    if target:
        try:
            with _TRACE_LOCK:
                with Path(target).open("a", encoding="utf-8") as output:
                    output.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError:
            logger.warning("启动诊断写入失败")


@contextmanager
def stage(name):
    started = time.perf_counter()
    _emit(name, "running", started)
    try:
        yield
    except BaseException as exc:
        _emit(name, "failed", started, type(exc).__name__)
        raise
    else:
        _emit(name, "success", started)


def timed(name):
    def decorate(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            with stage(name):
                return function(*args, **kwargs)
        return wrapper
    return decorate
