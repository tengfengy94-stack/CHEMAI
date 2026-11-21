"""登录与刷新、题库接口。权限三层：get_current_user 挡匿名，查询过滤带身份条件，
归属判定走 app.auth 的 require_* 函数。
"""
import jwt
from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import (
    AccessDeniedError,
    create_token,
    decode_token,
    dummy_verify,
    get_current_user,
    get_session,
    require_owner,
    verify_password,
)
from app.envelope import fail, ok
from app.models import Class, Question, User
from app.schemas import (
    DIFFICULTIES,
    LoginRequest,
    QuestionCreate,
    QuestionStatusUpdate,
    QuestionValidationError,
    question_to_dict,
    question_to_public_dict,
    validate_new_question,
)

router = APIRouter(prefix="/api")

WRONG_CREDENTIALS = "用户名或密码不对"

# 题库列表：每页固定 20 条（设计/05 §五）
PAGE_SIZE = 20
STATUS_LABELS = {"draft": "草稿", "pending": "待复核", "approved": "已通过"}

# 审核只走这三条边；已通过是终态，待复核不能退回草稿（设计/02 §4.2）
ALLOWED_TRANSITIONS = {
    ("draft", "pending"),
    ("draft", "approved"),
    ("pending", "approved"),
}


def require_question_manager(user: User) -> None:
    """题目写操作只给老师与管理员；学生没有建题、审题、删题的入口。"""
    if user.role not in ("teacher", "admin"):
        raise AccessDeniedError("只有老师和管理员可以管理题目")


def papers_using_question(_session: Session, _question_id: int) -> int:
    """这道题被几份卷子用过。卷子表在组卷章节引入，本章没有任何卷子，恒为 0。

    组卷章节必须先用真实查询替换这里，再开放"加题进卷"——否则会留下
    "先删题、再加进卷"的口子（设计/02 §4.3）。
    """
    return 0


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


def build_question_query(
    user: User,
    difficulty: int | None = None,
    status: str | None = None,
    keyword: str | None = None,
):
    """角色条件先加，用户筛选只收窄；两者的顺序不变量：筛选永远不能放大范围。"""
    if user.role == "teacher":
        conditions = [Question.created_by == user.username]
    elif user.role == "student":
        # 学生只看已通过（设计/02 §4.2）；这条与筛选无关，永远在
        conditions = [Question.status == "approved"]
    elif user.role == "admin":
        conditions = []
    else:
        # 未知角色不能落到"管理员全量"，直接拒绝
        raise AccessDeniedError("角色不认识，不能查看题目")

    if difficulty is not None:
        conditions.append(Question.difficulty == difficulty)
    if status is not None:
        conditions.append(Question.status == status)
    if keyword:
        conditions.append(Question.stem.contains(keyword))

    stmt = select(Question)
    if conditions:
        stmt = stmt.where(*conditions)
    return stmt


@router.get("/questions")
def list_questions(
    difficulty: int | None = None,
    status: str | None = None,
    q: str | None = None,
    page: int = 1,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if difficulty is not None and difficulty not in DIFFICULTIES:
        return fail("难度只能是 1、2、3", 422)
    if status is not None and status not in STATUS_LABELS:
        return fail("审核状态只能是草稿、待复核或已通过", 422)
    if page < 1:
        return fail("页码不对", 422)
    keyword = (q or "").strip() or None

    base = build_question_query(user, difficulty, status, keyword)
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = session.scalars(
        base.order_by(Question.created_at.desc(), Question.id.asc())
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
    ).all()

    # 学生条目不发标准答案与解析（设计/02 §4.6）
    if user.role == "student":
        items = [question_to_public_dict(item) for item in rows]
    else:
        items = [question_to_dict(item) for item in rows]
    return ok({"items": items, "total": total, "page": page, "page_size": PAGE_SIZE})


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


def get_owned_question(question_id: int, user: User, session: Session) -> Question:
    """取题并校验归属：不存在返回 404「题目不存在」，不是自己建的返回 403。"""
    question = session.get(Question, question_id)
    if question is None:
        raise QuestionNotFound()
    require_owner(question.created_by, user)
    return question


class QuestionNotFound(Exception):
    """题目不存在，main.py 统一转 404。"""


@router.put("/questions/{question_id}")
def update_question(
    question_id: int,
    body: QuestionCreate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    require_question_manager(user)
    question = get_owned_question(question_id, user, session)
    if question.status == "approved":
        return fail("已通过的题不能修改，要改请新建一道", 409)
    try:
        values = validate_new_question(body)
    except QuestionValidationError as e:
        return fail(str(e), 422)

    for field, value in values.items():
        setattr(question, field, value)
    session.commit()
    return ok(question_to_dict(question))


@router.post("/questions/{question_id}/status")
def change_question_status(
    question_id: int,
    body: QuestionStatusUpdate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    require_question_manager(user)
    question = get_owned_question(question_id, user, session)
    target = body.status
    if (question.status, target) not in ALLOWED_TRANSITIONS:
        if question.status == "approved":
            return fail("已通过的题不能再改状态", 409)
        return fail("不能这样改状态", 409)

    question.status = target
    session.commit()
    return ok(question_to_dict(question))


@router.get("/questions/{question_id}/usage")
def question_usage(
    question_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    require_question_manager(user)
    get_owned_question(question_id, user, session)
    return ok({"papers": papers_using_question(session, question_id)})


@router.delete("/questions/{question_id}")
def delete_question(
    question_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    require_question_manager(user)
    question = get_owned_question(question_id, user, session)
    count = papers_using_question(session, question_id)
    if count > 0:
        return fail(f"这道题已被 {count} 份卷子使用", 409)

    session.delete(question)
    session.commit()
    return ok({"deleted": question_id})
