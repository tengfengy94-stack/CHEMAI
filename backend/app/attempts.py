"""作答记录读取：详情、错题清单与判分租约。

路由与 Agent 工具共用；不 import 路由层，避免工具依赖 HTTP。
"""
from sqlalchemy import func, literal, null, select, union_all
from sqlalchemy.orm import Session

from app import clock
from app.auth import AccessDeniedError, require_own_class
from app.models import (
    AnswerItem,
    AnswerRecord,
    Paper,
    PaperQuestion,
    PracticeRecord,
    Question,
    ReviewTask,
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


def require_attempt_reader(session, record: AnswerRecord, user: User) -> None:
    """学生看自己；老师看本班且由自己（或管理员）发布的卷子；管理员全通。"""
    if user.role == "admin":
        return
    if user.role == "student":
        if record.student_id == user.id:
            return
        raise AccessDeniedError("只能看自己的作答记录")
    if user.role != "teacher":
        raise AccessDeniedError("只能看自己的作答记录")

    paper = session.get(Paper, record.paper_id)
    if paper is None:
        raise AccessDeniedError("卷子不存在")
    creator = session.scalar(select(User).where(User.username == paper.created_by))
    if paper.created_by != user.username and (creator is None or creator.role != "admin"):
        raise AccessDeniedError("只能看自己发布的卷子的结果")
    require_own_class(record.class_id, user, session)


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
    total = len(rows)
    per_item_score = round(100.0 / total, 1) if total else 0.0
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
            entry["score"] = per_item_score if entry["is_correct"] else 0.0
        questions.append(entry)
    data["questions"] = questions
    return data


WRONG_SOURCES = ("exam", "practice", "review")


def wrong_questions_query(
    user: User,
    *,
    source: str | None = None,
    class_id: int | None = None,
    student_id: int | None = None,
    in_queue: bool | None = None,
):
    """错题清单：考试、练习、复习三路事实合并，每题只留最近一次答错。

    不单独建错题表：错题是三种作答事实的查询结果。去重按
    (student_id, question_id) 分区；同一时间戳按 exam > practice > review 取。
    """
    exam = (
        select(
            AnswerRecord.student_id.label("student_id"),
            User.name.label("student_name"),
            AnswerItem.question_id.label("question_id"),
            AnswerItem.student_answer.label("student_answer"),
            literal("exam").label("source"),
            AnswerRecord.id.label("source_ref"),
            Paper.id.label("paper_id"),
            Paper.title.label("paper_title"),
            AnswerRecord.submitted_at.label("occurred_at"),
            literal(3).label("source_rank"),
            Question.stem.label("stem"),
            Question.type.label("type"),
            Question.options.label("options"),
            Question.answer.label("answer"),
            Question.explanation.label("explanation"),
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
    practice = (
        select(
            PracticeRecord.student_id.label("student_id"),
            User.name.label("student_name"),
            PracticeRecord.question_id.label("question_id"),
            PracticeRecord.student_answer.label("student_answer"),
            literal("practice").label("source"),
            PracticeRecord.id.label("source_ref"),
            null().label("paper_id"),
            null().label("paper_title"),
            PracticeRecord.created_at.label("occurred_at"),
            literal(2).label("source_rank"),
            Question.stem.label("stem"),
            Question.type.label("type"),
            Question.options.label("options"),
            Question.answer.label("answer"),
            Question.explanation.label("explanation"),
        )
        .join(User, User.id == PracticeRecord.student_id)
        .join(Question, Question.id == PracticeRecord.question_id)
        .where(PracticeRecord.is_correct.is_(False))
    )
    review = (
        select(
            ReviewTask.student_id.label("student_id"),
            User.name.label("student_name"),
            ReviewTask.question_id.label("question_id"),
            ReviewTask.last_wrong_answer.label("student_answer"),
            literal("review").label("source"),
            ReviewTask.id.label("source_ref"),
            null().label("paper_id"),
            null().label("paper_title"),
            ReviewTask.last_wrong_at.label("occurred_at"),
            literal(1).label("source_rank"),
            Question.stem.label("stem"),
            Question.type.label("type"),
            Question.options.label("options"),
            Question.answer.label("answer"),
            Question.explanation.label("explanation"),
        )
        .join(User, User.id == ReviewTask.student_id)
        .join(Question, Question.id == ReviewTask.question_id)
        .where(ReviewTask.last_wrong_at.is_not(None))
    )

    facts = union_all(exam, practice, review).subquery("wrong_facts")
    conditions = []
    if user.role == "student":
        conditions.append(facts.c.student_id == user.id)
    else:
        if student_id is not None:
            conditions.append(facts.c.student_id == student_id)
        if class_id is not None:
            conditions.append(
                facts.c.student_id.in_(
                    select(User.id).where(User.class_id == class_id)
                )
            )
    if source is not None:
        conditions.append(facts.c.source == source)
    if in_queue is not None:
        queue_ids = select(ReviewTask.question_id).where(
            ReviewTask.student_id == user.id,
            ReviewTask.level < 5,
        )
        if in_queue:
            conditions.append(facts.c.question_id.in_(queue_ids))
        else:
            conditions.append(~facts.c.question_id.in_(queue_ids))

    ranked = (
        select(
            facts,
            func.row_number()
            .over(
                partition_by=[facts.c.student_id, facts.c.question_id],
                order_by=[
                    facts.c.occurred_at.desc(),
                    facts.c.source_rank.desc(),
                    facts.c.source_ref.desc(),
                ],
            )
            .label("rn"),
        )
        .where(*conditions)
        .subquery()
    )
    return (
        select(ranked)
        .where(ranked.c.rn == 1)
        .order_by(ranked.c.occurred_at.desc(), ranked.c.source_ref.desc())
    )
