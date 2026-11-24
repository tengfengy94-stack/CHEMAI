"""Agent 测试辅助：装图、解析 SSE、直接跑一轮图。"""
import asyncio
import json

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select

from app.agent_context import ChatContext
from app.agent_runtime import RECURSION_LIMIT, build_agents
from app.models import AnswerRecord, User


class ToolCallModel(BaseChatModel):
    """第一轮调用指定工具，第二轮给最终回答。"""

    tool_name: str
    tool_args: dict = {}
    calls: int = 0

    @property
    def _llm_type(self):
        return "tool-call"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return ChatResult(
                generations=[
                    ChatGeneration(
                        message=AIMessage(
                            content="",
                            tool_calls=[
                                {
                                    "name": self.tool_name,
                                    "args": self.tool_args,
                                    "id": "call-1",
                                    "type": "tool_call",
                                }
                            ],
                        )
                    )
                ]
            )
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="done"))])


def install_agents(client, model):
    client.app.state.agents = build_agents(model, InMemorySaver())


def user_id(client, username):
    with client.app.state.session_factory() as session:
        return session.scalar(select(User.id).where(User.username == username))


def _exam_in_progress(client, student_id):
    with client.app.state.session_factory() as session:
        return (
            session.scalar(
                select(AnswerRecord.id)
                .where(
                    AnswerRecord.student_id == student_id,
                    AnswerRecord.status == "in_progress",
                )
                .limit(1)
            )
            is not None
        )


def run_agent(
    client,
    role,
    username,
    message,
    scene="chat",
    thread="test-thread",
    class_id=None,
):
    uid = user_id(client, username)
    context = ChatContext(
        user_id=uid,
        role=role,
        class_id=class_id,
        scene=scene,
        exam_in_progress=_exam_in_progress(client, uid) if role == "student" else False,
        session_factory=client.app.state.session_factory,
    )
    agent = client.app.state.agents[role]
    return asyncio.run(
        agent.ainvoke(
            {"messages": [HumanMessage(content=message)]},
            config={
                "configurable": {"thread_id": thread},
                "recursion_limit": RECURSION_LIMIT,
            },
            context=context,
        )
    )


def tool_outputs(result):
    """把图里的 ToolMessage 解析成 dict 列表。"""
    outputs = []
    for message in result["messages"]:
        if isinstance(message, ToolMessage):
            content = message.content
            if isinstance(content, str):
                try:
                    outputs.append(json.loads(content))
                except json.JSONDecodeError:
                    outputs.append({"raw": content})
            else:
                outputs.append({"raw": content})
    return outputs
