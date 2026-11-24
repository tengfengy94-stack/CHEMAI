"""评测模式专用只读接口：按隔离对话线读取工具轨迹。

只在 create_app(eval_mode=True) 时挂载；生产环境这个路由不存在。
"""
from fastapi import APIRouter, Depends, Request

from app.agent_routes import resolve_class_scope
from app.agent_runtime import normalize_conversation_id, thread_id_for
from app.auth import get_current_user
from app.envelope import fail, ok
from app.models import User

router = APIRouter(prefix="/api")


@router.get("/eval/trace")
async def read_eval_trace(
    request: Request,
    conversation_id: str,
    class_id: int | None = None,
    user: User = Depends(get_current_user),
):
    app = request.app
    store = getattr(app.state, "eval_trace", None)
    if store is None:
        return fail("接口不存在", 404)

    suffix = normalize_conversation_id(conversation_id)
    if suffix is None:
        return fail("对话线编号不合法", 422)

    class_id, error = resolve_class_scope(app, user, class_id)
    if error is not None:
        return error

    thread_id = thread_id_for(user, class_id, suffix)
    if not store.known(thread_id):
        return fail("没有这条评测轨迹", 404)
    return ok({"thread_id": thread_id, "items": store.get(thread_id)})
