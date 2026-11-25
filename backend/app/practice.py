"""自适应练习：难度重放、选题、判分与记录。

判分复用 answers.judge_answer；练习记录只追加，不写考试与复习。
选题口径见 设计/03 §4.3 与 openspec change add-adaptive-practice。
"""
import random

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock, reporting
from app.answers import judge_answer
from app.models import PracticeRecord, Question, QuestionKnowledgePoint

DIFFICULTY_MIN = 1
DIFFICULTY_MAX = 3
DIFFICULTY_START = 2
EXCLUDE_WINDOW = 20
# 同一知识点内的放宽阶梯：(是否限定当前难度, 排除窗口)
LADDER = (
    (True, 20),
    (False, 20),
    (False, 10),
    (False, 5),
    (False, 0),
)
ANSWER_MAX_LENGTH = 500


class PracticeQuestionNotFound(Exception):
    """题目不存在或不是已通过状态，路由转 404。"""


class PracticeAnswerTooLong(Exception):
    """单题答案超过 500 字，路由转 422。"""


def current_difficulty(session: Session, student_id: int) -> int:
    """从练习记录重放当前难度：初始 2，答错降一档，每连对两题升一档。

    只看对错序列，不看记录里的 difficulty；放宽难度出的题不会改变目标档。
    """
    results = session.scalars(
        select(PracticeRecord.is_correct)
        .where(PracticeRecord.student_id == student_id)
        .order_by(PracticeRecord.id)
    ).all()

    level = DIFFICULTY_START
    streak = 0
    for is_correct in results:
        if is_correct:
            streak += 1
            if streak % 2 == 0:
                level = min(DIFFICULTY_MAX, level + 1)
        else:
            streak = 0
            level = max(DIFFICULTY_MIN, level - 1)
    return level


def consecutive_wrong_count(session: Session, student_id: int) -> int:
    """从练习记录尾部数连续答错，答对一条即停止；空记录为 0。"""
    results = session.scalars(
        select(PracticeRecord.is_correct)
        .where(PracticeRecord.student_id == student_id)
        .order_by(PracticeRecord.id.desc())
    )
    count = 0
    for is_correct in results:
        if is_correct:
            break
        count += 1
    return count


def recent_question_ids(session: Session, student_id: int, limit: int = EXCLUDE_WINDOW) -> list[int]:
    """最近 limit 条练习记录里的题目 ID，按记录倒序；重复题保留重复。"""
    return list(
        session.scalars(
            select(PracticeRecord.question_id)
            .where(PracticeRecord.student_id == student_id)
            .order_by(PracticeRecord.id.desc())
            .limit(limit)
        ).all()
    )


def _approved_questions_for_point(session: Session, point_id: int) -> dict[int, Question]:
    questions = session.scalars(
        select(Question)
        .join(
            QuestionKnowledgePoint,
            QuestionKnowledgePoint.question_id == Question.id,
        )
        .where(
            QuestionKnowledgePoint.knowledge_point_id == point_id,
            Question.status == "approved",
        )
    ).all()
    return {question.id: question for question in questions}


def _all_approved_questions(session: Session) -> dict[int, Question]:
    questions = session.scalars(
        select(Question).where(Question.status == "approved")
    ).all()
    return {question.id: question for question in questions}


def _pick(candidates: list[Question]) -> Question:
    """随机取一道；测试可以替换这个函数固定选择。"""
    return random.choice(candidates)


def _choose(pool: dict[int, Question], recent_ids: list[int], level: int) -> Question | None:
    """按固定阶梯放宽：当前档/20 → 任意/20 → 任意/10 → 任意/5 → 任意/0。"""
    for exact, window in LADDER:
        excluded = set(recent_ids[:window])
        candidates = [
            question
            for question in pool.values()
            if question.id not in excluded
            and (not exact or question.difficulty == level)
        ]
        if candidates:
            return _pick(candidates)
    return None


def _question_dict(question: Question) -> dict:
    return {
        "id": question.id,
        "stem": question.stem,
        "type": question.type,
        "options": question.options,
    }


def _question_result(
    question: Question,
    *,
    level: int,
    has_weak_data: bool,
    knowledge_point: dict | None,
    reason: str | None = None,
    message: str | None = None,
) -> dict:
    return {
        "status": "question",
        "reason": reason,
        "message": message,
        "has_weak_data": has_weak_data,
        "current_difficulty": level,
        "served_difficulty": question.difficulty,
        "question": _question_dict(question),
        "knowledge_point": knowledge_point,
    }


