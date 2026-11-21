"""登录与刷新、题库接口。权限三层：get_current_user 挡匿名，查询过滤带身份条件，
归属判定走 app.auth 的 require_* 函数。
"""
import jwt
from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.answers import judge_answer, score_for
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
from app.models import (
    AnswerItem,
    AnswerRecord,
    Class,
    Paper,
    PaperQuestion,
    Question,
    User,
    utcnow,
)
from app.schemas import (
    DIFFICULTIES,
    AnswerInput,
    AttemptSubmit,
    LoginRequest,
    PaperCreate,
    PaperPublish,
    PaperQuestionAdd,
    QuestionCreate,
    QuestionStatusUpdate,
    QuestionValidationError,
    attempt_to_dict,
    paper_question_to_dict,
    paper_to_dict,
    question_pool_to_dict,
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


def papers_using_question(session: Session, question_id: int) -> int:
    """这道题当前被几份卷子引用。草稿卷也计入；从草稿卷减掉后不再计。

    已发布卷子的内容不可改，所以“当前引用”就是“历史引用”，不会出现
    考过的卷子里这道题被删掉的情况（设计/02 §4.3）。
    """
    return (
        session.scalar(
            select(func.count(func.distinct(PaperQuestion.paper_id))).where(
                PaperQuestion.question_id == question_id
            )
        )
        or 0
    )


# ---- 考试：卷子、作答记录 ----

PAPER_STATUSES = ("draft", "published")
ATTEMPT_STATUSES = ("pending", "in_progress", "submitted", "graded")
GRADING_LEASE_SECONDS = 60


class PaperNotFound(Exception):
    """卷子不存在，main.py 统一转 404。"""


class AttemptNotFound(Exception):
    """作答记录不存在，main.py 统一转 404。"""


class ClassNotFound(Exception):
    """班级不存在，main.py 统一转 404。"""


def require_paper_manager(user: User) -> None:
    """卷子读写只给老师与管理员；学生没有组卷、发布入口。"""
    if user.role not in ("teacher", "admin"):
        raise AccessDeniedError("只有老师和管理员可以管理卷子")


def get_owned_paper(paper_id: int, user: User, session: Session) -> Paper:
    paper = session.get(Paper, paper_id)
    if paper is None:
        raise PaperNotFound()
    if user.role != "admin" and paper.created_by != user.username:
        raise AccessDeniedError("不是这份卷子的创建者")
    return paper


def get_attempt_record(attempt_id: int, session: Session) -> AnswerRecord:
    record = session.get(AnswerRecord, attempt_id)
    if record is None:
        raise AttemptNotFound()
    return record


def require_attempt_reader(record: AnswerRecord, user: User) -> None:
    """学生只能看自己的；管理员可读全部；老师没有这里的结果入口。"""
    if user.role == "admin":
        return
    if user.role != "student" or record.student_id != user.id:
        raise AccessDeniedError("只能看自己的作答记录")


def require_attempt_owner(record: AnswerRecord, user: User) -> None:
    """开始、交卷、重试只能是记录所属学生；管理员也不能代替。"""
    if user.role == "admin":
        raise AccessDeniedError("管理员不能代替学生作答")
    if user.role != "student":
        raise AccessDeniedError("只有学生可以作答")
    if record.student_id != user.id:
        raise AccessDeniedError("只能操作自己的作答记录")


def _as_utc(value):
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _grading_in_progress(record: AnswerRecord) -> bool:
    if record.status != "submitted" or record.score is not None:
        return False
    started = _as_utc(record.grading_started_at)
    if started is None:
        return False
    return (utcnow() - started).total_seconds() < GRADING_LEASE_SECONDS


def _paper_detail(session: Session, paper: Paper) -> dict:
    rows = session.execute(
        select(PaperQuestion, Question)
        .join(Question, Question.id == PaperQuestion.question_id)
        .where(PaperQuestion.paper_id == paper.id)
        .order_by(PaperQuestion.position, PaperQuestion.id)
    ).all()
    data = paper_to_dict(paper, len(rows))
    data["questions"] = [paper_question_to_dict(pq, q) for pq, q in rows]
    return data


def _attempt_detail(session: Session, record: AnswerRecord) -> dict:
    paper = session.get(Paper, record.paper_id)
    data = attempt_to_dict(
        record, paper.title if paper else "", _grading_in_progress(record)
    )
    if record.status == "pending":
        data["questions"] = []
        return data

    rows = session.execute(
        select(PaperQuestion, Question, AnswerItem)
        .join(Question, Question.id == PaperQuestion.question_id)
        .outerjoin(
            AnswerItem,
            (AnswerItem.record_id == record.id)
            & (AnswerItem.question_id == PaperQuestion.question_id),
        )
        .where(PaperQuestion.paper_id == record.paper_id)
        .order_by(PaperQuestion.position, PaperQuestion.id)
    ).all()
    questions = []
    for pq, question, item in rows:
        entry = {
            "id": question.id,
            "position": pq.position,
            "stem": question.stem,
            "type": question.type,
            "options": question.options,
        }
        if record.status in ("submitted", "graded"):
            entry["student_answer"] = item.student_answer if item else ""
        if record.status == "graded":
            entry["answer"] = question.answer
            entry["explanation"] = question.explanation
            entry["is_correct"] = bool(item.is_correct) if item else False
        questions.append(entry)
    data["questions"] = questions
    return data


def grade_record(session: Session, record: AnswerRecord) -> None:
    """判分事务：写逐题对错、总分并推进到已判分。失败由调用方回滚。"""
    rows = session.execute(
        select(AnswerItem, Question)
        .join(Question, Question.id == AnswerItem.question_id)
        .where(AnswerItem.record_id == record.id)
        .order_by(AnswerItem.position, AnswerItem.id)
    ).all()
    if not rows:
        raise RuntimeError("卷子里没有题，无法判分")

    correct = 0
    for item, question in rows:
        item.is_correct = judge_answer(
            question.type,
            question.answer,
            item.student_answer,
            len(question.options or []),
        )
        if item.is_correct:
            correct += 1

    record.score = score_for(correct, len(rows))
    record.status = "graded"
    record.graded_at = utcnow()
    record.grading_started_at = None
    session.commit()


def _start_state_error(record: AnswerRecord):
    if record.status in ("submitted", "graded"):
        return fail("已经交过卷了，不能再开始", 400)
    return fail("当前状态不能开始作答", 400)


def _submit_state_error(record: AnswerRecord):
    messages = {
        "pending": "还没开始作答，不能交卷",
        "submitted": "已经交过了，不能再交卷",
        "graded": "分数已经定了，不能再交卷",
    }
    return fail(messages.get(record.status, "当前状态不能交卷"), 400)


def _retry_state_error(record: AnswerRecord):
    if record.status == "graded" or (
        record.status == "submitted" and record.score is not None
    ):
        return fail("分数已经定了，不能重试判分", 400)
    if record.status in ("pending", "in_progress"):
        return fail("还没交卷，不能重试判分", 400)
    return fail("当前状态不能重试判分", 400)


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


# ---- 考试：老师组卷与发布 ----

@router.get("/classes")
def list_classes(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """组卷发布弹窗用：老师看自己带的班，管理员看全部；带学生人数。"""
    require_paper_manager(user)
    stmt = select(Class)
    if user.role == "teacher":
        stmt = stmt.where(Class.teacher_id == user.id)
    classes = session.scalars(stmt.order_by(Class.id)).all()
    ids = [c.id for c in classes]
    counts = {}
    if ids:
        counts = dict(
            session.execute(
                select(User.class_id, func.count())
                .where(User.role == "student", User.class_id.in_(ids))
                .group_by(User.class_id)
            ).all()
        )
    return ok(
        {
            "items": [
                {
                    "id": c.id,
                    "name": c.name,
                    "student_count": counts.get(c.id, 0),
                }
                for c in classes
            ]
        }
    )


@router.get("/papers")
def list_papers(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    require_paper_manager(user)
    stmt = select(Paper, func.count(PaperQuestion.id)).outerjoin(
        PaperQuestion, PaperQuestion.paper_id == Paper.id
    )
    if user.role == "teacher":
        stmt = stmt.where(Paper.created_by == user.username)
    rows = session.execute(
        stmt.group_by(Paper.id).order_by(Paper.created_at.desc(), Paper.id.asc())
    ).all()
    return ok({"items": [paper_to_dict(paper, count) for paper, count in rows]})


@router.post("/papers")
def create_paper(
    body: PaperCreate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    require_paper_manager(user)
    title = body.title.strip()
    if not title:
        return fail("卷子名称不能为空", 422)
    if len(title) > 100:
        return fail("卷子名称最多 100 个字", 422)

    paper = Paper(title=title, status="draft", created_by=user.username)
    session.add(paper)
    session.commit()
    session.refresh(paper)
    return ok(paper_to_dict(paper, 0), status_code=201)


@router.get("/papers/pool")
def paper_question_pool(
    difficulty: int | None = None,
    q: str | None = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """组卷题目池：只给当前老师自己的已通过题。"""
    require_paper_manager(user)
    if difficulty is not None and difficulty not in DIFFICULTIES:
        return fail("难度只能是 1、2、3", 422)

    conditions = [Question.status == "approved"]
    if user.role == "teacher":
        conditions.append(Question.created_by == user.username)
    if difficulty is not None:
        conditions.append(Question.difficulty == difficulty)
    keyword = (q or "").strip()
    if keyword:
        conditions.append(Question.stem.contains(keyword))

    rows = session.scalars(
        select(Question)
        .where(*conditions)
        .order_by(Question.created_at.desc(), Question.id.asc())
    ).all()
    return ok({"items": [question_pool_to_dict(question) for question in rows]})


@router.get("/papers/{paper_id}")
def get_paper(
    paper_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    require_paper_manager(user)
    paper = get_owned_paper(paper_id, user, session)
    return ok(_paper_detail(session, paper))


@router.post("/papers/{paper_id}/questions")
def add_paper_question(
    paper_id: int,
    body: PaperQuestionAdd,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    require_paper_manager(user)
    paper = get_owned_paper(paper_id, user, session)
    if paper.status != "draft":
        return fail("已发布的卷子不能修改", 400)

    question = session.get(Question, body.question_id)
    if question is None:
        raise QuestionNotFound()
    if question.status != "approved":
        return fail("只有已通过的题能加入卷子", 400)
    require_owner(question.created_by, user)

    # 条件插入：只有卷子仍是 draft 才插入；重复加由唯一约束忽略。
    # position 在同一条 INSERT 里算，两个并发加题不会算出同一个位置。
    result = session.execute(
        text(
            """
            INSERT INTO paper_questions (paper_id, question_id, position)
            SELECT :paper_id, :question_id,
                   COALESCE(
                       (SELECT MAX(position) FROM paper_questions WHERE paper_id = :paper_id),
                       0
                   ) + 1
            WHERE EXISTS (
                SELECT 1 FROM papers WHERE id = :paper_id AND status = 'draft'
            )
            ON CONFLICT(paper_id, question_id) DO NOTHING
            """
        ),
        {"paper_id": paper_id, "question_id": body.question_id},
    )
    added = (result.rowcount or 0) > 0
    session.commit()

    if not added:
        session.refresh(paper)
        if paper.status != "draft":
            return fail("已发布的卷子不能修改", 400)
    return ok({"added": added, "paper": _paper_detail(session, paper)})


@router.delete("/papers/{paper_id}/questions/{question_id}")
def remove_paper_question(
    paper_id: int,
    question_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    require_paper_manager(user)
    paper = get_owned_paper(paper_id, user, session)
    if paper.status != "draft":
        return fail("已发布的卷子不能修改", 400)

    result = session.execute(
        text(
            """
            DELETE FROM paper_questions
            WHERE paper_id = :paper_id AND question_id = :question_id
              AND EXISTS (
                  SELECT 1 FROM papers WHERE id = :paper_id AND status = 'draft'
              )
            """
        ),
        {"paper_id": paper_id, "question_id": question_id},
    )
    removed = (result.rowcount or 0) > 0
    session.commit()

    if not removed:
        session.refresh(paper)
        if paper.status != "draft":
            return fail("已发布的卷子不能修改", 400)
        return fail("卷子里没有这道题", 404)
    return ok({"removed": question_id, "paper": _paper_detail(session, paper)})


@router.post("/papers/{paper_id}/publish")
def publish_paper(
    paper_id: int,
    body: PaperPublish,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    require_paper_manager(user)
    paper = get_owned_paper(paper_id, user, session)
    if paper.status not in PAPER_STATUSES:
        return fail("卷子状态不对", 400)

    klass = session.get(Class, body.class_id)
    if klass is None:
        raise ClassNotFound()
    if user.role != "admin" and (
        user.role != "teacher" or klass.teacher_id != user.id
    ):
        raise AccessDeniedError("只能发布给自己带的班")

    # 先抢卷子状态，再校验内容：发布与加题/减题因此互斥。
    if paper.status == "draft":
        claimed = session.execute(
            update(Paper)
            .where(Paper.id == paper.id, Paper.status == "draft")
            .values(status="published")
        )
        if claimed.rowcount == 0:
            session.rollback()
            paper = get_owned_paper(paper_id, user, session)
        else:
            paper.status = "published"

    question_count = (
        session.scalar(
            select(func.count())
            .select_from(PaperQuestion)
            .where(PaperQuestion.paper_id == paper.id)
        )
        or 0
    )
    if question_count == 0:
        session.rollback()
        return fail("卷子里还没有题", 400)

    students = session.scalars(
        select(User).where(User.role == "student", User.class_id == klass.id)
    ).all()
    if not students:
        session.rollback()
        return fail("该班还没有学生", 400)

    now = utcnow()
    stmt = (
        sqlite_insert(AnswerRecord)
        .values(
            [
                {
                    "paper_id": paper.id,
                    "student_id": student.id,
                    "class_id": klass.id,
                    "status": "pending",
                    "created_at": now,
                }
                for student in students
            ]
        )
        .on_conflict_do_nothing(index_elements=["paper_id", "student_id"])
    )
    result = session.execute(stmt)
    created = result.rowcount if result.rowcount and result.rowcount > 0 else 0
    session.commit()
    return ok(
        {
            "created": created,
            "skipped": len(students) - created,
            "paper": paper_to_dict(paper, question_count),
        }
    )


# ---- 考试：学生作答 ----

@router.get("/attempts")
def list_attempts(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if user.role == "student":
        condition = AnswerRecord.student_id == user.id
    elif user.role == "admin":
        condition = None
    else:
        raise AccessDeniedError("只有学生可以查看自己的作答记录")

    stmt = select(AnswerRecord, Paper.title).join(Paper, Paper.id == AnswerRecord.paper_id)
    if condition is not None:
        stmt = stmt.where(condition)
    rows = session.execute(
        stmt.order_by(AnswerRecord.created_at.desc(), AnswerRecord.id.asc())
    ).all()
    return ok(
        {
            "items": [
                attempt_to_dict(record, title, _grading_in_progress(record))
                for record, title in rows
            ]
        }
    )


@router.get("/attempts/{attempt_id}")
def get_attempt(
    attempt_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    record = get_attempt_record(attempt_id, session)
    require_attempt_reader(record, user)
    return ok(_attempt_detail(session, record))


@router.post("/attempts/{attempt_id}/start")
def start_attempt(
    attempt_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    record = get_attempt_record(attempt_id, session)
    require_attempt_owner(record, user)

    if record.status == "in_progress":
        return ok(_attempt_detail(session, record))
    if record.status != "pending":
        return _start_state_error(record)

    changed = session.execute(
        update(AnswerRecord)
        .where(AnswerRecord.id == record.id, AnswerRecord.status == "pending")
        .values(status="in_progress", started_at=utcnow())
    )
    session.commit()
    if changed.rowcount == 0:
        session.refresh(record)
        if record.status == "in_progress":
            return ok(_attempt_detail(session, record))
        return _start_state_error(record)

    session.refresh(record)
    return ok(_attempt_detail(session, record))


@router.post("/attempts/{attempt_id}/submit")
def submit_attempt(
    attempt_id: int,
    body: AttemptSubmit,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    record = get_attempt_record(attempt_id, session)
    require_attempt_owner(record, user)
    if record.status != "in_progress":
        return _submit_state_error(record)

    rows = session.execute(
        select(PaperQuestion, Question)
        .join(Question, Question.id == PaperQuestion.question_id)
        .where(PaperQuestion.paper_id == record.paper_id)
        .order_by(PaperQuestion.position, PaperQuestion.id)
    ).all()
    question_ids = {pq.question_id for pq, _question in rows}
    answers: dict[int, str] = {}
    for item in body.answers:
        if item.question_id not in question_ids:
            return fail("答案里有不属于这份卷子的题", 400)
        if item.question_id in answers:
            return fail("同一道题只能提交一次答案", 400)
        if len(item.answer) > 500:
            return fail("单题答案最多 500 字", 422)
        answers[item.question_id] = item.answer

    now = utcnow()
    claimed = session.execute(
        update(AnswerRecord)
        .where(
            AnswerRecord.id == record.id,
            AnswerRecord.status == "in_progress",
        )
        .values(
            status="submitted",
            submitted_at=now,
            grading_started_at=now,
        )
    )
    if claimed.rowcount == 0:
        session.rollback()
        session.refresh(record)
        return _submit_state_error(record)

    for pq, _question in rows:
        session.add(
            AnswerItem(
                record_id=record.id,
                question_id=pq.question_id,
                position=pq.position,
                student_answer=answers.get(pq.question_id, ""),
                is_correct=None,
            )
        )
    session.commit()
    session.refresh(record)

    try:
        grade_record(session, record)
    except Exception:
        # 答案已经落库，判分失败只清租约，保留“已交卷 + 空分”的重试态。
        session.rollback()
        try:
            session.execute(
                update(AnswerRecord)
                .where(AnswerRecord.id == record.id)
                .values(grading_started_at=None)
            )
            session.commit()
        except Exception:
            session.rollback()
        session.refresh(record)
        return ok(_attempt_detail(session, record))

    session.refresh(record)
    return ok(_attempt_detail(session, record))


@router.post("/attempts/{attempt_id}/retry-grading")
def retry_grading(
    attempt_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    record = get_attempt_record(attempt_id, session)
    require_attempt_owner(record, user)
    if record.status != "submitted" or record.score is not None:
        return _retry_state_error(record)

    now = utcnow()
    cutoff = now - timedelta(seconds=GRADING_LEASE_SECONDS)
    claimed = session.execute(
        update(AnswerRecord)
        .where(
            AnswerRecord.id == record.id,
            AnswerRecord.status == "submitted",
            AnswerRecord.score.is_(None),
            or_(
                AnswerRecord.grading_started_at.is_(None),
                AnswerRecord.grading_started_at < cutoff,
            ),
        )
        .values(grading_started_at=now)
        .execution_options(synchronize_session=False)
    )
    session.commit()
    if claimed.rowcount == 0:
        session.refresh(record)
        if record.status == "graded":
            return fail("分数已经定了，不能重试判分", 400)
        return fail("判分正在进行，请稍后再试", 400)

    session.refresh(record)
    try:
        grade_record(session, record)
    except Exception:
        session.rollback()
        try:
            session.execute(
                update(AnswerRecord)
                .where(AnswerRecord.id == record.id)
                .values(grading_started_at=None)
            )
            session.commit()
        except Exception:
            session.rollback()
        session.refresh(record)
        return ok(_attempt_detail(session, record))

    session.refresh(record)
    return ok(_attempt_detail(session, record))
