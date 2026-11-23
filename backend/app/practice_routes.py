"""自适应练习接口：出题与作答。

练习只服务学生本人；老师与管理员没有入口。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import practice
from app.auth import AccessDeniedError, get_current_user, get_session
from app.envelope import fail, ok
from app.models import User
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
