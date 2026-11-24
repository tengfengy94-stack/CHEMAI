"""评测库夹具：可重复构建、工具数据齐全、引用解析、开发库隔离。"""
import hashlib

import pytest
from sqlalchemy import func, select

from app import attempts, class_reporting, practice, reporting, review
from app.config import DEFAULT_DATABASE_PATH
from app.db import make_engine, make_session_factory
from app.models import AnswerRecord, Class, KnowledgePoint, Question, ReviewTask, User
from evalkit.db import build_eval_database
from evalkit.references import (
    build_reference_index,
    question_exists,
    resolve_point,
    resolve_question,
)


def _counts(fixture):
    engine = make_engine(fixture.database_url)
    factory = make_session_factory(engine)
    try:
        with factory() as session:
            return {
                "users": session.scalar(select(func.count()).select_from(User)),
                "classes": session.scalar(select(func.count()).select_from(Class)),
                "points": session.scalar(select(func.count()).select_from(KnowledgePoint)),
                "questions": session.scalar(select(func.count()).select_from(Question)),
                "attempts": session.scalar(select(func.count()).select_from(AnswerRecord)),
                "reviews": session.scalar(select(func.count()).select_from(ReviewTask)),
            }
    finally:
        engine.dispose()


def test_build_eval_database_is_repeatable(tmp_path):
    path = tmp_path / "eval.db"
    first = build_eval_database(path)
    first_counts = _counts(first)
    second = build_eval_database(path)
    assert _counts(second) == first_counts
    assert first_counts["points"] == 7
    assert first_counts["questions"] == 15
    assert first_counts["users"] == 5
    assert first_counts["classes"] == 2
    assert first_counts["attempts"] == 3


def test_fixture_feeds_required_tools(tmp_path):
    fixture = build_eval_database(tmp_path / "eval.db")
    engine = make_engine(fixture.database_url)
    factory = make_session_factory(engine)
    try:
        with factory() as session:
            student = session.scalar(
                select(User).where(User.username == fixture.users["student"])
            )
            teacher = session.scalar(
                select(User).where(User.username == fixture.users["teacher"])
            )
            profile = reporting.student_report(session, student.id)
            assert profile["has_data"] is True
            names = [item["name"] for item in profile["items"]]
            assert "氧化还原" in names
            assert review.due_task_count(session, student.id) >= 2
            assert practice.consecutive_wrong_count(session, student.id) >= 3
            assert reporting.recent_scores(session, student.id)
            wrong = session.execute(
                attempts.wrong_questions_query(student)
            ).mappings().all()
            assert wrong
            overview = class_reporting.class_overview(
                session, fixture.classes["class_1"], teacher
            )
            assert overview["knowledge_points"]
            assert overview["students"]
    finally:
        engine.dispose()


def test_reference_resolver(tmp_path):
    fixture = build_eval_database(tmp_path / "eval.db")
    index = build_reference_index(fixture)

    assert resolve_point(index, "氧化还原")["id"] == fixture.points["氧化还原"]
    assert resolve_point(index, "氧化还原反应")["id"] == fixture.points["氧化还原"]
    assert resolve_point(index, "电解质")["id"] == fixture.points["电化学"]
    assert resolve_point(index, "不存在的知识点") is None
    assert resolve_question(index, "redox_wrong") == fixture.question_refs["redox_wrong"]
    assert resolve_question(index, "missing") is None
    assert question_exists(index, fixture.question_refs["redox_wrong"]) is True
    assert question_exists(index, 999999) is False


def test_build_does_not_touch_dev_database(tmp_path):
    if not DEFAULT_DATABASE_PATH.exists():
        pytest.skip("没有开发库")
    before = hashlib.sha256(DEFAULT_DATABASE_PATH.read_bytes()).hexdigest()
    build_eval_database(tmp_path / "eval.db")
    after = hashlib.sha256(DEFAULT_DATABASE_PATH.read_bytes()).hexdigest()
    assert before == after


def test_refuses_dev_database_path():
    with pytest.raises(ValueError):
        build_eval_database(DEFAULT_DATABASE_PATH)