def _empty_result(
    level: int,
    *,
    reason: str,
    message: str,
    has_weak_data: bool,
) -> dict:
    return {
        "status": "empty",
        "reason": reason,
        "message": message,
        "has_weak_data": has_weak_data,
        "current_difficulty": level,
        "served_difficulty": None,
        "question": None,
        "knowledge_point": None,
    }


def pick_questions(session: Session, student_id: int, count: int = 5) -> list[dict]:
    """按弱项排名与当前难度选一组题，供 Agent 布置练习；不写练习记录。"""
    limit = max(1, min(int(count or 5), 20))
    level = current_difficulty(session, student_id)
    recent = set(recent_question_ids(session, student_id, EXCLUDE_WINDOW))
    report = reporting.weak_report(session, student_id)

    pools: list[dict[int, Question]] = []
    if report["items"]:
        for item in report["items"]:
            pools.append(_approved_questions_for_point(session, item["knowledge_point_id"]))
    pools.append(_all_approved_questions(session))

    picked: list[Question] = []
    seen: set[int] = set(recent)
    for pool in pools:
        candidates = sorted(
            (question for question in pool.values() if question.id not in seen),
            key=lambda question: (abs(question.difficulty - level), question.id),
        )
        for question in candidates:
            if len(picked) >= limit:
                return [_question_summary(question) for question in picked]
            picked.append(question)
            seen.add(question.id)
    return [_question_summary(question) for question in picked]


def _question_summary(question: Question) -> dict:
    return {
        "id": question.id,
        "stem": question.stem,
        "type": question.type,
        "difficulty": question.difficulty,
    }


def next_question(session: Session, student_id: int) -> dict:
    """出一道理题：弱项按排名依次尝试；没有弱项时从全部已通过题里选。"""
    level = current_difficulty(session, student_id)
    recent_ids = recent_question_ids(session, student_id, EXCLUDE_WINDOW)
    report = reporting.weak_report(session, student_id)

    if report["items"]:
        for item in report["items"]:
            pool = _approved_questions_for_point(session, item["knowledge_point_id"])
            question = _choose(pool, recent_ids, level)
            if question is not None:
                return _question_result(
                    question,
                    level=level,
                    has_weak_data=True,
                    knowledge_point={
                        "id": item["knowledge_point_id"],
                        "name": item["name"],
                    },
                )
        return _empty_result(
            level,
            reason="no_question_in_point",
            message="该知识点暂无题",
            has_weak_data=True,
        )

    pool = _all_approved_questions(session)
    question = _choose(pool, recent_ids, level)
    if question is not None:
        reason = "no_data" if not report["has_data"] else "no_weak_point"
        message = (
            "先做几道题，系统才能找到你的弱项"
            if not report["has_data"]
            else "暂无可统计的弱项"
        )
        return _question_result(
            question,
            level=level,
            has_weak_data=False,
            knowledge_point=None,
            reason=reason,
            message=message,
        )
    return _empty_result(
        level,
        reason="no_approved_question",
        message="题库里还没有可练习的题",
        has_weak_data=False,
    )


def answer_question(
    session: Session,
    student_id: int,
    question_id: int,
    submitted: str,
    served_difficulty: int,
) -> dict:
    """判一道练习题，追加记录，返回反馈与调整后的下一题难度。"""
    question = session.get(Question, question_id)
    if question is None or question.status != "approved":
        raise PracticeQuestionNotFound()
    if len(submitted) > ANSWER_MAX_LENGTH:
        raise PracticeAnswerTooLong()

    moment = clock.utcnow()
    is_correct = judge_answer(
        question.type,
        question.answer,
        submitted,
        len(question.options or []),
    )
    record = PracticeRecord(
        student_id=student_id,
        question_id=question.id,
        student_answer=submitted,
        difficulty=served_difficulty,
        is_correct=is_correct,
        created_at=moment,
    )
    session.add(record)
    session.commit()
    session.refresh(record)

    return {
        "record_id": record.id,
        "question_id": question.id,
        "is_correct": is_correct,
        "student_answer": submitted,
        "answer": question.answer,
        "explanation": question.explanation,
        "served_difficulty": served_difficulty,
        "next_difficulty": current_difficulty(session, student_id),
    }
