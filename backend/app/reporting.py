"""学生弱项：按知识点汇总已判分考试的逐题作答和练习记录。

错误率 = 错题数 ÷ 作答数；只取作答数 ≥ 2 的前三项。
两路作答事实在这里合并，上层排序与门槛不区分来源；复习作答不进入统计。
"""
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import case, func, select, union_all
from sqlalchemy.orm import Session

from app.models import (
    AnswerItem,
    AnswerRecord,
    KnowledgePoint,
    PracticeRecord,
    QuestionKnowledgePoint,
)

MIN_ANSWERS = 2
TOP_N = 3


def _answer_facts(student_id: int):
    """统一作答事实：已判分考试的逐题作答 + 练习记录。

    列名对齐成 question_id / is_correct，后面只连接知识点一次。
    """
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


def _has_data(session: Session, student_id: int) -> bool:
    facts = _answer_facts(student_id)
    count = session.scalar(select(func.count()).select_from(facts))
    return bool(count)


def weak_report(session: Session, student_id: int) -> dict:
    facts = _answer_facts(student_id)
    wrong_count = func.sum(
        case((facts.c.is_correct.is_(False), 1), else_=0)
    ).label("wrong_count")
    rows = session.execute(
        select(
            KnowledgePoint.id,
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
