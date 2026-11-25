"""评测模式下的工具轨迹：按对话线记录工具名、参数与返回值。

只存在进程内存；浏览器收到的 `tool` 事件仍然只有名称与中文提示。
"""
import json
from threading import Lock


def _json_safe(value):
    """轨迹要经接口返回，先转成可序列化的普通结构。"""
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return str(value)


class EvalTraceStore:
    """评测轨迹存储；读写都在事件循环里，锁只防同一进程内的并发读。"""

    def __init__(self) -> None:
        self._items: dict[str, list[dict]] = {}
        self._known: set[str] = set()
        self._lock = Lock()

    def touch(self, thread_id: str) -> None:
        """记下这条对话线已经被评测请求使用过。"""
        with self._lock:
            self._known.add(thread_id)
            self._items.setdefault(thread_id, [])

    def known(self, thread_id: str) -> bool:
        with self._lock:
            return thread_id in self._known

    def start(self, thread_id: str, run_id: str, tool: str, args) -> None:
        with self._lock:
            self._known.add(thread_id)
            self._items.setdefault(thread_id, []).append(
                {
                    "run_id": run_id,
                    "tool": tool,
                    "args": _json_safe(args or {}),
                    "result": None,
                    "ok": None,
                }
            )

    def end(self, thread_id: str, run_id: str, result, ok: bool) -> None:
        with self._lock:
            entries = self._items.get(thread_id) or []
            for entry in reversed(entries):
                if entry.get("run_id") == run_id:
                    entry["result"] = _json_safe(result)
                    entry["ok"] = bool(ok)
                    return

    def get(self, thread_id: str) -> list[dict]:
        with self._lock:
            return [dict(entry) for entry in self._items.get(thread_id, [])]
