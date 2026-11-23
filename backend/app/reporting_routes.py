"""学生报告接口：弱项前三。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import reporting
from app.auth import AccessDeniedError, get_current_user, get_session
from app.envelope import fail, ok
from app.models import User

router = APIRouter(prefix="/api")


@router.get("/reports/weak")
def student_weak_report(
    student_id: int | None = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if user.role == "student":
        if student_id is not None and student_id != user.id:
            raise AccessDeniedError("只能看自己的弱项")
        target_id = user.id
    elif user.role == "admin":
        if student_id is None:
            return fail("管理员需要指定学生", 400)
        target = session.get(User, student_id)
        if target is None or target.role != "student":
            return fail("学生不存在", 404)
        target_id = target.id
    else:
        raise AccessDeniedError("老师没有学生弱项入口")
    return ok(reporting.weak_report(session, target_id))
