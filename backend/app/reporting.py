"""学生弱项：按知识点汇总已判分考试的逐题作答。

错误率 = 错题数 ÷ 作答数；只取作答数 ≥ 2 的前三项。
本次数据源只有考试逐题作答；练习接入时在这里扩展"作答事实"来源。
"""
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import AnswerItem, AnswerRecord, KnowledgePoint, QuestionKnowledgePoint

MIN_ANSWERS = 2
TOP_N = 3


def _graded_answer_filters(student_id: int):
    """统计与 has_data 共用同一套“已判分、对错已写入”的过滤条件。"""
    return (
        AnswerRecord.student_id == student_id,
        AnswerRecord.status == "graded",
        AnswerItem.is_correct.is_not(None),
    )


def _has_data(session: Session, student_id: int) -> bool:
    count = session.scalar(
        select(func.count())
        .select_from(AnswerItem)
        .join(AnswerRecord, AnswerRecord.id == AnswerItem.record_id)
        .where(*_graded_answer_filters(student_id))
    )
    return bool(count)


def weak_report(session: Session, student_id: int) -> dict:
    wrong_count = func.sum(
        case((AnswerItem.is_correct.is_(False), 1), else_=0)
    ).label("wrong_count")
    rows = session.execute(
        select(
            KnowledgePoint.id,
            KnowledgePoint.name,
            func.count(AnswerItem.id).label("answered_count"),
            wrong_count,
        )
        .select_from(AnswerItem)
        .join(AnswerRecord, AnswerRecord.id == AnswerItem.record_id)
        .join(
            QuestionKnowledgePoint,
            QuestionKnowledgePoint.question_id == AnswerItem.question_id,
        )
        .join(
            KnowledgePoint,
            KnowledgePoint.id == QuestionKnowledgePoint.knowledge_point_id,
        )
        .where(*_graded_answer_filters(student_id))
        .group_by(KnowledgePoint.id, KnowledgePoint.name)
    ).all()

    candidates = []
    for point_id, name, answered_count, wrong in rows:
        if answered_count < MIN_ANSWERS:
            continue
        wrong = int(wrong or 0)
        rate = Decimal(wrong) / Decimal(answered_count)
        candidates.append(
            {
                "knowledge_point_id": point_id,
                "name": name,
                "answered_count": int(answered_count),
                "wrong_count": wrong,
                "error_rate": float(
                    (rate * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
                ),
                "_rate": rate,
            }
        )

    candidates.sort(
        key=lambda item: (
            -item["_rate"],
            -item["answered_count"],
            item["knowledge_point_id"],
        )
    )
    items = []
    for item in candidates[:TOP_N]:
        item.pop("_rate")
        items.append(item)
    return {"has_data": _has_data(session, student_id), "items": items}
