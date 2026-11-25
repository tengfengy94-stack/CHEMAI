"""知识点接口：两层树、别名、题目关联与合并。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import knowledge
from app.auth import AccessDeniedError, get_current_user, get_session
from app.envelope import fail, ok
from app.models import Question, User
from app.schemas import (
    KnowledgePointCreate,
    KnowledgePointMerge,
    KnowledgePointUpdate,
    QuestionKnowledgePointsUpdate,
    question_to_dict,
)

router = APIRouter(prefix="/api")


def require_knowledge_access(user: User) -> None:
    if user.role not in ("teacher", "admin"):
        raise AccessDeniedError("只有老师和管理员可以查看或管理知识点")


@router.get("/knowledge-points")
def list_knowledge_points(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    require_knowledge_access(user)
    return ok({"items": knowledge.tree(session)})


@router.post("/knowledge-points")
def create_knowledge_point(
    body: KnowledgePointCreate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    require_knowledge_access(user)
    try:
        data = knowledge.create_point(
            session,
            name=body.name,
            parent_id=body.parent_id,
            aliases=body.aliases,
            user=user,
        )
    except knowledge.KnowledgeError as exc:
        return fail(str(exc), 400)
    return ok(data, 201)


@router.put("/knowledge-points/{point_id}")
def update_knowledge_point(
    point_id: int,
    body: KnowledgePointUpdate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    require_knowledge_access(user)
    try:
        data = knowledge.update_point(
            session, point_id, name=body.name, aliases=body.aliases
        )
    except knowledge.KnowledgeError as exc:
        return fail(str(exc), 400)
    return ok(data)


@router.post("/knowledge-points/{point_id}/merge")
def merge_knowledge_point(
    point_id: int,
    body: KnowledgePointMerge,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    require_knowledge_access(user)
    try:
        data = knowledge.merge_points(session, point_id, body.target_id)
    except knowledge.KnowledgeError as exc:
        return fail(str(exc), 400)
    return ok(data)


@router.get("/knowledge-points/{point_id}/questions")
def list_point_questions(
    point_id: int,
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """知识点下已关联的题目；老师只看自己建的题，管理员看全部。"""
    require_knowledge_access(user)
    if page < 1:
        return fail("页码不对", 422)
    page_size = max(1, min(page_size, 50))
    rows, total = knowledge.point_questions(
        session,
        point_id,
        created_by=user.username if user.role == "teacher" else None,
        page=page,
        page_size=page_size,
    )
    return ok(
        {
            "items": [
                {**question_to_dict(question), "is_primary": primary}
                for question, primary in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/questions/{question_id}/knowledge-points")
def get_question_knowledge_points(
    question_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    require_knowledge_access(user)
    question = session.get(Question, question_id)
    if question is None:
        return fail("题目不存在", 404)
    if user.role != "admin" and question.created_by != user.username:
        raise AccessDeniedError("不是这道题的创建者")
    return ok(
        {
            "question_id": question_id,
            "knowledge_points": knowledge.question_points(session, question_id),
        }
    )


@router.put("/questions/{question_id}/knowledge-points")
def set_question_knowledge_points(
    question_id: int,
    body: QuestionKnowledgePointsUpdate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    require_knowledge_access(user)
    question = session.get(Question, question_id)
    if question is None:
        return fail("题目不存在", 404)
    if user.role != "admin" and question.created_by != user.username:
        raise AccessDeniedError("不是这道题的创建者")
    try:
        points = knowledge.set_question_points(
            session,
            question_id,
            body.knowledge_point_ids,
            primary_point_id=body.primary_point_id,
        )
    except knowledge.KnowledgeError as exc:
        return fail(str(exc), 400)
    return ok({"question_id": question_id, "knowledge_points": points})
