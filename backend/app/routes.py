"""三个动作：健康检查、题目列表、建题。"""
from collections.abc import Iterator

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import PLACEHOLDER_CREATOR
from app.envelope import fail, ok
from app.models import Question
from app.schemas import QuestionCreate, QuestionValidationError, question_to_dict, validate_new_question

router = APIRouter(prefix="/api")


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


@router.get("/health")
def health():
    return ok({"status": "ok"})


@router.get("/questions")
def list_questions(session: Session = Depends(get_session)):
    # 最新的在最上面；同一时刻建的（种子题）按 id 顺序
    rows = session.scalars(select(Question).order_by(Question.created_at.desc(), Question.id.asc())).all()
    return ok([question_to_dict(q) for q in rows])


@router.post("/questions")
def create_question(body: QuestionCreate, session: Session = Depends(get_session)):
    try:
        values = validate_new_question(body)
    except QuestionValidationError as e:
        return fail(str(e), 422)

    question = Question(**values, status="draft", created_by=PLACEHOLDER_CREATOR)
    session.add(question)
    session.commit()
    return ok(question_to_dict(question), status_code=201)
