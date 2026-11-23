"""班级报告：按考试看提交与逐题正确率，按知识点看全班分布与学生表。

只读考试作答，按发布时的班级快照归集；练习记录没有班级快照，不进入这里。
"""
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app import clock, reporting
from app.models import (
    AnswerItem,
    AnswerRecord,
    Class,
    Paper,
    PaperQuestion,
    Question,
    User,
)


class ClassExamNotFound(Exception):
    """该班没有这次考试的作答记录，main.py 统一转 404。"""


def class_exams(session: Session, class_id: int) -> list[dict]:
    """这个班考过的卷子：按发布快照去重，发布时间取最早一条作答记录。"""
    rows = session.execute(
        select(
            Paper.id.label("paper_id"),
            Paper.title.label("paper_title"),
            func.min(AnswerRecord.created_at).label("published_at"),
            func.count(AnswerRecord.id).label("student_count"),
        )
        .join(AnswerRecord, AnswerRecord.paper_id == Paper.id)
        .where(AnswerRecord.class_id == class_id)
        .group_by(Paper.id, Paper.title)
        .order_by(func.min(AnswerRecord.created_at).desc(), Paper.id.desc())
    ).all()

    paper_ids = [row.paper_id for row in rows]
    question_counts = {}
    if paper_ids:
        question_counts = dict(
            session.execute(
                select(PaperQuestion.paper_id, func.count())
                .where(PaperQuestion.paper_id.in_(paper_ids))
                .group_by(PaperQuestion.paper_id)
            ).all()
        )
    return [
        {
            "paper_id": row.paper_id,
            "paper_title": row.paper_title,
            "published_at": clock.iso_utc(row.published_at),
            "question_count": int(question_counts.get(row.paper_id, 0)),
            "student_count": int(row.student_count),
        }
        for row in rows
    ]


def _knowledge_distribution(session: Session, class_id: int) -> list[dict]:
    stats = reporting.class_knowledge_stats(session, class_id)
    items = [
        {
            **item,
            "error_rate": reporting.error_rate(item["wrong_count"], item["answered_count"]),
        }
        for item in stats
    ]
    items.sort(
        key=lambda item: (
            -item["error_rate"],
            -item["answered_count"],
            item["knowledge_point_id"],
        )
    )
    return items


def _class_student_rows(session: Session, class_id: int, viewer: User) -> list[dict]:
    """班级学生表：历史快照里的学生 + 当前在班学生，后者可能是「未作答」。"""
    snapshot_ids = (
        select(AnswerRecord.student_id)
        .where(AnswerRecord.class_id == class_id)
        .distinct()
    )
    users = session.execute(
        select(User.id, User.name, User.class_id)
        .where(
            User.role == "student",
            or_(User.id.in_(snapshot_ids), User.class_id == class_id),
        )
        .order_by(User.name, User.id)
    ).all()
    if not users:
        return []

    ranked = (
        select(
            AnswerRecord.student_id,
            AnswerRecord.score,
            AnswerRecord.graded_at,
            func.row_number()
            .over(
                partition_by=AnswerRecord.student_id,
                order_by=(AnswerRecord.graded_at.desc(), AnswerRecord.id.desc()),
            )
            .label("rn"),
        )
        .where(
            AnswerRecord.class_id == class_id,
            AnswerRecord.status == "graded",
            AnswerRecord.graded_at.is_not(None),
        )
        .subquery()
    )
    latest = {
        row.student_id: row
        for row in session.execute(
            select(ranked.c.student_id, ranked.c.score, ranked.c.graded_at).where(
                ranked.c.rn == 1
            )
        ).all()
    }

    wrong_counts = dict(
        session.execute(
            select(
                AnswerRecord.student_id,
                func.count(func.distinct(AnswerItem.question_id)),
            )
            .join(AnswerItem, AnswerItem.record_id == AnswerRecord.id)
            .where(
                AnswerRecord.class_id == class_id,
                AnswerRecord.status == "graded",
                AnswerItem.is_correct.is_(False),
            )
            .group_by(AnswerRecord.student_id)
        ).all()
    )

    grading_pending = dict(
        session.execute(
            select(AnswerRecord.student_id, func.count())
            .where(
                AnswerRecord.class_id == class_id,
                AnswerRecord.status == "submitted",
                AnswerRecord.score.is_(None),
            )
            .group_by(AnswerRecord.student_id)
        ).all()
    )

    rows = []
    for user in users:
        latest_row = latest.get(user.id)
        is_current_member = user.class_id == class_id
        rows.append(
            {
                "student_id": user.id,
                "student_name": user.name,
                "latest_score": (
                    None if latest_row is None or latest_row.score is None
                    else float(latest_row.score)
                ),
                "latest_graded_at": (
                    None if latest_row is None
                    else clock.iso_utc(latest_row.graded_at)
                ),
                "wrong_count": int(wrong_counts.get(user.id, 0)),
                "is_current_member": is_current_member,
                "grading_pending": bool(grading_pending.get(user.id, 0)),
                # 原班报告只给仍在班的学生报告入口；转出到同一位老师别的班，
                # 也要从新班报告进，不能从历史行跳过去。
                "can_view_report": True if viewer.role == "admin" else is_current_member,
            }
        )
    return rows


