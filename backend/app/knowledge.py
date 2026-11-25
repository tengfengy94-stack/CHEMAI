"""知识点：两层树、别名、题目关联与合并。

名称与别名共用一个全局词表；同一个词只能属于一个知识点。
"""
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    KnowledgePoint,
    KnowledgePointAlias,
    Question,
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


def get_point(session: Session, point_id: int) -> KnowledgePoint:
    """公开的取点入口：路由需要区分“不存在”和“没有权限”。"""
    return _get(session, point_id)


def point_questions(
    session: Session,
    point_id: int,
    *,
    created_by: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[tuple[Question, bool]], int]:
    """某个知识点下的题目及“是否主知识点”；老师只看自己建的题。"""
    _get(session, point_id)
    stmt = (
        select(Question, QuestionKnowledgePoint.is_primary)
        .join(
            QuestionKnowledgePoint,
            QuestionKnowledgePoint.question_id == Question.id,
        )
        .where(QuestionKnowledgePoint.knowledge_point_id == point_id)
    )
    if created_by is not None:
        stmt = stmt.where(Question.created_by == created_by)
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = session.execute(
        stmt.order_by(Question.created_at.desc(), Question.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return [(question, bool(primary)) for question, primary in rows], int(total)


def question_points(session: Session, question_id: int) -> list[dict]:
    """一道题关联的所有知识点及主次。"""
    rows = session.execute(
        select(
            KnowledgePoint.id,
            KnowledgePoint.name,
            QuestionKnowledgePoint.is_primary,
        )
        .join(
            QuestionKnowledgePoint,
            QuestionKnowledgePoint.knowledge_point_id == KnowledgePoint.id,
        )
        .where(QuestionKnowledgePoint.question_id == question_id)
        .order_by(KnowledgePoint.id)
    ).all()
    return [
        {"id": point_id, "name": name, "is_primary": bool(primary)}
        for point_id, name, primary in rows
    ]


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


def _match_score(query: str, word: str) -> int:
    """名称/别名匹配打分：精确最高，包含次之；0 表示不匹配。"""
    if not query or not word:
        return 0
    if word == query:
        return 100
    if query in word:
        return 90 - min(len(word) - len(query), 20)
    if word in query:
        return 80 - min(len(query) - len(word), 20)
    return 0


def find_point(session: Session, query: str) -> dict | None:
    """按名称与别名找最接近的一个知识点；匹配不到返回 None，不猜。"""
    raw = (query or "").strip()
    if not raw:
        return None
    lowered = raw.casefold()

    aliases: dict[int, list[str]] = {}
    for row in session.scalars(
        select(KnowledgePointAlias).order_by(KnowledgePointAlias.id)
    ).all():
        aliases.setdefault(row.knowledge_point_id, []).append(row.alias)

    best: tuple[int, int] | None = None
    best_point: KnowledgePoint | None = None
    for point in session.scalars(select(KnowledgePoint).order_by(KnowledgePoint.id)).all():
        score = _match_score(lowered, point.name.casefold())
        for alias in aliases.get(point.id, []):
            score = max(score, _match_score(lowered, alias.casefold()))
        if score <= 0:
            continue
        # 同分取 id 小的，结果稳定
        candidate = (score, -point.id)
        if best is None or candidate > best:
            best = candidate
            best_point = point

    if best_point is None:
        return None
    return {
        "id": best_point.id,
        "name": best_point.name,
        "parent_id": best_point.parent_id,
        "aliases": aliases.get(best_point.id, []),
    }


def _create_point(
    session: Session,
    *,
    name: str,
    parent_id: int | None,
    aliases: list[str] | None,
    created_by: str,
) -> KnowledgePoint:
    """建节点但不提交，供接口与迁移复用。"""
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
        created_by=created_by,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(point)
    session.flush()
    for alias in cleaned_aliases:
        session.add(KnowledgePointAlias(knowledge_point_id=point.id, alias=alias))
    session.flush()
    return point


def create_point(
    session: Session,
    *,
    name: str,
    parent_id: int | None,
    aliases: list[str] | None,
    user: User,
) -> dict:
    point = _create_point(
        session,
        name=name,
        parent_id=parent_id,
        aliases=aliases,
        created_by=user.username,
    )
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
    session: Session,
    question_id: int,
    point_ids: list[int],
    primary_point_id: int | None = None,
) -> list[dict]:
    unique_ids = list(dict.fromkeys(point_ids))
    if primary_point_id is not None and primary_point_id not in unique_ids:
        raise KnowledgeError("主知识点必须属于这道题的关联")
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
                question_id=question_id,
                knowledge_point_id=point_id,
                is_primary=point_id == primary_point_id,
            )
        )
    _commit_or_conflict(session)
    return question_points(session, question_id)


def _merge_points(
    session: Session, source: KnowledgePoint, target: KnowledgePoint
) -> None:
    """把 source 并进 target 但不提交，供接口与迁移复用。"""
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

    # 题目关联：目标已有的题去掉源里的重复行，其余改挂到目标。
    # 如果被去掉的源关联是主知识点，把目标上那道题的关联补成主。
    source_primary_ids = set(
        session.scalars(
            select(QuestionKnowledgePoint.question_id).where(
                QuestionKnowledgePoint.knowledge_point_id == source.id,
                QuestionKnowledgePoint.is_primary.is_(True),
            )
        ).all()
    )
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
        promoted = source_primary_ids & target_question_ids
        if promoted:
            session.execute(
                update(QuestionKnowledgePoint)
                .where(
                    QuestionKnowledgePoint.knowledge_point_id == target.id,
                    QuestionKnowledgePoint.question_id.in_(promoted),
                )
                .values(is_primary=True)
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
    session.flush()


def merge_points(session: Session, source_id: int, target_id: int) -> dict:
    source = _get(session, source_id)
    target = _get(session, target_id)
    _merge_points(session, source, target)
    _commit_or_conflict(session)
    session.refresh(target)
    return point_to_dict(session, target)
