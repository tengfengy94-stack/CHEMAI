"""题目的入参与出参。

字段格式不对（比如难度传了文字）由 Pydantic 拦，在 main.py 里翻成中文；
业务规则（题型、难度范围、选项、答案）在 validate_new_question 里统一检查。
"""
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictInt

from app.answers import QUESTION_TYPES, AnswerError, normalize_answer
from app.models import Question

DIFFICULTIES = (1, 2, 3)

# 字段名 → 中文，用于把 Pydantic 的格式错误翻成人话
FIELD_LABELS = {
    "stem": "题干",
    "type": "题型",
    "options": "选项",
    "answer": "标准答案",
    "explanation": "解析",
    "difficulty": "难度",
    "status": "审核状态",
    "username": "用户名",
    "password": "密码",
}


class QuestionValidationError(ValueError):
    """建题不合规，消息是给老师看的中文。"""


class LoginRequest(BaseModel):
    username: str
    password: str


class QuestionStatusUpdate(BaseModel):
    """审核动作只有两种：标待复核、通过。退回草稿不是一种动作，不在这里。"""

    status: Literal["pending", "approved"]


class QuestionCreate(BaseModel):
    # 只收这几个字段；status、created_by 等即使传了也忽略，由后端决定
    model_config = ConfigDict(extra="ignore")

    stem: str
    type: str
    options: list[str] | None = None
    answer: str
    explanation: str | None = None
    difficulty: StrictInt


def validate_new_question(body: QuestionCreate) -> dict:
    """检查规则并整理字段，返回可以直接存库的值。"""
    stem = body.stem.strip()
    if not stem:
        raise QuestionValidationError("题干不能为空")

    if body.type not in QUESTION_TYPES:
        raise QuestionValidationError("题型只能是单选、多选或填空")

    if body.difficulty not in DIFFICULTIES:
        raise QuestionValidationError("难度只能是 1、2、3")

    if body.type == "blank":
        if body.options:
            raise QuestionValidationError("填空题不能有选项")
        options = None
    else:
        options = [o.strip() for o in (body.options or [])]
        if len(options) < 2:
            raise QuestionValidationError("选择题至少要有 2 个选项")
        if any(not o for o in options):
            raise QuestionValidationError("选项不能为空")

    try:
        answer = normalize_answer(body.type, body.answer, option_count=len(options or []))
    except AnswerError as e:
        raise QuestionValidationError(str(e)) from e

    explanation = (body.explanation or "").strip() or None

    return {
        "stem": stem,
        "type": body.type,
        "options": options,
        "answer": answer,
        "explanation": explanation,
        "difficulty": body.difficulty,
    }


def _iso_utc(dt: datetime) -> str:
    # SQLite 取回来的时间不带时区，按存入时的 UTC 补上
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def question_to_dict(q: Question) -> dict:
    return {
        "id": q.id,
        "stem": q.stem,
        "type": q.type,
        "options": q.options,
        "answer": q.answer,
        "explanation": q.explanation,
        "difficulty": q.difficulty,
        "status": q.status,
        "created_by": q.created_by,
        "created_at": _iso_utc(q.created_at),
    }


def question_to_public_dict(q: Question) -> dict:
    """学生可见的题目条目：不发标准答案与解析（设计/02 §4.6——发卷时它不是给学生的）。"""
    data = question_to_dict(q)
    del data["answer"]
    del data["explanation"]
    return data
