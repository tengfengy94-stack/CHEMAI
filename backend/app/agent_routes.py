"""流式对话接口：鉴权、SSE 编码、心跳与中断处理。

成功时返回 `text/event-stream`；流开始之前的失败仍然走 `fail()` 的信封。
第 12 章起走 LangGraph 图；`use_agent_graph=False` 时保留第 11 章的单轮路径。
"""
import asyncio
import json
import logging
from contextlib import aclosing, suppress

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
from pydantic import BaseModel
from sqlalchemy import select

from app.agent import ChatModel, build_messages, chunk_text
from app.agent_context import ChatContext
from app.agent_runtime import RECURSION_LIMIT, thread_id_for, tool_label
from app.auth import AccessDeniedError, get_current_user, require_own_class
from app.config import ModelConfigError
from app.envelope import fail, ok
from app.models import AnswerRecord, Class, User

router = APIRouter(prefix="/api")

logger = logging.getLogger("chemai.agent")

# 心跳间隔做成模块常量，测试可以调小；生产固定 15 秒。
HEARTBEAT_SECONDS = 15.0


class ChatRequest(BaseModel):
    message: str
    scene: str = "chat"
    class_id: int | None = None
    retry: bool = False


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
    """fallback 单轮路径：模型增量与 15 秒超时赛跑；超时就发 SSE 注释心跳。"""
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
                logger.error("对话流中断（用户 %s）：%s", username, payload, exc_info=payload)
                return
    finally:
        pump.cancel()
        with suppress(asyncio.CancelledError):
            await pump


async def _pump_agent(agent, input_messages, config, context, queue: asyncio.Queue) -> None:
    """把图事件送进队列；工具事件和正文分片在这里分流。"""
    try:
        async for event in agent.astream_events(
            input_messages,
            config=config,
            context=context,
            version="v2",
        ):
            await queue.put(("event", event))
        await queue.put(("done", None))
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        await queue.put(("error", exc))


def _tool_payload(event) -> dict:
    output = (event.get("data") or {}).get("output")
    content = getattr(output, "content", None)
    if not isinstance(content, str):
        return {}
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _plan_event(tool_name: str, parsed: dict) -> dict | None:
    """把工具结果里的题号转成前端可执行的一条轻提示。"""
    if tool_name == "assign_practice":
        ids = [
            item.get("id")
            for item in (parsed.get("questions") or [])
            if isinstance(item, dict) and item.get("id") is not None
        ]
        if ids:
            return {
                "name": "assign_practice_result",
                "label": "已为你选好题",
                "questions": ids,
            }
    if tool_name == "explain_wrong_question":
        similar = parsed.get("similar")
        question_id = similar.get("id") if isinstance(similar, dict) else None
        if question_id is not None:
            return {
                "name": "similar_question_result",
                "label": "找到一道同类题",
                "questions": [question_id],
            }
    return None


async def _rewind_failed_turn(agent, config, message: str) -> None:
    """重试前把上一轮未完成的用户消息与其后的消息一起回退，避免重复提问。

    只有最后一条用户消息与本次重试内容一致才回退；请求根本没到服务端时，
    最后一条是更早的提问，内容不一致，直接追加本次消息即可。
    """
    state = await agent.aget_state(config)
    messages = (state.values or {}).get("messages", []) if state else []
    index = next(
        (i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], HumanMessage)),
        None,
    )
    if index is None or messages[index].content != message:
        return
    removals = [
        RemoveMessage(id=item.id)
        for item in messages[index:]
        if getattr(item, "id", None)
    ]
    if removals:
        await agent.aupdate_state(config, {"messages": removals})


async def _last_ai_text(agent, config) -> str:
    """取图结束时最后一条 AI 正文；用于补发没有经过模型流的收尾消息。"""
    state = await agent.aget_state(config)
    messages = (state.values or {}).get("messages", []) if state else []
    for item in reversed(messages):
        if isinstance(item, AIMessage):
            return item.content if isinstance(item.content, str) else ""
    return ""


async def _stream_agent_events(
    agent,
    message: str,
    thread_id: str,
    context: ChatContext,
    username: str,
    retry: bool = False,
):
    """LangGraph 路径：tool 提示 + text 正文 + end；心跳与中断规则同第 11 章。"""
    queue: asyncio.Queue = asyncio.Queue()
    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": RECURSION_LIMIT,
    }
    if retry:
        try:
            await _rewind_failed_turn(agent, config, message)
        except Exception:  # noqa: BLE001 - 回退失败仍继续本轮，最多留下一条旧消息
            logger.exception("重试回退失败（用户 %s）", username)

    pump = asyncio.create_task(
        _pump_agent(
            agent,
            {"messages": [HumanMessage(content=message)]},
            config,
            context,
            queue,
        )
    )
    streamed_text = ""
    try:
        while True:
            try:
                kind, payload = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue
            if kind == "event":
                event = payload
                event_name = event.get("event")
                metadata = event.get("metadata") or {}
                if event_name == "on_tool_start":
                    name = event.get("name") or ""
                    yield sse_event(
                        "tool",
                        {"name": name, "label": tool_label(name)},
                    )
                elif event_name == "on_tool_end":
                    plan = _plan_event(event.get("name") or "", _tool_payload(event))
                    if plan is not None:
                        yield sse_event("tool", plan)
                elif event_name == "on_chat_model_stream":
                    if metadata.get("langgraph_node") != "model":
                        continue
                    chunk = (event.get("data") or {}).get("chunk")
                    text = chunk_text(chunk)
                    if text:
                        streamed_text += text
                        yield sse_event("text", {"delta": text})
            elif kind == "done":
                # 模型调用上限/收尾消息不是模型流，不会触发 on_chat_model_stream，
                # 这里从最终状态补发最后一条 AI 正文，避免客户端只看到 end。
                try:
                    final_text = await _last_ai_text(agent, config)
                except Exception:  # noqa: BLE001
                    logger.exception("读取收尾回答失败（用户 %s）", username)
                    final_text = ""
                if final_text and not streamed_text.endswith(final_text):
                    yield sse_event("text", {"delta": final_text})
                yield sse_event("end", {})
                return
            else:
                logger.error("对话流中断（用户 %s）：%s", username, payload, exc_info=payload)
                return
    finally:
        pump.cancel()
        with suppress(asyncio.CancelledError):
            await pump


