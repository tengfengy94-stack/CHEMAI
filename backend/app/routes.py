"""登录与刷新、题库接口。权限三层：get_current_user 挡匿名，查询过滤带身份条件，
归属判定走 app.auth 的 require_* 函数。
"""
import jwt
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import (
    AccessDeniedError,
    create_token,
    decode_token,
    dummy_verify,
    get_current_user,
    get_session,
    verify_password,
)
from app.envelope import fail, ok
from app.models import Class, Question, User
from app.schemas import (
    LoginRequest,
    QuestionCreate,
    QuestionValidationError,
    question_to_dict,
    question_to_public_dict,
    validate_new_question,
)

router = APIRouter(prefix="/api")

WRONG_CREDENTIALS = "用户名或密码不对"


def identity_dict(user: User, session: Session) -> dict:
    """给前端展示的身份信息；权限判断不用它，以查库的 User 为准。"""
    data = {"username": user.username, "name": user.name, "role": user.role}
    if user.role == "student" and user.class_id:
        klass = session.get(Class, user.class_id)
        data["class"] = {"id": klass.id, "name": klass.name} if klass else None
    if user.role == "teacher":
        data["classes"] = [
            {"id": c.id, "name": c.name}
            for c in session.scalars(
                select(Class).where(Class.teacher_id == user.id).order_by(Class.id)
            ).all()
        ]
    return data


@router.post("/auth/login")
def login(body: LoginRequest, session: Session = Depends(get_session)):
    user = session.scalar(select(User).where(User.username == body.username))
    if user is None:
        # 用户名不存在也对哑哈希跑一次校验，耗时与密码错误一致，不泄露账号存在性
        dummy_verify(body.password)
        return fail(WRONG_CREDENTIALS, 401)
    if not verify_password(body.password, user.password_hash):
        return fail(WRONG_CREDENTIALS, 401)
    return ok({
        "access_token": create_token(user.username, "access"),
        "refresh_token": create_token(user.username, "refresh"),
        "user": identity_dict(user, session),
    })


@router.post("/auth/refresh")
def refresh(request: Request, session: Session = Depends(get_session)):
    """拿长期凭证换新的短期凭证；短期凭证、伪造或过期的凭证一律拒绝。"""
    auth_header = request.headers.get("Authorization", "")
    scheme, _, token = auth_header.partition(" ")
    try:
        payload = decode_token(token.strip(), "refresh")
    except jwt.InvalidTokenError:
        return fail("登录已过期，请重新登录", 401)
    if scheme.lower() != "bearer":
        return fail("登录已过期，请重新登录", 401)
    username = payload.get("sub")
    user = session.scalar(select(User).where(User.username == username)) if username else None
    if user is None:
        return fail("登录已过期，请重新登录", 401)
    return ok({
        "access_token": create_token(user.username, "access"),
        "user": identity_dict(user, session),
    })


@router.get("/health")
def health():
    return ok({"status": "ok"})


@router.get("/questions")
def list_questions(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    stmt = select(Question).order_by(Question.created_at.desc(), Question.id.asc())
    # 第三层权限：查询过滤带身份条件。学生的"仅已通过"是可见性规则（设计/02 §4.2），同在过滤里
    if user.role == "teacher":
        stmt = stmt.where(Question.created_by == user.username)
    elif user.role == "student":
        stmt = stmt.where(Question.status == "approved")
    # 管理员全量，不加条件
    rows = session.scalars(stmt).all()
    # 学生条目不发标准答案与解析（设计/02 §4.6）
    if user.role == "student":
        return ok([question_to_public_dict(q) for q in rows])
    return ok([question_to_dict(q) for q in rows])


@router.post("/questions")
def create_question(
    body: QuestionCreate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if user.role not in ("teacher", "admin"):
        raise AccessDeniedError("只有老师和管理员可以建题")
    try:
        values = validate_new_question(body)
    except QuestionValidationError as e:
        return fail(str(e), 422)

    # 规则① 的赋值面：创建时归属当前用户
    question = Question(**values, status="draft", created_by=user.username)
    session.add(question)
    session.commit()
    return ok(question_to_dict(question), status_code=201)
