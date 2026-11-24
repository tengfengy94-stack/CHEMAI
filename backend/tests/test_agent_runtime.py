"""Agent 图装配：场景提示、20/30 压缩、8 次调用上限与角色工具清单。"""
import asyncio

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from app.agent import FakeChatModel
from app.agent_context import ChatContext, build_system_prompt
from app.agent_runtime import (
    RECURSION_LIMIT,
    STUDENT_TOOLS,
    TEACHER_TOOLS,
    build_agents,
    thread_id_for,
)
from app.models import User


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


class DummySession:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, *args, **kwargs):
        return None

    def scalar(self, *args, **kwargs):
        return None

    def scalars(self, *args, **kwargs):
        class Rows:
            def all(self):
                return []

        return Rows()

    def execute(self, *args, **kwargs):
        class Result:
            def mappings(self):
                class Mappings:
                    def all(self):
                        return []

                return Mappings()

        return Result()


def _context(role="student", scene="chat", exam=False):
    return ChatContext(
        user_id=1,
        role=role,
        class_id=None,
        scene=scene,
        exam_in_progress=exam,
        session_factory=DummySession,
    )


def test_scene_prompt_order_and_exam_rule():
    practice = build_system_prompt(_context(scene="practice"))
    wrong = build_system_prompt(_context(scene="wrong"))
    chat = build_system_prompt(_context(scene="chat"))
    teacher = build_system_prompt(_context(role="teacher"))
    exam = build_system_prompt(_context(exam=True))

    for prompt in (practice, wrong, chat):
        assert prompt.index("你是这门课的化学助教") < prompt.index("现在是")
        assert prompt.index("现在是") < prompt.index("四条红线")
        assert prompt.index("四条红线") < prompt.index("回答要求")
    assert "引导" in practice and "错因" in wrong
    assert "通用解释" in chat
    assert "只能查自己的数据" in chat
    assert "先调用工具" in chat
    assert "只能查自己的数据" not in teacher
    assert "老师" in teacher and "不出现鼓励" in teacher
    assert "作答中的考试" in exam


def test_student_and_teacher_tool_lists():
    student = {tool.name for tool in STUDENT_TOOLS}
    teacher = {tool.name for tool in TEACHER_TOOLS}
    assert student == {
        "search_questions",
        "find_knowledge_point",
        "student_profile",
        "knowledge_map",
        "explain_wrong_question",
        "due_reviews",
        "assign_practice",
        "add_review",
        "exam_result",
    }
    assert teacher == {
        "search_questions",
        "find_knowledge_point",
        "knowledge_map",
        "exam_result",
        "class_overview",
    }
    assert "student_profile" not in teacher


def test_admin_agent_has_no_tools():
    agents = build_agents(FakeChatModel(), InMemorySaver())
    assert "tools" not in agents["admin"].get_graph().nodes
    assert "tools" in agents["student"].get_graph().nodes
    assert "tools" in agents["teacher"].get_graph().nodes


def test_thread_ids():
    student = User(username="s1", name="学生", role="student", password_hash="x")
    teacher = User(username="t1", name="老师", role="teacher", password_hash="x")
    student.id = 7
    teacher.id = 8
    assert thread_id_for(student) == "student:7"
    assert thread_id_for(teacher, 3) == "teacher:8:class:3"
    assert thread_id_for(teacher, None) == "teacher:8:class:0"


def test_summarization_keeps_last_twenty():
    async def run():
        agents = build_agents(FakeChatModel(), InMemorySaver())
        agent = agents["student"]
        config = {
            "configurable": {"thread_id": "summary"},
            "recursion_limit": RECURSION_LIMIT,
        }
        history = []
        for index in range(15):
            history.append(HumanMessage(content=f"问题{index}"))
            history.append(AIMessage(content=f"回答{index}"))
        await agent.aupdate_state(config, {"messages": history})
        await agent.ainvoke(
            {"messages": [HumanMessage(content="继续")]},
            config=config,
            context=_context(),
        )
        state = await agent.aget_state(config)
        messages = state.values["messages"]
        assert len(messages) <= 22
        assert "summary" in str(messages[0].content).lower()

    asyncio.run(run())


def test_under_thirty_does_not_compress():
    async def run():
        agents = build_agents(FakeChatModel(), InMemorySaver())
        agent = agents["student"]
        config = {
            "configurable": {"thread_id": "no-summary"},
            "recursion_limit": RECURSION_LIMIT,
        }
        history = []
        for index in range(14):
            history.append(HumanMessage(content=f"问题{index}"))
            history.append(AIMessage(content=f"回答{index}"))
        await agent.aupdate_state(config, {"messages": history})
        await agent.ainvoke(
            {"messages": [HumanMessage(content="继续")]},
            config=config,
            context=_context(),
        )
        state = await agent.aget_state(config)
        assert state.values["messages"][0].content == "问题0"

    asyncio.run(run())


def test_eight_model_calls_then_chinese_wrapup():
    async def run():
        model = LoopModel()
        agents = build_agents(model, InMemorySaver())
        config = {
            "configurable": {"thread_id": "limit"},
            "recursion_limit": RECURSION_LIMIT,
        }
        result = await agents["student"].ainvoke(
            {"messages": [HumanMessage(content="循环")]},
            config=config,
            context=_context(),
        )
        assert model.calls == 8
        assert "我先说到这里" in result["messages"][-1].content

    asyncio.run(run())
