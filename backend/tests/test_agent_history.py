"""对话存档、历史入口、老师班级校验与线程锁。"""
import asyncio
import json

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

import app.agent_routes as agent_routes
from agent_helpers import install_agents, run_agent, user_id
from app.agent import FAKE_ANSWER, FakeChatModel
from helpers import auth, login


class HistoryAwareModel(BaseChatModel):
    """记录每次模型调用看到的用户消息，用来验证第二句带上了第一句。"""

    seen: list[list[str]] = Field(default_factory=list)

    @property
    def _llm_type(self):
        return "history-aware"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(
            [
                message.content
                for message in messages
                if isinstance(message, HumanMessage) and isinstance(message.content, str)
            ]
        )
        return ChatResult(
            generations=[
                ChatGeneration(message=AIMessage(content=f"第{len(self.seen)}次回答"))
            ]
        )


def _consume(client, token, message, class_id=None, retry=False):
    payload = {"message": message}
    if class_id is not None:
        payload["class_id"] = class_id
    if retry:
        payload["retry"] = True
    with client.stream(
        "POST", "/api/chat/stream", json=payload, headers=auth(token)
    ) as response:
        return response.status_code, list(response.iter_lines())


def _history(client, token, class_id=None):
    url = "/api/chat/history"
    if class_id is not None:
        url += f"?class_id={class_id}"
    return client.get(url, headers=auth(token))


def test_history_restores_current_student_thread(client, make_user):
    make_user("s1", role="student", name="学生一")
    token = login(client, "s1")
    install_agents(client, FakeChatModel())

    status, _ = _consume(client, token, "你好")
    assert status == 200

    r = _history(client, token)
    assert r.status_code == 200, r.text
    items = r.json()["data"]["items"]
    assert items[0] == {"role": "user", "content": "你好"}
    assert items[-1]["role"] == "assistant"
    assert "化学助教" in items[-1]["content"]


def test_two_students_do_not_share_history(client, make_user):
    make_user("s1", role="student", name="学生一")
    make_user("s2", role="student", name="学生二")
    s1 = login(client, "s1")
    s2 = login(client, "s2")
    install_agents(client, FakeChatModel())

    _consume(client, s1, "你好")
    r = _history(client, s2)
    assert r.status_code == 200
    assert r.json()["data"]["items"] == []


def test_history_filters_tool_messages(client, make_user):
    make_user("s1", role="student", name="学生一")
    token = login(client, "s1")
    install_agents(client, FakeChatModel())

    _consume(client, token, "我哪块弱")
    items = _history(client, token).json()["data"]["items"]
    assert [item["role"] for item in items] == ["user", "assistant"]
    dumped = json.dumps(items, ensure_ascii=False)
    assert "weak_items" not in dumped
    assert "tool_call" not in dumped


def test_teacher_multi_class_requires_class_id(client, make_user, make_class):
    make_user("t1", role="teacher")
    first = make_class("一班", "t1")
    make_class("二班", "t1")
    token = login(client, "t1")
    install_agents(client, FakeChatModel())

    status, _ = _consume(client, token, "我们班哪块最弱")
    assert status == 422

    status, _ = _consume(client, token, "我们班哪块最弱", class_id=first)
    assert status == 200

    r = _history(client, token)
    assert r.status_code == 422
    r = _history(client, token, class_id=first)
    assert r.status_code == 200


def test_teacher_single_class_is_auto_selected(client, make_user, make_class):
    make_user("t1", role="teacher")
    make_class("一班", "t1")
    token = login(client, "t1")
    install_agents(client, FakeChatModel())

    status, _ = _consume(client, token, "我们班哪块最弱")
    assert status == 200


def test_teacher_other_class_is_rejected(client, make_user, make_class):
    make_user("t1", role="teacher")
    make_class("一班", "t1")
    make_user("t2", role="teacher")
    other = make_class("二班", "t2")
    token = login(client, "t1")
    install_agents(client, FakeChatModel())

    status, _ = _consume(client, token, "我们班哪块最弱", class_id=other)
    assert status == 403
    assert _history(client, token, class_id=other).status_code == 403


def test_thread_lock_is_per_thread(client):
    app = client.app
    first = agent_routes._thread_lock(app, "student:1")
    again = agent_routes._thread_lock(app, "student:1")
    other = agent_routes._thread_lock(app, "student:2")
    assert first is again
    assert first is not other


def test_history_filters_summarization_and_keeps_tool_call_text(client, make_user):
    make_user("s1", role="student", name="学生一")
    token = login(client, "s1")
    install_agents(client, FakeChatModel())
    agent = client.app.state.agents["student"]
    config = {"configurable": {"thread_id": f"student:{user_id(client, 's1')}"}}
    asyncio.run(
        agent.aupdate_state(
            config,
            {
                "messages": [
                    HumanMessage(
                        content="Here is a summary of the conversation to date:\n\n旧对话",
                        additional_kwargs={"lc_source": "summarization"},
                    ),
                    HumanMessage(content="问题一"),
                    AIMessage(
                        content="先说一句，再查。",
                        tool_calls=[
                            {
                                "name": "student_profile",
                                "args": {},
                                "id": "call-1",
                                "type": "tool_call",
                            }
                        ],
                    ),
                    AIMessage(content="最终回答"),
                ]
            },
        )
    )

    items = _history(client, token).json()["data"]["items"]
    assert [item["content"] for item in items] == [
        "问题一",
        "先说一句，再查。",
        "最终回答",
    ]


def test_retry_rewinds_failed_turn(client, make_user):
    make_user("s1", role="student", name="学生一")
    token = login(client, "s1")
    install_agents(client, FakeChatModel())
    agent = client.app.state.agents["student"]
    config = {"configurable": {"thread_id": f"student:{user_id(client, 's1')}"}}
    asyncio.run(
        agent.aupdate_state(
            config,
            {
                "messages": [
                    HumanMessage(content="失败的问题", id="human-1"),
                    AIMessage(content="半截回答", id="ai-1"),
                ]
            },
        )
    )

    status, lines = _consume(client, token, "失败的问题", retry=True)
    assert status == 200
    assert any("event: text" in line for line in lines)

    items = _history(client, token).json()["data"]["items"]
    assert [item["role"] for item in items] == ["user", "assistant"]
    assert items[0]["content"] == "失败的问题"
    assert items[1]["content"] == FAKE_ANSWER


def test_second_turn_receives_first_turn(client, make_user):
    make_user("s1", role="student", name="学生一")
    login(client, "s1")
    model = HistoryAwareModel()
    install_agents(client, model)

    run_agent(client, "student", "s1", "第一句", thread="memory-thread")
    run_agent(client, "student", "s1", "第二句", thread="memory-thread")

    assert model.seen[0] == ["第一句"]
    assert model.seen[1] == ["第一句", "第二句"]