def class_overview(session: Session, class_id: int, viewer: User) -> dict:
    klass = session.get(Class, class_id)
    exams = class_exams(session, class_id)
    return {
        "class": {"id": klass.id, "name": klass.name},
        "exam_count": len(exams),
        "exams": exams,
        "knowledge_points": _knowledge_distribution(session, class_id),
        "students": _class_student_rows(session, class_id, viewer),
    }


def _submission(session: Session, class_id: int, paper_id: int) -> dict:
    counts = dict(
        session.execute(
            select(AnswerRecord.status, func.count())
            .where(
                AnswerRecord.class_id == class_id,
                AnswerRecord.paper_id == paper_id,
            )
            .group_by(AnswerRecord.status)
        ).all()
    )
    if not counts:
        raise ClassExamNotFound()
    submitted = int(counts.get("submitted", 0)) + int(counts.get("graded", 0))
    return {
        "total": sum(int(value) for value in counts.values()),
        "submitted": submitted,
        "in_progress": int(counts.get("in_progress", 0)),
        "pending": int(counts.get("pending", 0)),
    }


def _question_rows(session: Session, class_id: int, paper_id: int) -> list[dict]:
    graded = (
        select(AnswerItem.question_id, AnswerItem.is_correct)
        .join(AnswerRecord, AnswerRecord.id == AnswerItem.record_id)
        .where(
            AnswerRecord.class_id == class_id,
            AnswerRecord.paper_id == paper_id,
            AnswerRecord.status == "graded",
            AnswerItem.is_correct.is_not(None),
        )
        .subquery()
    )
    rows = session.execute(
        select(
            PaperQuestion.position,
            Question.id.label("question_id"),
            Question.stem,
            Question.type,
            func.count(graded.c.is_correct).label("graded_count"),
            func.coalesce(
                func.sum(case((graded.c.is_correct.is_(True), 1), else_=0)), 0
            ).label("correct_count"),
        )
        .select_from(PaperQuestion)
        .join(Question, Question.id == PaperQuestion.question_id)
        .outerjoin(graded, graded.c.question_id == PaperQuestion.question_id)
        .where(PaperQuestion.paper_id == paper_id)
        .group_by(PaperQuestion.position, Question.id, Question.stem, Question.type)
        .order_by(PaperQuestion.position)
    ).all()

    items = []
    for row in rows:
        graded_count = int(row.graded_count)
        correct_count = int(row.correct_count or 0)
        correct_rate = None
        if graded_count:
            rate = Decimal(correct_count) / Decimal(graded_count)
            correct_rate = float(
                (rate * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
            )
        items.append(
            {
                "position": row.position,
                "question_id": row.question_id,
                "stem": row.stem,
                "type": row.type,
                "correct_count": correct_count,
                "graded_count": graded_count,
                "correct_rate": correct_rate,
            }
        )
    return items


def _unsubmitted(session: Session, class_id: int, paper_id: int) -> list[dict]:
    rows = session.execute(
        select(AnswerRecord.student_id, User.name, AnswerRecord.status)
        .join(User, User.id == AnswerRecord.student_id)
        .where(
            AnswerRecord.class_id == class_id,
            AnswerRecord.paper_id == paper_id,
            AnswerRecord.status.in_(("pending", "in_progress")),
        )
        .order_by(
            case((AnswerRecord.status == "in_progress", 0), else_=1),
            User.name,
            User.id,
        )
    ).all()
    return [
        {
            "student_id": row.student_id,
            "student_name": row.name,
            "status": row.status,
        }
        for row in rows
    ]


def exam_report(session: Session, class_id: int, paper_id: int) -> dict:
    submission = _submission(session, class_id, paper_id)
    title = session.scalar(select(Paper.title).where(Paper.id == paper_id))
    return {
        "paper_id": paper_id,
        "paper_title": title,
        "submission": submission,
        "questions": _question_rows(session, class_id, paper_id),
        "unsubmitted": _unsubmitted(session, class_id, paper_id),
    }
