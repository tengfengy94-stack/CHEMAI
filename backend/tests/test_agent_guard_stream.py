"""第 13 章：SSE 输出检查与红线替换。"""
import json

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

from agent_helpers import install_agents
from app.agent import FakeChatModel
from app.agent_guard import REPLACEMENTS
from exam_helpers import (
    attempt_for_paper,
    make_approved,
    paper_with,
)
from helpers import auth, login


def _parse_events(lines):
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


def _consume(client, token, message):
    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": message},
        headers=auth(token),
    ) as response:
        events = _parse_events(response.iter_lines())
    text = "".join(
        json.loads(event["data"])["delta"]
        for event in events
        if event["event"] == "text"
    )
    return events, text


@pytest.mark.parametrize(
    ("trigger", "forbidden", "replacement"),
    [
        ("[[guard:other]]", "张三", REPLACEMENTS[2]),
        ("[[guard:danger]]", "直接闻", REPLACEMENTS[3]),
        ("[[guard:insult]]", "这么简单都不会", REPLACEMENTS[4]),
    ],
)
def test_stream_replaces_red_line(
    client, make_user, trigger, forbidden, replacement
):
    make_user("s1", role="student", name="学生一")
    token = login(client, "s1")
    install_agents(client, FakeChatModel())

    events, text = _consume(client, token, trigger)

    assert forbidden not in text
    assert replacement in text
    assert sum(1 for event in events if event["event"] == "end") == 1
    assert events[-1]["event"] == "end"


def test_stream_replaces_exam_answer_when_exam_in_progress(
    client, make_user, make_class
):
    make_user("t1", role="teacher")
    class_id = make_class("一班", "t1")
    make_user("s1", role="student", name="学生一", class_id=class_id)
    teacher = login(client, "t1")
    student = login(client, "s1")

    question = make_approved(client, teacher)
    paper = paper_with(client, teacher, class_id, [question], "周测")
    attempt = attempt_for_paper(client, student, paper["id"])
    started = client.post(
        f"/api/attempts/{attempt['id']}/start", headers=auth(student)
    )
    assert started.status_code == 200, started.text

    install_agents(client, FakeChatModel())
    events, text = _consume(client, student, "[[guard:exam]]")

    assert "答案是" not in text
    assert REPLACEMENTS[1] in text
    assert sum(1 for event in events if event["event"] == "end") == 1
    assert events[-1]["event"] == "end"


def test_clean_stream_keeps_incremental_text(client, make_user):
    make_user("s1", role="student", name="学生一")
    token = login(client, "s1")
    install_agents(client, FakeChatModel())

    events, text = _consume(client, token, "你好")

    assert "我是化学助教" in text
    text_events = [event for event in events if event["event"] == "text"]
    assert len(text_events) >= 2
    assert events[-1]["event"] == "end"
    assert sum(1 for event in events if event["event"] == "end") == 1


def test_fallback_stream_replaces_red_line(client, make_user):
    make_user("s1", role="student", name="学生一")
    token = login(client, "s1")
    client.app.state.use_agent_graph = False
    client.app.state.chat_model_factory = lambda: FakeChatModel()

    events, text = _consume(client, token, "[[guard:insult]]")

    assert "这么简单都不会" not in text
    assert REPLACEMENTS[4] in text
    assert events[-1]["event"] == "end"
    assert sum(1 for event in events if event["event"] == "end") == 1


def test_history_hides_violation_after_hit(client, make_user):
    make_user("s1", role="student", name="学生一")
    token = login(client, "s1")
    install_agents(client, FakeChatModel())

    _consume(client, token, "[[guard:insult]]")
    history = client.get("/api/chat/history", headers=auth(token)).json()["data"]["items"]
    dumped = json.dumps(history, ensure_ascii=False)

    assert "这么简单都不会" not in dumped
    assert REPLACEMENTS[4] in dumped


