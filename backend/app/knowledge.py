"""知识点：两层树、别名、题目关联与合并。

名称与别名共用一个全局词表；同一个词只能属于一个知识点。
"""
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    KnowledgePoint,
    KnowledgePointAlias,
    QuestionKnowledgePoint,
    User,
    utcnow,
)

MAX_NAME_LENGTH = 100


class KnowledgePointNotFound(Exception):
    """知识点不存在，main.py 统一转 404。"""


class KnowledgeError(ValueError):
    """知识点规则不满足，路由转 400 并显示中文原因。"""


def _clean_name(raw: str | None) -> str:
    name = (raw or "").strip()
    if not name:
        raise KnowledgeError("知识点名称不能为空")
    if len(name) > MAX_NAME_LENGTH:
        raise KnowledgeError("知识点名称最多 100 字")
    return name


def _clean_aliases(aliases: list[str] | None, *, exclude: str = "") -> list[str]:
    cleaned = []
    seen = set()
    for raw in aliases or []:
        alias = (raw or "").strip()
        if not alias or alias == exclude or alias in seen:
            continue
        if len(alias) > MAX_NAME_LENGTH:
            raise KnowledgeError("别名最多 100 字")
        seen.add(alias)
        cleaned.append(alias)
    return cleaned


def _aliases_of(session: Session, point_id: int) -> list[str]:
    return list(
        session.scalars(
            select(KnowledgePointAlias.alias)
            .where(KnowledgePointAlias.knowledge_point_id == point_id)
            .order_by(KnowledgePointAlias.id)
        ).all()
    )


def _ensure_words_free(
    session: Session, words: set[str], *, exclude_point_id: int | None = None
) -> None:
    """名称和别名共用一个词表；排除当前节点自己的词。"""
    for table, column, point_column in (
        (KnowledgePoint, KnowledgePoint.name, KnowledgePoint.id),
        (KnowledgePointAlias, KnowledgePointAlias.alias, KnowledgePointAlias.knowledge_point_id),
    ):
        stmt = select(column).where(column.in_(words))
        if exclude_point_id is not None:
            stmt = stmt.where(point_column != exclude_point_id)
        taken = set(session.scalars(stmt).all())
        if taken:
            word = sorted(taken)[0]
            raise KnowledgeError(f"「{word}」已经被其他知识点使用")