async def stream_agent_events(agent, message, thread_id, context, username, lock, retry=False):
    async with lock:
        async for chunk in _stream_agent_events(
            agent, message, thread_id, context, username, retry
        ):
            yield chunk


def _thread_lock(app, thread_id: str) -> asyncio.Lock:
    locks = getattr(app.state, "thread_locks", None)
    if locks is None:
        locks = {}
        app.state.thread_locks = locks
    return locks.setdefault(thread_id, asyncio.Lock())


def _teacher_class(app, user: User, requested: int | None):
    with app.state.session_factory() as session:
        classes = session.scalars(
            select(Class).where(Class.teacher_id == user.id).order_by(Class.id)
        ).all()
        if not classes:
            return None, fail("还没有带班，暂时不能使用班级对话", 403)
        if requested is None:
            if len(classes) == 1:
                return classes[0].id, None
            return None, fail("请先选择班级", 422)
        try:
            require_own_class(requested, user, session)
        except AccessDeniedError:
            return None, fail("只能选择自己带的班", 403)
        return requested, None


def _exam_in_progress(session_factory, student_id: int) -> bool:
    with session_factory() as session:
        found = session.scalar(
            select(AnswerRecord.id)
            .where(
                AnswerRecord.student_id == student_id,
                AnswerRecord.status == "in_progress",
            )
            .limit(1)
        )
        return found is not None


def _build_context(app, user: User, scene: str, class_id: int | None) -> ChatContext:
    exam_in_progress = (
        _exam_in_progress(app.state.session_factory, user.id)
        if user.role == "student"
        else False
    )
    return ChatContext(
        user_id=user.id,
        role=user.role,
        class_id=class_id,
        scene=scene,
        exam_in_progress=exam_in_progress,
        session_factory=app.state.session_factory,
    )


@router.post("/chat/stream")
async def chat_stream(
    payload: ChatRequest,
    request: Request,
    user: User = Depends(get_current_user),
):
    message = payload.message.strip()
    if not message:
        return fail("消息不能为空", 422)
    if payload.scene not in {"practice", "wrong", "chat"}:
        return fail("场景不合法", 422)

    app = request.app
    class_id = payload.class_id
    if user.role == "student":
        if class_id is not None:
            return fail("学生不能指定班级", 422)
    elif user.role == "teacher":
        class_id, error = _teacher_class(app, user, class_id)
        if error is not None:
            return error
    else:
        if class_id is not None:
            return fail("当前身份不能指定班级", 422)
        class_id = None

    agents = getattr(app.state, "agents", None)
    if agents and getattr(app.state, "use_agent_graph", True):
        agent = agents.get(user.role) or agents["admin"]
        context = _build_context(app, user, payload.scene, class_id)
        thread_id = thread_id_for(user, class_id)
        username = user.username
        lock = _thread_lock(app, thread_id)
        return StreamingResponse(
            stream_agent_events(
                agent, message, thread_id, context, username, lock, retry=payload.retry
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    try:
        model = app.state.chat_model_factory()
    except ModelConfigError as exc:
        logger.error("模型配置错误：%s", exc)
        return fail("助教暂时不可用，请稍后重试", 500)

    username = user.username
    return StreamingResponse(
        stream_events(model, build_messages(message), username),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/chat/history")
async def chat_history(
    request: Request,
    class_id: int | None = None,
    user: User = Depends(get_current_user),
):
    app = request.app
    agents = getattr(app.state, "agents", None)
    if not agents:
        return ok({"items": []})

    if user.role == "student":
        if class_id is not None:
            return fail("学生不能指定班级", 422)
    elif user.role == "teacher":
        class_id, error = _teacher_class(app, user, class_id)
        if error is not None:
            return error
    else:
        if class_id is not None:
            return fail("当前身份不能指定班级", 422)
        class_id = None

    thread_id = thread_id_for(user, class_id)
    agent = agents.get(user.role) or agents["admin"]
    state = await agent.aget_state({"configurable": {"thread_id": thread_id}})
    messages = (state.values or {}).get("messages", []) if state else []
    items = []
    for message in messages:
        if isinstance(message, HumanMessage):
            # 压缩摘要是框架内部上下文，不是用户说过的话。
            if message.additional_kwargs.get("lc_source") == "summarization":
                continue
            text = message.content if isinstance(message.content, str) else ""
            if text:
                items.append({"role": "user", "content": text})
        elif isinstance(message, AIMessage):
            # 带 tool_calls 的消息也可能有正文；只跳过没有正文的工具调用消息。
            text = message.content if isinstance(message.content, str) else ""
            if text:
                items.append({"role": "assistant", "content": text})
    return ok({"items": items})
