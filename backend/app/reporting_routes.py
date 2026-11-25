"""学情报告接口：学生自助报告、老师班级报告与老师下钻学生报告。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import class_reporting, reporting
from app.auth import AccessDeniedError, get_current_user, get_session, require_own_class
from app.envelope import fail, ok
from app.models import Class, User
from app.routes import ClassNotFound

router = APIRouter(prefix="/api")


def _class_or_403(class_id: int, user: User, session: Session) -> Class:
    """班级存在性先查，再按「只能看自己带的班」判定。"""
    klass = session.get(Class, class_id)
    if klass is None:
        raise ClassNotFound()
    require_own_class(class_id, user, session)
    return klass


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


@router.get("/reports/me")
def my_report(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if user.role != "student":
        raise AccessDeniedError("只有学生可以查看自己的报告")
    return ok(reporting.student_report(session, user.id))


@router.get("/reports/students/{student_id}")
def student_report(
    student_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    target = session.get(User, student_id)
    if target is None or target.role != "student":
        return fail("学生不存在", 404)

    if user.role == "student":
        if target.id != user.id:
            raise AccessDeniedError("只能看自己的报告")
    elif user.role == "admin":
        pass
    elif user.role == "teacher":
        if target.class_id is None:
            raise AccessDeniedError("只能看自己带的班的学生")
        require_own_class(target.class_id, user, session)
    else:
        raise AccessDeniedError("只能看自己的报告")

    return ok(reporting.student_report(session, target.id))


@router.get("/reports/classes/{class_id}")
def class_report(
    class_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _class_or_403(class_id, user, session)
    return ok(class_reporting.class_overview(session, class_id, user))


@router.get("/reports/classes/{class_id}/exams/{paper_id}")
def class_exam_report(
    class_id: int,
    paper_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _class_or_403(class_id, user, session)
    return ok(class_reporting.exam_report(session, class_id, paper_id, user))
