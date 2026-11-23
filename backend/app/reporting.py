"""学情报告：弱项、掌握度、最近五次分数与待复习数。

作答事实 = 已判分考试的逐题作答 UNION ALL 练习记录；复习作答、未判分记录不计。
错误率 = 错题数 ÷ 作答数；弱项只取作答数 ≥ 2 且错误率 > 0 的前三。
掌握度 = 达标知识点的平均正确率 × 100，知识点之间等权。
班级知识点分布只读考试作答，按发布时的班级快照归集。
"""
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import case, func, select, union_all
from sqlalchemy.orm import Session

from app import clock, review
from app.models import (
    AnswerItem,
    AnswerRecord,
    KnowledgePoint,
    Paper,
    PracticeRecord,
    QuestionKnowledgePoint,
)

MIN_ANSWERS = 2
TOP_N = 3


def _student_answer_facts(student_id: int):
    """统一作答事实：已判分考试的逐题作答 + 练习记录。"""
    exam = (
        select(
            AnswerItem.question_id.label("question_id"),
            AnswerItem.is_correct.label("is_correct"),
        )
        .join(AnswerRecord, AnswerRecord.id == AnswerItem.record_id)
        .where(
            AnswerRecord.student_id == student_id,
            AnswerRecord.status == "graded",
            AnswerItem.is_correct.is_not(None),
        )
    )
    practice = select(
        PracticeRecord.question_id.label("question_id"),
        PracticeRecord.is_correct.label("is_correct"),
    ).where(PracticeRecord.student_id == student_id)
    return union_all(exam, practice).subquery("answer_facts")


def _class_exam_facts(class_id: int):
    """班级版作答事实：只含该班发布快照下已判分考试的逐题作答。"""
    return (
        select(
            AnswerItem.question_id.label("question_id"),
            AnswerItem.is_correct.label("is_correct"),
        )
        .join(AnswerRecord, AnswerRecord.id == AnswerItem.record_id)
        .where(
            AnswerRecord.class_id == class_id,
            AnswerRecord.status == "graded",
            AnswerItem.is_correct.is_not(None),
        )
        .subquery("answer_facts")
    )


def _knowledge_rows(session: Session, facts):
    wrong_count = func.sum(
        case((facts.c.is_correct.is_(False), 1), else_=0)
    ).label("wrong_count")
    return session.execute(
        select(
            KnowledgePoint.id.label("knowledge_point_id"),
            KnowledgePoint.name,
            func.count().label("answered_count"),
            wrong_count,
        )
        .select_from(facts)
        .join(
            QuestionKnowledgePoint,
            QuestionKnowledgePoint.question_id == facts.c.question_id,
        )
        .join(
            KnowledgePoint,
            KnowledgePoint.id == QuestionKnowledgePoint.knowledge_point_id,
        )
        .group_by(KnowledgePoint.id, KnowledgePoint.name)
        .order_by(KnowledgePoint.id)
    ).all()


def _stats_from_rows(rows) -> list[dict]:
    return [
        {
            "knowledge_point_id": row.knowledge_point_id,
            "name": row.name,
            "answered_count": int(row.answered_count),
            "wrong_count": int(row.wrong_count or 0),
        }
        for row in rows
    ]


def knowledge_stats(session: Session, student_id: int) -> list[dict]:
    """学生每个知识点的作答数与错题数，考试与练习合并。"""
    return _stats_from_rows(_knowledge_rows(session, _student_answer_facts(student_id)))


def class_knowledge_stats(session: Session, class_id: int) -> list[dict]:
    """一个班所有学生已判分考试的逐题作答，按知识点合并。"""
    return _stats_from_rows(_knowledge_rows(session, _class_exam_facts(class_id)))


def _rate(wrong_count: int, answered_count: int) -> Decimal:
    return Decimal(wrong_count) / Decimal(answered_count)


def _percent(rate: Decimal) -> float:
    return float((rate * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def error_rate(wrong_count: int, answered_count: int) -> float:
    return _percent(_rate(wrong_count, answered_count))


def weak_items(stats: list[dict]) -> list[dict]:
    """弱项前三：达到样本门槛且错误率大于 0。"""
    candidates = [
        {**item, "_rate": _rate(item["wrong_count"], item["answered_count"])}
        for item in stats
        if item["answered_count"] >= MIN_ANSWERS and item["wrong_count"] > 0
    ]
    candidates.sort(
        key=lambda item: (
            -item["_rate"],
            -item["answered_count"],
            item["knowledge_point_id"],
        )
    )
    return [
        {
            "knowledge_point_id": item["knowledge_point_id"],
            "name": item["name"],
            "answered_count": item["answered_count"],
            "wrong_count": item["wrong_count"],
            "error_rate": _percent(item["_rate"]),
        }
        for item in candidates[:TOP_N]
    ]


def mastery_value(stats: list[dict]) -> dict:
    """掌握度：达标知识点的平均正确率 ×100；没有达标知识点时带无数据标记。"""
    eligible = [item for item in stats if item["answered_count"] >= MIN_ANSWERS]
    if not eligible:
        return {"value": 0.0, "has_data": False}
    accuracy_sum = sum(
        Decimal(item["answered_count"] - item["wrong_count"]) / Decimal(item["answered_count"])
        for item in eligible
    )
    average = accuracy_sum / Decimal(len(eligible))
    return {"value": _percent(average), "has_data": True}


def _has_data(session: Session, student_id: int) -> bool:
    facts = _student_answer_facts(student_id)
    count = session.scalar(select(func.count()).select_from(facts))
    return bool(count)


def recent_scores(session: Session, student_id: int) -> list[dict]:
    """最近五次已判分考试，按判分时间正序返回。"""
    rows = session.execute(
        select(
            AnswerRecord.paper_id,
            Paper.title,
            AnswerRecord.score,
            AnswerRecord.graded_at,
        )
        .join(Paper, Paper.id == AnswerRecord.paper_id)
        .where(
            AnswerRecord.student_id == student_id,
            AnswerRecord.status == "graded",
            AnswerRecord.graded_at.is_not(None),
        )
        .order_by(AnswerRecord.graded_at.desc(), AnswerRecord.id.desc())
        .limit(5)
    ).all()
    return [
        {
            "paper_id": row.paper_id,
            "paper_title": row.title,
            "score": None if row.score is None else float(row.score),
            "graded_at": clock.iso_utc(row.graded_at),
        }
        for row in reversed(rows)
    ]


def weak_report(session: Session, student_id: int) -> dict:
    stats = knowledge_stats(session, student_id)
    return {"has_data": _has_data(session, student_id), "items": weak_items(stats)}


def student_report(session: Session, student_id: int) -> dict:
    """学生报告：弱项、掌握度、最近五次分数、待复习数一次算完。"""
    stats = knowledge_stats(session, student_id)
    return {
        "has_data": _has_data(session, student_id),
        "items": weak_items(stats),
        "mastery": mastery_value(stats),
        "recent_scores": recent_scores(session, student_id),
        "review_due_count": review.due_task_count(session, student_id),
    }
