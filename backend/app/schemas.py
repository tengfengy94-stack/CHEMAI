"""题目的入参与出参。

字段格式不对（比如难度传了文字）由 Pydantic 拦，在 main.py 里翻成中文；
业务规则（题型、难度范围、选项、答案）在 validate_new_question 里统一检查。
"""
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.answers import QUESTION_TYPES, AnswerError, normalize_answer
from app.models import AnswerRecord, Paper, PaperQuestion, Question

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
    "title": "卷子名称",
    "question_id": "题目",
    "class_id": "班级",
    "answers": "答案",
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


class PaperCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str


class PaperQuestionAdd(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question_id: StrictInt


class PaperPublish(BaseModel):
    model_config = ConfigDict(extra="ignore")

    class_id: StrictInt


class AnswerInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question_id: StrictInt
    # 长度在路由里检查，避免和建题的标准答案共用同一条字段提示
    answer: str = ""


class AttemptSubmit(BaseModel):
    model_config = ConfigDict(extra="ignore")

    answers: list[AnswerInput] = Field(default_factory=list)


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


def _iso_utc_or_none(dt: datetime | None) -> str | None:
    return _iso_utc(dt) if dt else None


def paper_to_dict(paper: Paper, question_count: int = 0) -> dict:
    return {
        "id": paper.id,
        "title": paper.title,
        "status": paper.status,
        "created_by": paper.created_by,
        "created_at": _iso_utc(paper.created_at),
        "question_count": question_count,
    }


def paper_question_to_dict(pq: PaperQuestion, q: Question) -> dict:
    """老师组卷时看到的题目：带标准答案与解析，另加卷内顺序。"""
    data = question_to_dict(q)
    data["position"] = pq.position
    return data


def question_pool_to_dict(q: Question) -> dict:
    """组卷题目池只给挑题需要的字段。"""
    return {
        "id": q.id,
        "stem": q.stem,
        "type": q.type,
        "difficulty": q.difficulty,
    }


def wrong_question_to_dict(row) -> dict:
    """错题清单的一条：最近一次答错的学生答案 + 题目与来源（设计/02 §4.8）。"""
    return {
        "question_id": row.question_id,
        "student_id": row.student_id,
        "student_name": row.student_name,
        "stem": row.stem,
        "type": row.type,
        "options": row.options,
        "student_answer": row.student_answer,
        "answer": row.answer,
        "explanation": row.explanation,
        "source": "exam",
        "paper_id": row.paper_id,
        "paper_title": row.paper_title,
        "attempt_id": row.attempt_id,
        "last_wrong_at": _iso_utc(row.submitted_at),
    }


def attempt_to_dict(record: AnswerRecord, paper_title: str, grading_in_progress: bool) -> dict:
    return {
        "id": record.id,
        "paper_id": record.paper_id,
        "paper_title": paper_title,
        "status": record.status,
        "score": record.score,
        "grading_in_progress": grading_in_progress,
        "created_at": _iso_utc(record.created_at),
        "started_at": _iso_utc_or_none(record.started_at),
        "submitted_at": _iso_utc_or_none(record.submitted_at),
        "graded_at": _iso_utc_or_none(record.graded_at),
    }
