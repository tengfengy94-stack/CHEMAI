"""复习任务接口：到期列表与作答。

复习模块依赖考试数据，考试模块不 import 这里。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import review
from app.auth import AccessDeniedError, get_current_user, get_session
from app.envelope import fail, ok
from app.models import Question, User
from app.schemas import ReviewAnswerRequest

router = APIRouter(prefix="/api")

REVIEW_SCOPES = ("due", "all")
REVIEW_ANSWER_MAX_LENGTH = 500


def require_review_reader(user: User) -> None:
    """学生看自己的复习任务，管理员可读全部；老师没有入口。"""
    if user.role not in ("student", "admin"):
        raise AccessDeniedError("只有学生可以查看复习任务")


def require_review_answerer(task, user: User) -> None:
    """只有任务所属学生可以作答；管理员也不能代替。"""
    if user.role == "admin":
        raise AccessDeniedError("管理员不能代替学生作答")
    if user.role != "student":
        raise AccessDeniedError("只有学生可以作答")
    if task.student_id != user.id:
        raise AccessDeniedError("只能操作自己的复习任务")


@router.get("/review/tasks")
def list_review_tasks(
    scope: str = "due",
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    require_review_reader(user)
    if scope not in REVIEW_SCOPES:
        return fail("复习范围只能是今日到期或全部", 400)
    if page < 1 or page_size < 1:
        return fail("页码不对", 422)
    page_size = min(page_size, 100)
    student_id = user.id if user.role == "student" else None
    total = review.count_tasks(session, scope=scope, student_id=student_id)
    rows = review.list_tasks(
        session,
        scope=scope,
        student_id=student_id,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    items = [
        review.task_to_dict(task, question, student if user.role == "admin" else None)
        for task, question, student in rows
    ]
    return ok(
        {"items": items, "total": int(total), "page": page, "page_size": page_size}
    )


@router.post("/review/tasks/{task_id}/answer")
def answer_review_task(
    task_id: int,
    body: ReviewAnswerRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    task = review.get_task(session, task_id)
    require_review_answerer(task, user)
    if len(body.student_answer) > REVIEW_ANSWER_MAX_LENGTH:
        return fail("单题答案最多 500 字", 422)
    question = session.get(Question, task.question_id)
    if question is None:
        return fail("题目不存在", 404)
    try:
        result = review.answer_task(session, task, question, body.student_answer)
    except review.ReviewOutOfQueue:
        return fail("这道题已经复习出队了", 400)
    except review.ReviewConflict:
        return fail("这题刚更新过，请刷新后再试", 400)
    return ok(result)
