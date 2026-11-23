"""Agent 的模型客户端与最小系统提示。

本章只做单轮对话：没有工具、没有历史、没有中间件。真模型走 OpenAI 兼容协议，
假模型用固定中文回答分多段输出，保证无密钥、无网络也能跑通完整流程。
"""
import asyncio
import logging
import os
from typing import AsyncIterator, Protocol, Sequence

from langchain_core.messages import AIMessageChunk, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.config import fake_model_enabled, model_config, should_use_fake_model

logger = logging.getLogger("chemai.agent")

# 自动回退只在第一次发生时报一次，避免每轮对话刷日志。
_auto_fake_warned = False

# 04 §4.1 的四段提示本章只立第一段；人设、红线、输出要求留给后续章节。
SYSTEM_PROMPT = (
    "你是这门课的化学助教，只回答这门课的问题。"
    "不确定就说不确定，不要编造。"
)

FAKE_CHUNKS = (
    "我是化学助教。",
    "这一章还没有接入题库工具，",
    "所以我先只能做通用讲解。",
    "你可以问我化学概念、反应原理或解题思路；",
    "等工具接上之后，",
    "我就能查你的成绩、错题和复习安排了。",
)
FAKE_ANSWER = "".join(FAKE_CHUNKS)


class ChatModel(Protocol):
    """路由只需要一个能按消息列表流式返回分片的对象。"""

    def astream(self, messages: Sequence[BaseMessage]) -> AsyncIterator[AIMessageChunk]: ...


def fake_chunk_delay() -> float:
    """假模型段间延迟；测试可设成 0，页面默认留一点让逐字效果可见。"""
    raw = os.environ.get("CHEMAI_FAKE_MODEL_DELAY", "").strip()
    if not raw:
        return 0.02
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 0.02


class FakeChatModel:
    """不联网的假模型：固定回答、固定分段，延迟可配置。"""

    async def astream(self, messages: Sequence[BaseMessage]) -> AsyncIterator[AIMessageChunk]:
        delay = fake_chunk_delay()
        for chunk in FAKE_CHUNKS:
            if delay:
                await asyncio.sleep(delay)
            yield AIMessageChunk(content=chunk)


def chunk_text(chunk: AIMessageChunk) -> str:
    """取分片里的正文；工具参数和内部字段不属于正文，本章也不产生这些分片。"""
    text = getattr(chunk, "text", "")
    return text if isinstance(text, str) else ""


def build_messages(message: str) -> list[BaseMessage]:
    """每轮固定 system + 当前 user 两条，不拼接任何历史。"""
    return [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=message)]


def build_chat_model() -> ChatModel:
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
