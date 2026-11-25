"""Agent 图装配：按角色裁剪工具，接场景提示、摘要压缩与 8 次调用上限。"""
import asyncio
import json
import logging
import os
import re
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    SummarizationMiddleware,
)
from langchain.agents.middleware.model_call_limit import ModelCallLimitState
from langchain.agents.middleware.types import hook_config
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agent_context import ChatContext, build_system_prompt
from app.agent_tools import (
    add_review,
    assign_practice,
    class_overview,
    due_reviews,
    exam_result,
    explain_wrong_question,
    find_knowledge_point,
    knowledge_map,
    search_questions,
    student_profile,
)
from app.models import User

logger = logging.getLogger("chemai.agent")

MAX_MODEL_CALLS = 8
RECURSION_LIMIT = 100
HISTORY_KEEP = 20
HISTORY_TRIGGER = 30


def tool_timeout_seconds() -> float:
    """单个工具的最长等待；超时按“查不到”处理，避免整轮对话卡死。"""
    raw = os.environ.get("CHEMAI_TOOL_TIMEOUT", "").strip()
    if not raw:
        return 15.0
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 15.0

CHINESE_SUMMARY_PROMPT = """你是这门课的教学助理。请把下面的对话压缩成一段中文摘要，
保留学生问过的知识点、已经查到的结论、还没完成的下一步；不要编造数据。
只输出摘要正文。

<对话>
{messages}
</对话>"""

TOOL_LABELS = {
    "search_questions": "正在为你找题",
    "find_knowledge_point": "正在核对知识点名称",
    "student_profile": "正在查你的学习情况",
    "knowledge_map": "正在看知识点的上下级",
    "explain_wrong_question": "正在看这道错题",
    "due_reviews": "正在查你的复习安排",
    "assign_practice": "正在为你选题",
    "add_review": "正在把这道题加入复习",
    "exam_result": "正在查考试结果",
    "class_overview": "正在看班级概况",
}

STUDENT_TOOLS = [
    search_questions,
    find_knowledge_point,
    student_profile,
    knowledge_map,
    explain_wrong_question,
    due_reviews,
    assign_practice,
    add_review,
    exam_result,
]

TEACHER_TOOLS = [
    search_questions,
    find_knowledge_point,
    knowledge_map,
    exam_result,
    class_overview,
]


class ScenePromptMiddleware(AgentMiddleware):
    """按场景和身份替换 system message，顺序固定为四段。"""

    def _prompt(self, request):
        context = getattr(request.runtime, "context", None)
        if not isinstance(context, ChatContext):
            return None
        return build_system_prompt(context)

    def wrap_model_call(self, request, handler):
        prompt = self._prompt(request)
        if prompt is None:
            return handler(request)
        return handler(request.override(system_message=SystemMessage(content=prompt)))

    async def awrap_model_call(self, request, handler):
        prompt = self._prompt(request)
        if prompt is None:
            return await handler(request)
        return await handler(request.override(system_message=SystemMessage(content=prompt)))


class ChineseModelCallLimitMiddleware(AgentMiddleware):
    """到 8 次模型调用时用中文收尾，不把英文兜底文案发给学生。"""

    state_schema = ModelCallLimitState

    def __init__(self, run_limit: int = MAX_MODEL_CALLS) -> None:
        super().__init__()
        self.run_limit = run_limit

    @hook_config(can_jump_to=["end"])
    def before_model(self, state, runtime):
        run_count = state.get("run_model_call_count", 0)
        if run_count >= self.run_limit:
            return {
                "jump_to": "end",
                "messages": [
                    AIMessage(
                        content="我先说到这里。已经查到的信息都在上面的回答里；"
                        "你可以把问题拆小一点，我们接着看。"
                    )
                ],
            }
        return None

    def after_model(self, state, runtime):
        return {
            "thread_model_call_count": state.get("thread_model_call_count", 0) + 1,
            "run_model_call_count": state.get("run_model_call_count", 0) + 1,
        }


class ToolFailureMiddleware(AgentMiddleware):
    """工具内部异常统一转成中文失败结果，避免中断整轮对话。"""

    @staticmethod
    def _failure(request, exc):
        call = getattr(request, "tool_call", None) or {}
        logger.exception("工具执行失败：%s", call.get("name"))
        return ToolMessage(
            content=json.dumps(
                {"found": False, "message": "这一项没查到"}, ensure_ascii=False
            ),
            tool_call_id=call.get("id", ""),
            name=call.get("name", "tool"),
            status="error",
        )

    def wrap_tool_call(self, request, handler):
        try:
            return handler(request)
        except Exception as exc:  # noqa: BLE001 - 工具失败不中断对话
            return self._failure(request, exc)

    async def awrap_tool_call(self, request, handler):
        try:
            return await asyncio.wait_for(
                handler(request), timeout=tool_timeout_seconds()
            )
        except asyncio.TimeoutError:
            logger.warning("工具执行超时：%s", getattr(request, "tool_call", None))
            return self._failure(request, TimeoutError("tool timeout"))
        except Exception as exc:  # noqa: BLE001 - 工具失败不中断对话
            return self._failure(request, exc)


def _middleware(model, with_tools: bool = True) -> list[Any]:
    chain: list[Any] = [ScenePromptMiddleware()]
    if with_tools:
        chain.append(ToolFailureMiddleware())
    chain.extend(
        [
            SummarizationMiddleware(
                model=model,
                trigger=("messages", HISTORY_TRIGGER),
                keep=("messages", HISTORY_KEEP),
                summary_prompt=CHINESE_SUMMARY_PROMPT,
            ),
            ChineseModelCallLimitMiddleware(run_limit=MAX_MODEL_CALLS),
        ]
    )
    return chain


def build_agents(model, checkpointer: BaseCheckpointSaver):
    """按角色编译三张图；工具清单在编译期裁剪，模型看不到别的角色工具。"""
    common = dict(
        model=model,
        context_schema=ChatContext,
        checkpointer=checkpointer,
    )
    return {
        "student": create_agent(
            tools=STUDENT_TOOLS,
            middleware=_middleware(model),
            name="student-agent",
            **common,
        ),
        "teacher": create_agent(
            tools=TEACHER_TOOLS,
            middleware=_middleware(model),
            name="teacher-agent",
            **common,
        ),
        # 管理员不参与助教对话：保留对话入口，但不暴露任何业务工具。
        # 没有工具时不挂 ToolFailureMiddleware，避免框架仍生成 tools 节点。
        "admin": create_agent(
            tools=[],
            middleware=_middleware(model, with_tools=False),
            name="admin-agent",
            **common,
        ),
    }


_CONVERSATION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def normalize_conversation_id(value: str | None) -> str | None:
    """评测模式下的隔离后缀；只接受小写字母、数字、下划线与短横线。"""
    if value is None:
        return None
    cleaned = value.strip()
    if not _CONVERSATION_ID_RE.fullmatch(cleaned):
        return None
    return cleaned


def thread_id_for(
    user: User,
    class_id: int | None = None,
    eval_suffix: str | None = None,
) -> str:
    """线程只由服务端身份推导；老师按账号 + 班级分线。

    评测模式在身份之后追加隔离后缀，客户端无法越过当前身份。
    """
    if user.role == "teacher":
        base = f"teacher:{user.id}:class:{class_id or 0}"
    elif user.role == "admin":
        base = f"admin:{user.id}"
    else:
        base = f"student:{user.id}"
    if eval_suffix:
        base = f"{base}:eval:{eval_suffix}"
    return base


def tool_label(name: str) -> str:
    return TOOL_LABELS.get(name, "正在查资料")
