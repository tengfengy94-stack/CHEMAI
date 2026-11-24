"""流式对话接口：鉴权、SSE、心跳、中断与图路径。"""
import json
import logging

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk

import app.agent_routes as agent_routes
from agent_helpers import install_agents
from app.agent import FAKE_ANSWER, FakeChatModel
from app.config import ModelConfigError
from helpers import auth, login


@pytest.fixture
def user(make_user):
    return make_user("s1", role="student", name="学生一")


@pytest.fixture
def token(client, user):
    return login(client, "s1")


def parse_events(lines):
    """把 SSE 行拆成事件列表；忽略注释心跳。"""
    events = []
    current = {}
    for line in lines:
        if line == "":
            if current:
                events.append(current)
                current = {}
        elif line.startswith(":"):
            continue
        elif line.startswith("event: "):
            current["event"] = line[len("event: "):]
        elif line.startswith("data: "):
            current["data"] = line[len("data: "):]
    if current:
        events.append(current)
    return events


def chat_response(client, token, message):
    return client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": message},
        headers=auth(token),
    )


class FailingChatModel(BaseChatModel):
    @property
    def _llm_type(self):
        return "failing"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise RuntimeError("上游断了")

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        yield ChatGenerationChunk(message=AIMessageChunk(content="先到的一段"))
        raise RuntimeError("上游断了")

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        yield ChatGenerationChunk(message=AIMessageChunk(content="先到的一段"))
        raise RuntimeError("上游断了")


def test_chat_requires_login(client):
    r = client.post("/api/chat/stream", json={"message": "你好"})
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["success"] is False
    assert "text/event-stream" not in r.headers["content-type"]


def test_empty_and_missing_message_are_json_envelopes(client, token):
    empty = client.post("/api/chat/stream", json={"message": "   "}, headers=auth(token))
    assert empty.status_code == 422
    assert empty.headers["content-type"].startswith("application/json")
    assert empty.json()["success"] is False
    assert "不能为空" in empty.json()["error"]

    missing = client.post("/api/chat/stream", json={}, headers=auth(token))
    assert missing.status_code == 422
    assert missing.json()["success"] is False
    assert "消息" in missing.json()["error"]


def test_invalid_scene_and_student_class_are_rejected(client, token):
    bad_scene = client.post(
        "/api/chat/stream",
        json={"message": "你好", "scene": "other"},
        headers=auth(token),
    )
    assert bad_scene.status_code == 422
    assert bad_scene.json()["success"] is False

    bad_class = client.post(
        "/api/chat/stream",
        json={"message": "你好", "class_id": 1},
        headers=auth(token),
    )
    assert bad_class.status_code == 422
    assert bad_class.json()["success"] is False


def test_model_config_error_is_generic_and_logged(client, token, caplog):
    def failing_factory():
        raise ModelConfigError("缺少 CHEMAI_MODEL_BASE_URL")

    client.app.state.chat_model_factory = failing_factory
    client.app.state.use_agent_graph = False

    with caplog.at_level(logging.ERROR, logger="chemai.agent"):
        r = client.post("/api/chat/stream", json={"message": "你好"}, headers=auth(token))

    assert r.status_code == 500
    assert r.headers["content-type"].startswith("application/json")
    assert r.json() == {
        "success": False,
        "data": None,
        "error": "助教暂时不可用，请稍后重试",
    }
    assert any("CHEMAI_MODEL_BASE_URL" in record.message for record in caplog.records)


def test_stream_headers_events_and_fake_answer(client, token, monkeypatch):
    monkeypatch.setenv("CHEMAI_FAKE_MODEL_DELAY", "0")
    install_agents(client, FakeChatModel())

    with chat_response(client, token, "你好") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        assert r.headers["cache-control"] == "no-cache, no-transform"
        assert r.headers["x-accel-buffering"] == "no"
        assert "content-length" not in r.headers
        events = parse_events(r.iter_lines())

    assert [e["event"] for e in events] == ["text"] * (len(events) - 1) + ["end"]
    assert sum(1 for e in events if e["event"] == "end") == 1
    assert all(e["event"] != "tool" for e in events)
    text = "".join(json.loads(e["data"])["delta"] for e in events if e["event"] == "text")
    assert text == FAKE_ANSWER


def test_heartbeat_is_comment_and_does_not_add_content(client, token, monkeypatch):
    monkeypatch.setattr(agent_routes, "HEARTBEAT_SECONDS", 0.02)
    monkeypatch.setenv("CHEMAI_FAKE_MODEL_DELAY", "0.06")
    install_agents(client, FakeChatModel())

    with chat_response(client, token, "慢一点") as r:
        raw_lines = list(r.iter_lines())

    pings = [line for line in raw_lines if line.startswith(": ping")]
    assert pings
    events = parse_events(raw_lines)
    assert [e["event"] for e in events] == ["text"] * (len(events) - 1) + ["end"]
    assert pings


def test_midstream_failure_closes_without_end(client, token):
    install_agents(client, FailingChatModel())

    with chat_response(client, token, "会断") as r:
        assert r.status_code == 200
        events = parse_events(r.iter_lines())

    assert [e["event"] for e in events] == ["text"]
    text = "".join(json.loads(e["data"])["delta"] for e in events)
    assert text == "先到的一段"


def test_stream_completes_after_request_session_is_cleaned(client, token, monkeypatch):
    """生成器不碰请求级 ORM；慢流跑完不应出现 DetachedInstanceError。"""
    monkeypatch.setenv("CHEMAI_FAKE_MODEL_DELAY", "0.01")
    install_agents(client, FakeChatModel())

    with chat_response(client, token, "慢流") as r:
        events = parse_events(r.iter_lines())

    assert events[-1]["event"] == "end"
    assert any(event["event"] == "text" for event in events)
