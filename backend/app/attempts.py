"""作答记录读取：详情、错题清单与判分租约。

路由与 Agent 工具共用；不 import 路由层，避免工具依赖 HTTP。
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import clock
from app.auth import AccessDeniedError
from app.models import (
    AnswerItem,
    AnswerRecord,
    Paper,
    PaperQuestion,
    Question,
    User,
)
from app.schemas import attempt_to_dict

GRADING_LEASE_SECONDS = 60


class AttemptNotFound(Exception):
    """作答记录不存在，main.py 统一转 404。"""


def get_attempt_record(attempt_id: int, session: Session) -> AnswerRecord:
    record = session.get(AnswerRecord, attempt_id)
    if record is None:
        raise AttemptNotFound()
    return record


def require_attempt_reader(record: AnswerRecord, user: User) -> None:
    """学生只能看自己的；管理员可读全部；老师没有这里的结果入口。"""
    if user.role == "admin":
        return
    if user.role != "student" or record.student_id != user.id:
        raise AccessDeniedError("只能看自己的作答记录")


def grading_in_progress(record: AnswerRecord) -> bool:
    if record.status != "submitted" or record.score is not None:
        return False
    started = clock.as_utc(record.grading_started_at)
    if started is None:
        return False
    return (clock.utcnow() - started).total_seconds() < GRADING_LEASE_SECONDS


def attempt_detail(session: Session, record: AnswerRecord) -> dict:
    paper = session.get(Paper, record.paper_id)
    data = attempt_to_dict(
        record, paper.title if paper else "", grading_in_progress(record)
    )
    if record.status == "pending":
        data["questions"] = []
        return data

    rows = session.execute(
        select(PaperQuestion, Question, AnswerItem)
        .join(Question, Question.id == PaperQuestion.question_id)
        .outerjoin(
            AnswerItem,
            (AnswerItem.record_id == record.id)
            & (AnswerItem.question_id == PaperQuestion.question_id),
        )
        .where(PaperQuestion.paper_id == record.paper_id)
        .order_by(PaperQuestion.position, PaperQuestion.id)
    ).all()
    questions = []
    for pq, question, item in rows:
        entry = {
            "id": question.id,
            "position": pq.position,
            "stem": question.stem,
            "type": question.type,
            "options": question.options,
        }
        if record.status in ("submitted", "graded"):
            entry["student_answer"] = item.student_answer if item else ""
        if record.status == "graded":
            entry["answer"] = question.answer
            entry["explanation"] = question.explanation
            entry["is_correct"] = bool(item.is_correct) if item else False
        questions.append(entry)
    data["questions"] = questions
    return data


def wrong_questions_query(user: User):
    """错题清单：先按学生 + 题目编号，外层只留每题最近一次答错。

    去重放在 SQL 里，管理员看全部时不会把不同学生的同一道题合并。
    """
    ranked = (
        select(
            AnswerItem.question_id.label("question_id"),
            AnswerItem.student_answer.label("student_answer"),
            AnswerItem.id.label("item_id"),
            AnswerRecord.id.label("attempt_id"),
            AnswerRecord.student_id.label("student_id"),
            AnswerRecord.submitted_at.label("submitted_at"),
            User.name.label("student_name"),
            Paper.id.label("paper_id"),
            Paper.title.label("paper_title"),
            Question.stem.label("stem"),
            Question.type.label("type"),
            Question.options.label("options"),
            Question.answer.label("answer"),
            Question.explanation.label("explanation"),
            func.row_number()
            .over(
                partition_by=[AnswerRecord.student_id, AnswerItem.question_id],
                order_by=[AnswerRecord.submitted_at.desc(), AnswerItem.id.desc()],
            )
            .label("rn"),
        )
        .join(AnswerRecord, AnswerRecord.id == AnswerItem.record_id)
        .join(User, User.id == AnswerRecord.student_id)
        .join(Paper, Paper.id == AnswerRecord.paper_id)
        .join(Question, Question.id == AnswerItem.question_id)
        .where(
            AnswerItem.is_correct.is_(False),
            AnswerRecord.status == "graded",
        )
    )
    if user.role == "student":
        ranked = ranked.where(AnswerRecord.student_id == user.id)

    ranked_subquery = ranked.subquery()
    return (
        select(ranked_subquery)
        .where(ranked_subquery.c.rn == 1)
        .order_by(ranked_subquery.c.submitted_at.desc(), ranked_subquery.c.item_id.desc())
    )
