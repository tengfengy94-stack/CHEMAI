"""从评测库导出真实引用清单，供用例生成与加载校验使用。"""
from sqlalchemy import select

from app.db import make_engine, make_session_factory
from app.models import KnowledgePoint, KnowledgePointAlias, Question, QuestionKnowledgePoint
from evalkit.db import EvalFixture


def build_reference_index(fixture: EvalFixture) -> dict:
    engine = make_engine(fixture.database_url)
    factory = make_session_factory(engine)
    try:
        with factory() as session:
            points = session.scalars(
                select(KnowledgePoint).order_by(KnowledgePoint.id)
            ).all()
            aliases: dict[int, list[str]] = {}
            for row in session.scalars(
                select(KnowledgePointAlias).order_by(KnowledgePointAlias.id)
            ).all():
                aliases.setdefault(row.knowledge_point_id, []).append(row.alias)
            questions = session.scalars(select(Question).order_by(Question.id)).all()
            links = session.execute(
                select(
                    QuestionKnowledgePoint.question_id,
                    KnowledgePoint.name,
                ).join(
                    KnowledgePoint,
                    KnowledgePoint.id == QuestionKnowledgePoint.knowledge_point_id,
                )
            ).all()
    finally:
        engine.dispose()

    point_names: dict[int, list[str]] = {}
    for question_id, name in links:
        point_names.setdefault(question_id, []).append(name)

    return {
        "knowledge_points": [
            {
                "id": point.id,
                "name": point.name,
                "parent_id": point.parent_id,
                "aliases": aliases.get(point.id, []),
            }
            for point in points
        ],
        "questions": [
            {
                "id": question.id,
                "stem": question.stem,
                "type": question.type,
                "status": question.status,
                "difficulty": question.difficulty,
                "points": point_names.get(question.id, []),
            }
            for question in questions
        ],
        "question_refs": dict(fixture.question_refs),
        "question_stems": dict(fixture.question_stems),
        "classes": dict(fixture.classes),
        "users": dict(fixture.users),
    }


def resolve_point(index: dict, word: str) -> dict | None:
    """正式名或别名解析到同一个知识点；精确匹配。"""
    target = (word or "").strip()
    if not target:
        return None
    for point in index["knowledge_points"]:
        if point["name"] == target or target in point["aliases"]:
            return point
    return None


def resolve_question(index: dict, key: str) -> int | None:
    return index["question_refs"].get(key)


def question_exists(index: dict, question_id: int) -> bool:
    return any(question["id"] == question_id for question in index["questions"])


def render(template: str, index: dict) -> str:
    """把用例里的 {q:key} 与 {stem:key} 换成库里真实值。"""
    text = template
    for key, question_id in index["question_refs"].items():
        text = text.replace(f"{{q:{key}}}", str(question_id))
    for key, stem in index["question_stems"].items():
        text = text.replace(f"{{stem:{key}}}", stem)
    return text
