"""模型客户端：假模型、真模型构造、最小提示，全部不访问网络。"""
import asyncio
import logging

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage

from app import agent

MODEL_ENV = (
    "CHEMAI_FAKE_MODEL",
    "CHEMAI_MODEL_API_KEY",
    "CHEMAI_MODEL_BASE_URL",
    "CHEMAI_MODEL_NAME",
)


def _clean(monkeypatch):
    for name in MODEL_ENV:
        monkeypatch.delenv(name, raising=False)


async def _collect(iterator):
    return [chunk async for chunk in iterator]


def test_fake_model_streams_fixed_answer_without_network(monkeypatch):
    _clean(monkeypatch)
    monkeypatch.setenv("CHEMAI_FAKE_MODEL", "1")
    monkeypatch.setenv("CHEMAI_FAKE_MODEL_DELAY", "0")

    def should_not_construct(*_args, **_kwargs):
        raise AssertionError("假模型路径不应构造真模型")

    monkeypatch.setattr(agent, "ChatOpenAI", should_not_construct)

    model = agent.build_chat_model()
    assert isinstance(model, agent.FakeChatModel)
    chunks = asyncio.run(_collect(model.astream([])))
    assert len(chunks) > 1
    assert "".join(agent.chunk_text(chunk) for chunk in chunks) == agent.FAKE_ANSWER


def test_real_model_uses_configured_address_key_and_name(monkeypatch):
    _clean(monkeypatch)
    monkeypatch.setenv("CHEMAI_FAKE_MODEL", "0")
    monkeypatch.setenv("CHEMAI_MODEL_API_KEY", "secret-key")
    monkeypatch.setenv("CHEMAI_MODEL_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("CHEMAI_MODEL_NAME", "model-x")

    captured = {}

    class DummyModel:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(agent, "ChatOpenAI", DummyModel)

    model = agent.build_chat_model()
    assert isinstance(model, DummyModel)
    assert captured == {
        "model": "model-x",
        "api_key": "secret-key",
        "base_url": "https://example.test/v1",
        "streaming": True,
        "temperature": 0,
    }


def test_auto_fake_warns_once(monkeypatch, caplog):
    _clean(monkeypatch)
    monkeypatch.setenv("CHEMAI_FAKE_MODEL_DELAY", "0")
    monkeypatch.setattr(agent, "_auto_fake_warned", False)

    with caplog.at_level(logging.WARNING, logger="chemai.agent"):
        agent.build_chat_model()
        agent.build_chat_model()

    warnings = [record.message for record in caplog.records if record.levelno == logging.WARNING]
    assert sum("自动使用假模型" in message for message in warnings) == 1


def test_explicit_fake_does_not_warn(monkeypatch, caplog):
    _clean(monkeypatch)
    monkeypatch.setenv("CHEMAI_FAKE_MODEL", "1")
    monkeypatch.setenv("CHEMAI_FAKE_MODEL_DELAY", "0")
    monkeypatch.setattr(agent, "_auto_fake_warned", False)

    with caplog.at_level(logging.WARNING, logger="chemai.agent"):
        agent.build_chat_model()

    assert not any("自动使用假模型" in record.message for record in caplog.records)


def test_minimal_prompt_is_system_plus_current_user_only():
    messages = agent.build_messages("氧化还原怎么判断？")
    assert len(messages) == 2
    assert isinstance(messages[0], SystemMessage)
    assert messages[0].content == agent.SYSTEM_PROMPT
    assert isinstance(messages[1], HumanMessage)
    assert messages[1].content == "氧化还原怎么判断？"


def test_chunk_text_reads_plain_and_block_content():
    plain = AIMessageChunk(content="你好")
    blocks = AIMessageChunk(content=[{"type": "text", "text": "分"}, {"type": "text", "text": "块"}])
    assert agent.chunk_text(plain) == "你好"
    assert agent.chunk_text(blocks) == "分块"


def test_langchain_streaming_yields_text_in_order():
    """按已安装的 langchain-core 1.8.4 的 astream 接口验证增量顺序，不访问网络。"""
    model = GenericFakeChatModel(messages=iter([AIMessage(content="第一段 第二段")]))
    chunks = asyncio.run(_collect(model.astream([HumanMessage(content="继续")])))
    assert "".join(agent.chunk_text(chunk) for chunk in chunks) == "第一段 第二段"