def _commit_or_conflict(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise KnowledgeError("名称或别名已经被占用") from exc


def _get(session: Session, point_id: int) -> KnowledgePoint:
    point = session.get(KnowledgePoint, point_id)
    if point is None:
        raise KnowledgePointNotFound()
    return point


def point_to_dict(session: Session, point: KnowledgePoint) -> dict:
    count = (
        session.scalar(
            select(func.count())
            .select_from(QuestionKnowledgePoint)
            .where(QuestionKnowledgePoint.knowledge_point_id == point.id)
        )
        or 0
    )
    return {
        "id": point.id,
        "name": point.name,
        "parent_id": point.parent_id,
        "aliases": _aliases_of(session, point.id),
        "question_count": count,
    }


def create_point(
    session: Session,
    *,
    name: str,
    parent_id: int | None,
    aliases: list[str] | None,
    user: User,
) -> dict:
    cleaned_name = _clean_name(name)
    if parent_id is not None:
        parent = _get(session, parent_id)
        if parent.parent_id is not None:
            raise KnowledgeError("知识点只有两层，不能建在第二层下面")
    cleaned_aliases = _clean_aliases(aliases, exclude=cleaned_name)
    _ensure_words_free(session, {cleaned_name, *cleaned_aliases})

    point = KnowledgePoint(
        name=cleaned_name,
        parent_id=parent_id,
        created_by=user.username,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(point)
    session.flush()
    for alias in cleaned_aliases:
        session.add(KnowledgePointAlias(knowledge_point_id=point.id, alias=alias))
    _commit_or_conflict(session)
    session.refresh(point)
    return point_to_dict(session, point)


def update_point(
    session: Session,
    point_id: int,
    *,
    name: str | None,
    aliases: list[str] | None,
) -> dict:
    point = _get(session, point_id)
    old_name = point.name
    new_name = old_name if name is None else _clean_name(name)

    if aliases is None:
        new_aliases = _aliases_of(session, point.id)
    else:
        new_aliases = _clean_aliases(aliases, exclude=new_name)

    if new_name != old_name:
        # 改名不能把旧名字弄丢，旧名自动成为别名
        new_aliases = _clean_aliases([old_name, *new_aliases], exclude=new_name)

    _ensure_words_free(
        session,
        {new_name, *new_aliases},
        exclude_point_id=point.id,
    )

    point.name = new_name
    point.updated_at = utcnow()
    session.execute(
        delete(KnowledgePointAlias).where(
            KnowledgePointAlias.knowledge_point_id == point.id
        )
    )
    session.flush()
    for alias in new_aliases:
        session.add(KnowledgePointAlias(knowledge_point_id=point.id, alias=alias))
    _commit_or_conflict(session)
    session.refresh(point)
    return point_to_dict(session, point)


def tree(session: Session) -> list[dict]:
    points = session.scalars(select(KnowledgePoint).order_by(KnowledgePoint.id)).all()
    aliases: dict[int, list[str]] = {}
    for row in session.scalars(
        select(KnowledgePointAlias).order_by(KnowledgePointAlias.id)
    ).all():
        aliases.setdefault(row.knowledge_point_id, []).append(row.alias)
    counts = dict(
        session.execute(
            select(
                QuestionKnowledgePoint.knowledge_point_id,
                func.count(QuestionKnowledgePoint.id),
            ).group_by(QuestionKnowledgePoint.knowledge_point_id)
        ).all()
    )

    nodes = {}
    for point in points:
        nodes[point.id] = {
            "id": point.id,
            "name": point.name,
            "parent_id": point.parent_id,
            "aliases": aliases.get(point.id, []),
            "question_count": counts.get(point.id, 0),
            "children": [],
        }

    roots = []
    for point in points:
        node = nodes[point.id]
        if point.parent_id is None:
            roots.append(node)
        elif point.parent_id in nodes:
            nodes[point.parent_id]["children"].append(node)
    return roots


def set_question_points(
    session: Session, question_id: int, point_ids: list[int]
) -> list[dict]:
    unique_ids = list(dict.fromkeys(point_ids))
    if unique_ids:
        existing = set(
            session.scalars(
                select(KnowledgePoint.id).where(KnowledgePoint.id.in_(unique_ids))
            ).all()
        )
        missing = [point_id for point_id in unique_ids if point_id not in existing]
        if missing:
            raise KnowledgePointNotFound()

    session.execute(
        delete(QuestionKnowledgePoint).where(
            QuestionKnowledgePoint.question_id == question_id
        )
    )
    session.flush()
    for point_id in unique_ids:
        session.add(
            QuestionKnowledgePoint(
                question_id=question_id, knowledge_point_id=point_id
            )
        )
    _commit_or_conflict(session)

    points = session.scalars(
        select(KnowledgePoint)
        .join(
            QuestionKnowledgePoint,
            QuestionKnowledgePoint.knowledge_point_id == KnowledgePoint.id,
        )
        .where(QuestionKnowledgePoint.question_id == question_id)
        .order_by(KnowledgePoint.id)
    ).all()
    return [{"id": point.id, "name": point.name} for point in points]


def merge_points(session: Session, source_id: int, target_id: int) -> dict:
    source = _get(session, source_id)
    target = _get(session, target_id)

    if source.id == target.id:
        raise KnowledgeError("不能把知识点合并到自己")
    if target.parent_id == source.id:
        raise KnowledgeError("不能把知识点合并到自己的下级")

    children = session.scalars(
        select(KnowledgePoint).where(KnowledgePoint.parent_id == source.id)
    ).all()
    if children and target.parent_id is not None:
        raise KnowledgeError("合并后会出现第三层知识点，换一个上级目标")

    # 别名：源名称也收进目标别名，旧的叫法不丢
    target_aliases = _aliases_of(session, target.id)
    source_aliases = _aliases_of(session, source.id)
    merged_aliases = _clean_aliases(
        [*target_aliases, source.name, *source_aliases], exclude=target.name
    )
    session.execute(
        delete(KnowledgePointAlias).where(
            KnowledgePointAlias.knowledge_point_id.in_([source.id, target.id])
        )
    )
    session.flush()
    for alias in merged_aliases:
        session.add(KnowledgePointAlias(knowledge_point_id=target.id, alias=alias))

    # 题目关联：目标已有的题去掉源里的重复行，其余改挂到目标
    target_question_ids = set(
        session.scalars(
            select(QuestionKnowledgePoint.question_id).where(
                QuestionKnowledgePoint.knowledge_point_id == target.id
            )
        ).all()
    )
    if target_question_ids:
        session.execute(
            delete(QuestionKnowledgePoint).where(
                QuestionKnowledgePoint.knowledge_point_id == source.id,
                QuestionKnowledgePoint.question_id.in_(target_question_ids),
            )
        )
    session.execute(
        update(QuestionKnowledgePoint)
        .where(QuestionKnowledgePoint.knowledge_point_id == source.id)
        .values(knowledge_point_id=target.id)
    )

    # 子节点改挂到目标（前面已保证不会出现第三层）
    if children:
        session.execute(
            update(KnowledgePoint)
            .where(KnowledgePoint.parent_id == source.id)
            .values(parent_id=target.id)
        )

    session.delete(source)
    _commit_or_conflict(session)
    session.refresh(target)
    return point_to_dict(session, target)
