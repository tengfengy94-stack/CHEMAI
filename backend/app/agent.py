"""Agent 的模型客户端与最小系统提示。

真模型走 OpenAI 兼容协议；假模型用固定中文回答，并按关键词脚本化调用工具，
保证无密钥、无网络也能跑通完整的工具流程。
"""
import asyncio
import logging
import os
from typing import AsyncIterator, Iterator, Protocol, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI

from app.config import fake_model_enabled, model_config, should_use_fake_model

logger = logging.getLogger("chemai.agent")

# 自动回退只在第一次发生时报一次，避免每轮对话刷日志。
_auto_fake_warned = False

# 04 §4.1 的四段提示由 agent_runtime 按场景拼；这里只保留 fallback 单轮提示。
SYSTEM_PROMPT = (
    "你是这门课的化学助教，只回答这门课的问题。"
    "不确定就说不确定，不要编造。"
)

FAKE_CHUNKS = (
    "我是化学助教。",
    "这个问题我先按通用化学知识解释；",
    "如果你要查自己的成绩、错题或复习安排，",
    "直接问我就行。",
)
FAKE_ANSWER = "".join(FAKE_CHUNKS)

TOOL_FINAL_CHUNKS = (
    "我查到了结果，",
    "已经按你的情况",
    "整理好了。",
)
TOOL_FINAL_ANSWER = "".join(TOOL_FINAL_CHUNKS)


def fake_chunk_delay() -> float:
    """假模型段间延迟；测试可设成 0，页面默认留一点让逐字效果可见。"""
    raw = os.environ.get("CHEMAI_FAKE_MODEL_DELAY", "").strip()
    if not raw:
        return 0.02
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 0.02


class ChatModel(Protocol):
    """fallback 路由只需要一个能按消息列表流式返回分片的对象。"""

    def astream(self, messages: Sequence[BaseMessage]) -> AsyncIterator[AIMessageChunk]: ...


def _pick_tool(message: str, available: set[str]):
    """按关键词挑一个可用工具；没有命中就不调用。"""
    text = message or ""
    if ("弱项" in text or "哪块弱" in text or "学得怎么样" in text or "还有多少" in text) and "student_profile" in available:
        return "student_profile", {}
    if ("错题" in text or "为什么错" in text or "选 A" in text) and "explain_wrong_question" in available:
        return "explain_wrong_question", {}
    if ("复习" in text or "到期" in text) and "due_reviews" in available:
        return "due_reviews", {}
    if ("出几道" in text or "布置" in text or "想练" in text) and "assign_practice" in available:
        return "assign_practice", {}
    if ("上次考" in text or "考了多少" in text or "考试结果" in text or "考试成绩" in text) and "exam_result" in available:
        args = {}
        if "查一下" in text:
            name = text.split("查一下", 1)[1].split("的")[0].strip()
            if name and len(name) <= 20:
                args = {"student_name": name}
        return "exam_result", args
    if ("我们班" in text or "班级" in text) and "class_overview" in available:
        return "class_overview", {}
    if ("前置" in text or "属于哪" in text or "知识地图" in text) and "knowledge_map" in available:
        return "knowledge_map", {"point_name": "氧化还原"}
    if "知识点" in text and "find_knowledge_point" in available:
        return "find_knowledge_point", {"query": "氧化还原"}
    if ("搜题" in text or "找题" in text or "有没有题" in text) and "search_questions" in available:
        return "search_questions", {}
    return None, {}


class FakeChatModel(BaseChatModel):
    """不联网的假模型：固定回答、固定分段，能按关键词发工具调用。"""

    tool_names: tuple[str, ...] = ()

    @property
    def _llm_type(self) -> str:
        return "chemai-fake"

    def bind_tools(self, tools, **kwargs):
        return self.model_copy(update={"tool_names": tuple(tool.name for tool in tools)})

    def _next_message(self, messages: Sequence[BaseMessage]) -> AIMessage:
        last = messages[-1] if messages else None
        if isinstance(last, ToolMessage):
            return AIMessage(content=TOOL_FINAL_ANSWER)
        if isinstance(last, HumanMessage):
            text = str(last.content)
            available = set(self.tool_names)
            if (
                "class_overview" not in available
                and ("我们班" in text or "班级" in text)
                and any(
                    word in text
                    for word in ("弱", "概况", "排名", "考得怎么样", "报告")
                )
            ):
                return AIMessage(
                    content="班级概况我查不了。你自己的弱项，我可以现在给你看。"
                )
            name, args = _pick_tool(text, available)
            if name:
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": name,
                            "args": args,
                            "id": f"fake-call-{name}",
                            "type": "tool_call",
                        }
                    ],
                )
        return AIMessage(content=FAKE_ANSWER)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager=None,
        **kwargs,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next_message(messages))])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager=None,
        **kwargs,
    ) -> Iterator[ChatGenerationChunk]:
        message = self._next_message(messages)
        delay = fake_chunk_delay()
        if message.tool_calls:
            yield ChatGenerationChunk(
                message=AIMessageChunk(content="", tool_calls=message.tool_calls)
            )
            return
        if message.content == TOOL_FINAL_ANSWER:
            for chunk in TOOL_FINAL_CHUNKS:
                if delay:
                    import time

                    time.sleep(delay)
                yield ChatGenerationChunk(message=AIMessageChunk(content=chunk))
            return
        if message.content != FAKE_ANSWER:
            yield ChatGenerationChunk(message=AIMessageChunk(content=message.content))
            return
        for chunk in FAKE_CHUNKS:
            if delay:
                import time

                time.sleep(delay)
            yield ChatGenerationChunk(message=AIMessageChunk(content=chunk))

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager=None,
        **kwargs,
    ) -> AsyncIterator[ChatGenerationChunk]:
        message = self._next_message(messages)
        delay = fake_chunk_delay()
        if message.tool_calls:
            yield ChatGenerationChunk(
                message=AIMessageChunk(content="", tool_calls=message.tool_calls)
            )
            return
        if message.content == TOOL_FINAL_ANSWER:
            for chunk in TOOL_FINAL_CHUNKS:
                if delay:
                    await asyncio.sleep(delay)
                yield ChatGenerationChunk(message=AIMessageChunk(content=chunk))
            return
        if message.content != FAKE_ANSWER:
            yield ChatGenerationChunk(message=AIMessageChunk(content=message.content))
            return
        for chunk in FAKE_CHUNKS:
            if delay:
                await asyncio.sleep(delay)
            yield ChatGenerationChunk(message=AIMessageChunk(content=chunk))


def chunk_text(chunk: AIMessageChunk) -> str:
    """取分片里的正文；工具参数和内部字段不属于正文。"""
    text = getattr(chunk, "text", "")
    return text if isinstance(text, str) else ""


def build_messages(message: str) -> list[BaseMessage]:
    """fallback 单轮路径：system + 当前 user 两条。"""
    return [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=message)]


def build_chat_model() -> BaseChatModel:
    """按配置选择真/假模型；配置不完整时抛 ModelConfigError，由路由转成 JSON 信封。"""
    global _auto_fake_warned
    if should_use_fake_model():
        if not fake_model_enabled() and not _auto_fake_warned:
            _auto_fake_warned = True
            logger.warning(
                "未配置 CHEMAI_MODEL_API_KEY，自动使用假模型；配置密钥后请重启服务"
            )
        return FakeChatModel()
    cfg = model_config()
    return ChatOpenAI(
        model=cfg.model_name,
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        streaming=True,
        temperature=0,
    )
