"""流式对话接口：鉴权、SSE 编码、心跳与中断处理。

这个接口是统一 JSON 信封的唯一例外：成功时返回 `text/event-stream`；
流开始之前的失败仍然走 `fail()` 的信封。
"""
import asyncio
import json
import logging
from contextlib import aclosing, suppress

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agent import ChatModel, build_messages, chunk_text
from app.auth import get_current_user
from app.config import ModelConfigError
from app.envelope import fail
from app.models import User

router = APIRouter(prefix="/api")

logger = logging.getLogger("chemai.agent")

# 心跳间隔做成模块常量，测试可以调小；生产固定 15 秒。
HEARTBEAT_SECONDS = 15.0


class ChatRequest(BaseModel):
    message: str


def sse_event(event: str, data: dict) -> str:
    """SSE 帧；data 用 JSON，正文里的换行不会破坏分帧。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _pump(stream, queue: asyncio.Queue) -> None:
    """把模型增量送进队列；模型异常也变成一条队列消息，不抛给响应层。"""
    try:
        async with aclosing(stream) as chunks:
            async for chunk in chunks:
                await queue.put(("chunk", chunk))
        await queue.put(("done", None))
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - 上游异常一律转成流中断
        await queue.put(("error", exc))


async def stream_events(model: ChatModel, messages, username: str):
    """模型增量与 15 秒超时赛跑；超时就发 SSE 注释心跳。"""
    queue: asyncio.Queue = asyncio.Queue()
    pump = asyncio.create_task(_pump(model.astream(messages), queue))
    try:
        while True:
            try:
                kind, payload = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue
            if kind == "chunk":
                text = chunk_text(payload)
                if text:
                    yield sse_event("text", {"delta": text})
            elif kind == "done":
                yield sse_event("end", {})
                return
            else:
                # 响应已经开始，不能再换成 JSON 信封；记日志、关流、不发 end。
                logger.error("对话流中断（用户 %s）：%s", username, payload, exc_info=payload)
                return
    finally:
        pump.cancel()
        with suppress(asyncio.CancelledError):
            await pump


@router.post("/chat/stream")
async def chat_stream(
    payload: ChatRequest,
    request: Request,
    user: User = Depends(get_current_user),
):
    message = payload.message.strip()
    if not message:
        return fail("消息不能为空", 422)

    try:
        model = request.app.state.chat_model_factory()
    except ModelConfigError as exc:
        # 具体缺哪个变量只进日志，不透给学生；页面统一显示“助教暂时不可用”。
        logger.error("模型配置错误：%s", exc)
        return fail("助教暂时不可用，请稍后重试", 500)

    # 流式生成器可能在请求级会话清理之后才继续执行；这里只留普通字符串。
    username = user.username
    return StreamingResponse(
        stream_events(model, build_messages(message), username),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
