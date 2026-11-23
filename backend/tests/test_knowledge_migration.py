"""正式词表与第 07 章临时知识点迁移（第 08 章）。"""
from contextlib import contextmanager

import pytest
from sqlalchemy import select

import app.knowledge as knowledge
import app.knowledge_migrate as migrate
from app.db import make_engine, make_session_factory
from app.knowledge_seed import FORMAL_CHILDREN, FORMAL_ROOTS, TEMP_LABEL_MAP
from app.models import (
    KnowledgePoint,
    KnowledgePointAlias,
    Question,
    QuestionKnowledgePoint,
    utcnow,
)


@contextmanager
def db_session(database_url):
    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    try:
        with factory() as session:
            yield session
    finally:
        engine.dispose()


def add_point(session, name, parent=None, aliases=()):
    point = KnowledgePoint(
        name=name,
        parent_id=parent.id if parent is not None else None,
        created_by="t1",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(point)
    session.flush()
    for alias in aliases:
        session.add(KnowledgePointAlias(knowledge_point_id=point.id, alias=alias))
    session.flush()
    return point


def add_question(session, stem):
    question = Question(
        stem=stem,
        type="single",
        options=["A", "B"],
        answer="A",
        difficulty=1,
        status="approved",
        created_by="t1",
        created_at=utcnow(),
    )
    session.add(question)
    session.flush()
    return question


def link(session, question, point):
    session.add(
        QuestionKnowledgePoint(question_id=question.id, knowledge_point_id=point.id)
    )
    session.flush()


def ch07_data(session, *, with_electro=False):
    """造第 07 章验收走查后的临时树与题目关联。"""
    root = add_point(session, "氧化还原", aliases=["氧化还原反应"])
    oxidant = add_point(session, "氧化剂", parent=root)
    electrolyte = add_point(session, "电解质", aliases=["电离"])
    formula = add_point(session, "化学式与化合价", aliases=["化学式"])
    misc = add_point(session, "杂项")

    electro = add_point(session, "电化学") if with_electro else None

    q1 = add_question(session, "氧化剂题")
    q2 = add_question(session, "电解质题")
    q3 = add_question(session, "化学式题")
    q4 = add_question(session, "杂项题")
    link(session, q1, oxidant)
    link(session, q2, electrolyte)
    if electro is not None:
        link(session, q2, electro)
    link(session, q3, formula)
    link(session, q4, misc)
    session.commit()
    return {
        "root": root.name,
        "oxidant": oxidant.name,
        "electrolyte": electrolyte.name,
        "formula": formula.name,
        "misc": misc.name,
        "questions": {"oxidant": q1.id, "electrolyte": q2.id, "formula": q3.id, "misc": q4.id},
    }


def snapshot(session):
    points = list(session.scalars(select(KnowledgePoint)))
    by_id = {point.id: point for point in points}
    result = {}
    for point in points:
        aliases = list(
            session.scalars(
                select(KnowledgePointAlias.alias).where(
                    KnowledgePointAlias.knowledge_point_id == point.id
                )
            )
        )
        question_ids = list(
            session.scalars(
                select(QuestionKnowledgePoint.question_id).where(
                    QuestionKnowledgePoint.knowledge_point_id == point.id
                )
            )
        )
        result[point.name] = {
            "parent": by_id[point.parent_id].name if point.parent_id else None,
            "aliases": sorted(aliases),
            "questions": sorted(question_ids),
        }
    return result


def test_formal_taxonomy_and_mapping():
    assert FORMAL_ROOTS == ("氧化还原", "电化学", "化学平衡", "物质结构", "元素周期律")
    assert FORMAL_CHILDREN == {"氧化还原": ("氧化剂", "还原剂")}
    assert TEMP_LABEL_MAP["电解质"] == "电化学"
    assert TEMP_LABEL_MAP["电离"] == "电化学"
    assert TEMP_LABEL_MAP["化学式与化合价"] == "物质结构"
    assert TEMP_LABEL_MAP["化学式"] == "物质结构"


def test_dry_run_reports_plan_without_writing(database_url):
    with db_session(database_url) as session:
        data = ch07_data(session)
        before = snapshot(session)

        report = migrate.run_migration(session, dry_run=True)

        assert report["dry_run"] is True
        assert report["applied"] is False
        assert {item["name"] for item in report["created"]} == {
            "电化学",
            "化学平衡",
            "物质结构",
            "元素周期律",
            "还原剂",
        }
        assert report["merged"] == [
            {"source": data["electrolyte"], "target": "电化学"},
            {"source": data["formula"], "target": "物质结构"},
        ]
        assert report["kept"] == [data["misc"]]
        assert report["moved_questions"] == 2
        assert report["conflicts"] == []
        assert snapshot(session) == before
        session.rollback()


def test_apply_migrates_aliases_questions_and_deletes_sources(database_url):
    with db_session(database_url) as session:
        data = ch07_data(session, with_electro=True)

        report = migrate.run_migration(session, dry_run=False)

        assert report["applied"] is True
        assert {item["name"] for item in report["created"]} == {
            "化学平衡",
            "物质结构",
            "元素周期律",
            "还原剂",
        }
        # q2 同时挂在电解质和电化学上：源里的重复行删掉，题目关联数不增加。
        assert report["moved_questions"] == 1
        assert report["conflicts"] == []

        tree = snapshot(session)
        assert data["electrolyte"] not in tree
        assert data["formula"] not in tree
        assert "电化学" in tree
        assert tree["电化学"]["aliases"] == sorted(["电解质", "电离"])
        assert tree["电化学"]["questions"] == [data["questions"]["electrolyte"]]
        assert tree["物质结构"]["aliases"] == sorted(["化学式与化合价", "化学式"])
        assert tree["物质结构"]["questions"] == [data["questions"]["formula"]]
        assert tree["氧化还原"]["aliases"] == ["氧化还原反应"]
        assert tree["氧化剂"]["parent"] == "氧化还原"
        assert tree["氧化剂"]["questions"] == [data["questions"]["oxidant"]]
        assert tree["还原剂"]["parent"] == "氧化还原"
        assert tree["杂项"]["questions"] == [data["questions"]["misc"]]

        # q2 在目标下只有一条关联，没有重复行。
        q2_rows = session.scalars(
            select(QuestionKnowledgePoint).where(
                QuestionKnowledgePoint.question_id == data["questions"]["electrolyte"]
            )
        ).all()
        assert len(q2_rows) == 1


def test_second_run_is_idempotent(database_url):
    with db_session(database_url) as session:
        ch07_data(session)
        migrate.run_migration(session, dry_run=False)
        after_first = snapshot(session)

        report = migrate.run_migration(session, dry_run=False)

        assert report["created"] == []
        assert report["merged"] == []
        assert report["moved_questions"] == 0
        # 未命中节点每次都会继续被报告为保留，但树与关联不变。
        assert snapshot(session) == after_first


def test_conflict_aborts_without_writing(database_url):
    with db_session(database_url) as session:
        data = ch07_data(session)
        # 一个非正式节点占用了「电化学」这个词，正式根节点就建不出来。
        add_point(session, "占位", aliases=["电化学"])
        session.commit()
        before = snapshot(session)

        report = migrate.run_migration(session, dry_run=False)

        assert report["applied"] is False
        assert report["conflicts"]
        assert any("电化学" in item for item in report["conflicts"])
        assert snapshot(session) == before
        assert data["electrolyte"] in snapshot(session)


def test_apply_rolls_back_on_error(database_url, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("合并失败")

    monkeypatch.setattr(knowledge, "_merge_points", boom)

    with db_session(database_url) as session:
        ch07_data(session)
        before = snapshot(session)

        with pytest.raises(RuntimeError):
            migrate.run_migration(session, dry_run=False)

        assert snapshot(session) == before
        assert "电化学" not in snapshot(session)


def test_cli_dry_run_apply_and_rerun(database_url, monkeypatch, capsys):
    with db_session(database_url) as session:
        ch07_data(session)

    monkeypatch.setenv("CHEMAI_DATABASE_URL", database_url)

    assert migrate.main(["--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "dry-run，未写入" in output
    assert "电解质 -> 电化学" in output
    assert "化学式与化合价 -> 物质结构" in output

    assert migrate.main(["--apply"]) == 0
    output = capsys.readouterr().out
    assert "已写入" in output

    with db_session(database_url) as session:
        tree = snapshot(session)
        assert "电化学" in tree
        assert "电解质" not in tree
        assert "化学式与化合价" not in tree

    assert migrate.main(["--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "合并临时节点：无" in output
