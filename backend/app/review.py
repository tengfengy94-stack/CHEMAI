"""复习任务：判分后入队、到期列表、作答推进与出队。

判分只通过 app.events 通知这里，题库与考试不 import 复习。
"""
from datetime import datetime, timedelta

from sqlalchemy import case, select, update
from sqlalchemy.orm import Session

from app import clock, events
from app.answers import judge_answer
from app.models import AnswerItem, Question, ReviewTask, User

LEVEL_MAX = 5
# 作答后的级别 → 下次间隔天数；5 级出队
NEXT_INTERVAL_DAYS = {0: 1, 1: 3, 2: 7, 3: 14, 4: 30}


class ReviewTaskNotFound(Exception):
    """复习任务不存在，main.py 统一转 404。"""


class ReviewOutOfQueue(Exception):
    """已经出队的任务不能再作答，路由转 400。"""


class ReviewConflict(Exception):
    """并发作答后到，路由转 400。"""


def enqueue_from_attempt(
    session: Session, record, graded_at: datetime | None = None
) -> None:
    """判分完成后把每道错题入队；同一学生同一道题只保留一条。"""
    if record.status != "graded":
        return

    moment = graded_at or record.graded_at or clock.utcnow()
    due_on = clock.business_date_of(moment) + timedelta(days=1)
    items = session.scalars(
        select(AnswerItem).where(
            AnswerItem.record_id == record.id,
            AnswerItem.is_correct.is_(False),
        )
    ).all()

    for item in items:
        task = session.scalar(
            select(ReviewTask).where(
                ReviewTask.student_id == record.student_id,
                ReviewTask.question_id == item.question_id,
            )
        )
        if task is None:
            session.add(
                ReviewTask(
                    student_id=record.student_id,
                    question_id=item.question_id,
                    level=0,
                    due_on=due_on,
                    review_count=0,
                    last_wrong_attempt_id=record.id,
                    created_at=moment,
                    updated_at=moment,
                )
            )
        elif task.last_wrong_attempt_id != record.id:
            # 新考试又错同一道题：归零重排；已出队的也重新入队。
            task.level = 0
            task.due_on = due_on
            task.last_wrong_attempt_id = record.id
            task.updated_at = moment


events.subscribe(events.ATTEMPT_GRADED, enqueue_from_attempt)


def get_task(session: Session, task_id: int) -> ReviewTask:
    task = session.get(ReviewTask, task_id)
    if task is None:
        raise ReviewTaskNotFound()
    return task


def list_tasks(
    session: Session,
    *,
    scope: str,
    student_id: int | None = None,
):
    """到期列表或全部任务；学生传自己的 student_id，管理员不传。"""
    stmt = (
        select(ReviewTask, Question, User)
        .join(Question, Question.id == ReviewTask.question_id)
        .join(User, User.id == ReviewTask.student_id)
    )
    if student_id is not None:
        stmt = stmt.where(ReviewTask.student_id == student_id)
    if scope == "due":
        day = clock.business_today()
        stmt = stmt.where(
            ReviewTask.level < LEVEL_MAX,
            ReviewTask.due_on.is_not(None),
            ReviewTask.due_on <= day,
        )
    # 已出队的任务 due_on 为空，排在最后
    stmt = stmt.order_by(
        case((ReviewTask.due_on.is_(None), 1), else_=0),
        ReviewTask.due_on,
        ReviewTask.id,
    )
    return session.execute(stmt).all()


def task_to_dict(task: ReviewTask, question: Question, student: User | None = None) -> dict:
    data = {
        "id": task.id,
        "question_id": task.question_id,
        "level": task.level,
        "in_queue": task.level < LEVEL_MAX,
        "due_on": task.due_on.isoformat() if task.due_on else None,
        "review_count": task.review_count,
        "last_answer": task.last_answer,
        "last_answered_at": clock.iso_utc(task.last_answered_at),
        "last_is_correct": task.last_is_correct,
        "question": {
            "id": question.id,
            "stem": question.stem,
            "type": question.type,
            "options": question.options,
        },
    }
    if student is not None:
        data["student_id"] = student.id
        data["student_name"] = student.name
    return data


def answer_task(
    session: Session,
    task: ReviewTask,
    question: Question,
    submitted: str,
    now: datetime | None = None,
) -> dict:
    """判一道复习题并推进任务；用 review_count 做乐观并发。"""
    if task.level >= LEVEL_MAX:
        raise ReviewOutOfQueue()

    moment = now or clock.utcnow()
    today = clock.business_today(moment)
    is_correct = judge_answer(
        question.type,
        question.answer,
        submitted,
        len(question.options or []),
    )
    previous_answer = task.last_answer
    old_count = task.review_count
    old_level = task.level

    if is_correct:
        new_level = old_level + 1
        due_on = (
            None
            if new_level >= LEVEL_MAX
            else today + timedelta(days=NEXT_INTERVAL_DAYS[new_level])
        )
    else:
        new_level = 0
        due_on = today + timedelta(days=1)

    values = {
        "level": new_level,
        "due_on": due_on,
        "review_count": ReviewTask.review_count + 1,
        "last_answer": submitted,
        "last_answered_at": moment,
        "last_is_correct": is_correct,
        "updated_at": moment,
    }
    if not is_correct:
        values["last_wrong_answer"] = submitted
        values["last_wrong_at"] = moment

    result = session.execute(
        update(ReviewTask)
        .where(
            ReviewTask.id == task.id,
            ReviewTask.review_count == old_count,
        )
        .values(**values)
    )
    if result.rowcount == 0:
        session.rollback()
        raise ReviewConflict()

    session.commit()
    session.refresh(task)

    return {
        "task_id": task.id,
        "question_id": question.id,
        "is_correct": is_correct,
        "student_answer": submitted,
        "answer": question.answer,
        "explanation": question.explanation,
        "previous_answer": previous_answer,
        "level": task.level,
        "in_queue": task.level < LEVEL_MAX,
        "due_on": task.due_on.isoformat() if task.due_on else None,
        "review_count": task.review_count,
    }
