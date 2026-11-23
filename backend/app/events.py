"""进程内事件：让判分能通知复习模块，而题库与考试不 import 复习。

只做通知，不放业务规则。订阅在模块导入时注册；发布按注册顺序同步调用。
"""
from collections.abc import Callable

_handlers: dict[str, list[Callable[..., None]]] = {}

ATTEMPT_GRADED = "attempt_graded"


def subscribe(event: str, handler: Callable[..., None]) -> None:
    _handlers.setdefault(event, []).append(handler)


def publish(event: str, **kwargs) -> None:
    # 复制一份，允许处理过程中新增订阅而不影响本次分发
    for handler in list(_handlers.get(event, ())):
        handler(**kwargs)