class RecordingViolationModel(BaseChatModel):
    """第一轮输出违规，记录后续每轮模型看到的上下文。"""

    seen: list[list[str]] = Field(default_factory=list)
    calls: int = 0

    @property
    def _llm_type(self):
        return "recording-violation"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        self.seen.append([str(message.content) for message in messages])
        content = "这么简单都不会。" if self.calls == 1 else "第二次正常回答。"
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])


def test_next_turn_context_excludes_violation(client, make_user):
    make_user("s1", role="student", name="学生一")
    token = login(client, "s1")
    model = RecordingViolationModel()
    install_agents(client, model)

    _consume(client, token, "[[guard:insult]]")
    _consume(client, token, "继续")

    assert len(model.seen) >= 2
    second_turn_context = "\n".join(model.seen[-1])
    assert "这么简单都不会" not in second_turn_context


class ViolationToolModel(BaseChatModel):
    """第一轮带违规正文与工具调用，验证清洗时保留工具调用。"""

    calls: int = 0

    @property
    def _llm_type(self):
        return "violation-tool"

    def bind_tools(self, tools, **kwargs):
        return self

    def _message_for(self, messages):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(
                content="这么简单都不会。",
                tool_calls=[
                    {
                        "name": "search_questions",
                        "args": {},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            )
        return AIMessage(content="好的，我们继续。")

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(
            generations=[ChatGeneration(message=self._message_for(messages))]
        )

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        message = self._message_for(messages)
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                content=message.content, tool_calls=message.tool_calls or []
            )
        )

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        message = self._message_for(messages)
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                content=message.content, tool_calls=message.tool_calls or []
            )
        )


def test_history_clears_only_text_on_tool_call_message(client, make_user):
    make_user("s1", role="student", name="学生一")
    token = login(client, "s1")
    install_agents(client, ViolationToolModel())

    events, text = _consume(client, token, "[[guard:insult]]")
    history = client.get("/api/chat/history", headers=auth(token)).json()["data"]["items"]
    dumped = json.dumps(history, ensure_ascii=False)

    assert "这么简单都不会" not in text
    assert REPLACEMENTS[4] in text
    assert "这么简单都不会" not in dumped
    assert REPLACEMENTS[4] in dumped


class FailingAfterViolationModel(BaseChatModel):
    """先吐一段违规正文，再断流。"""

    @property
    def _llm_type(self):
        return "failing-after-violation"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise RuntimeError("上游断了")

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        yield ChatGenerationChunk(
            message=AIMessageChunk(content="这么简单都不会。")
        )
        raise RuntimeError("上游断了")

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        yield ChatGenerationChunk(
            message=AIMessageChunk(content="这么简单都不会。")
        )
        raise RuntimeError("上游断了")


def test_stream_failure_after_hit_still_sends_end(client, make_user):
    make_user("s1", role="student", name="学生一")
    token = login(client, "s1")
    install_agents(client, FailingAfterViolationModel())

    events, text = _consume(client, token, "会断")

    assert "这么简单都不会" not in text
    assert REPLACEMENTS[4] in text
    assert events[-1]["event"] == "end"
    assert sum(1 for event in events if event["event"] == "end") == 1


class RecordingFallbackModel(BaseChatModel):
    """记录 fallback 单轮路径收到的 system prompt。"""

    seen: list[str] = Field(default_factory=list)

    @property
    def _llm_type(self):
        return "recording-fallback"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen = [
            str(message.content)
            for message in messages
            if isinstance(message, SystemMessage)
        ]
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="好的。"))])


def test_fallback_system_prompt_has_red_lines(client, make_user):
    make_user("s1", role="student", name="学生一")
    token = login(client, "s1")
    model = RecordingFallbackModel()
    client.app.state.use_agent_graph = False
    client.app.state.chat_model_factory = lambda: model

    _consume(client, token, "你好")

    assert model.seen
    assert any("四条红线" in text for text in model.seen)
    assert any("现在是普通对话场景" in text for text in model.seen)
