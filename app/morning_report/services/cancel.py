"""协作式取消：CancelToken + GenerationCancelled。

不杀线程：同步节点（LLM 调用等）在"当前节点完成、下一节点启动前"的安全检查点停止；
运行中的节点自然跑完（其结果是完整的一段，不会被半成品消费，因为后续节点不再执行）。
"""

from __future__ import annotations

import threading


class GenerationCancelled(RuntimeError):
    """用户主动停止晨报生成。节点/阶段检查点抛出，由 Runner 统一转为 cancelled 终态。"""


class CancelToken:
    def __init__(self):
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


def check_cancel(token: CancelToken | None) -> None:
    """安全检查点：已请求停止则抛 GenerationCancelled。"""

    if token is not None and token.cancelled:
        raise GenerationCancelled("用户主动停止生成")
