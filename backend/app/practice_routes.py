"""自适应练习接口：出题与作答。

练习只服务学生本人；老师与管理员没有入口。
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import practice
from app.auth import AccessDeniedError, get_current_user, get_session
from app.envelope import fail, ok
from app.models import Question, User
from app.schemas import PracticeAnswerRequest

router = APIRouter(prefix="/api")


def require_student(user: User) -> None:
    if user.role != "student":
        raise AccessDeniedError("只有学生可以练习")


@router.get("/practice/next")
def next_practice_question(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    require_student(user)
    return ok(practice.next_question(session, user.id))


@router.get("/practice/plan")
def practice_plan(
    question_ids: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """对话带来的题单：按给定顺序返回已通过题，不带答案与解析。"""
    require_student(user)
    ids = []
    for raw in (question_ids or "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            value = int(raw)
        except ValueError:
            return fail("题单不合法", 422)
        if value > 0 and value not in ids:
            ids.append(value)
    ids = ids[:20]
    if not ids:
        return fail("题单不能为空", 422)

    rows = session.scalars(
        select(Question).where(
            Question.id.in_(ids),
            Question.status == "approved",
        )
    ).all()
    by_id = {question.id: question for question in rows}
    items = [
        {
            "id": question.id,
            "stem": question.stem,
            "type": question.type,
            "options": question.options,
            "difficulty": question.difficulty,
        }
        for question_id in ids
        if (question := by_id.get(question_id)) is not None
    ]
    return ok({"items": items})


@router.post("/practice/answers")
def answer_practice_question(
    body: PracticeAnswerRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    require_student(user)
    try:
        result = practice.answer_question(
            session,
            user.id,
            body.question_id,
            body.answer,
            body.difficulty,
        )
    except practice.PracticeQuestionNotFound:
        return fail("题目不存在", 404)
    except practice.PracticeAnswerTooLong:
        return fail("单题答案最多 500 字", 422)
    return ok(result)
