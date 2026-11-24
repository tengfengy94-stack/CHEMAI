"""8 次模型调用上限：中文收尾必须通过 SSE 的 text 事件发给客户端。"""
import json

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from agent_helpers import install_agents
from helpers import auth, login


class LoopModel(BaseChatModel):
    calls: int = 0

    @property
    def _llm_type(self):
        return "loop"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "search_questions",
                                "args": {},
                                "id": f"call-{self.calls}",
                                "type": "tool_call",
                            }
                        ],
                    )
                )
            ]
        )


def _parse_events(lines):
    events = []
    current = {}
    for line in lines:
        if line == "":
            if current:
                events.append(current)
                current = {}
        elif line.startswith("event: "):
            current["event"] = line[len("event: "):]
        elif line.startswith("data: "):
            current["data"] = line[len("data: "):]
    if current:
        events.append(current)
    return events


def test_eight_model_calls_wrapup_is_streamed(client, make_user):
    make_user("s1", role="student", name="学生一")
    token = login(client, "s1")
    install_agents(client, LoopModel())

    with client.stream(
        "POST", "/api/chat/stream", json={"message": "循环"}, headers=auth(token)
    ) as response:
        events = _parse_events(response.iter_lines())

    text = "".join(
        json.loads(event["data"])["delta"]
        for event in events
        if event["event"] == "text"
    )
    assert "我先说到这里" in text
    assert sum(1 for event in events if event["event"] == "tool") == 8
    assert events[-1]["event"] == "end"
