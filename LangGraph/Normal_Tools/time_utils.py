"""时间相关工具：会话耗时统计与时长格式化。"""

from __future__ import annotations

import time


class SessionTimer:
    """一次会话的计时器：从创建到结束的总耗时。

    基于 time.perf_counter（单调时钟），系统调时不会影响计时结果。
    """

    def __init__(self) -> None:
        self._start = time.perf_counter()

    def elapsed(self) -> float:
        return time.perf_counter() - self._start

    def elapsed_text(self) -> str:
        return fmt_duration(self.elapsed())


def fmt_duration(seconds: float) -> str:
    """把秒数格式化为 "X小时X分钟X秒"（四舍五入到整秒）。"""

    total = int(round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}小时{minutes}分钟{secs}秒"
