"""0005 迁移：建练习记录表，可完整回滚（第 09 章）。"""
import sqlite3

from alembic import command

from app.migrations import alembic_config


def _upgrade(url: str, revision: str) -> None:
    command.upgrade(alembic_config(url), revision)


def _downgrade(url: str, revision: str) -> None:
    command.downgrade(alembic_config(url), revision)


def test_practice_table_and_indexes_exist(tmp_path):
    path = tmp_path / "practice.db"
    url = f"sqlite:///{path.as_posix()}"
    _upgrade(url, "head")

    conn = sqlite3.connect(path)
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    indexes = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
    }
    columns = {row[1] for row in conn.execute("PRAGMA table_info(practice_records)")}
    foreign_keys = {
        (row[3], row[2])
        for row in conn.execute("PRAGMA foreign_key_list(practice_records)")
    }
    conn.close()

    assert "practice_records" in tables
    assert {
        "ix_practice_records_student_id",
        "ix_practice_records_question_id",
    } <= indexes
    assert columns == {
        "id",
        "student_id",
        "question_id",
        "difficulty",
        "is_correct",
        "created_at",
    }
    assert foreign_keys == {("student_id", "users"), ("question_id", "questions")}


def test_downgrade_drops_only_practice_table(tmp_path):
    path = tmp_path / "rollback.db"
    url = f"sqlite:///{path.as_posix()}"
    _upgrade(url, "head")
    _downgrade(url, "0004_review_knowledge")

    conn = sqlite3.connect(path)
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    conn.close()

    assert "practice_records" not in tables
    for table in ("questions", "papers", "answer_records", "answer_items", "review_tasks"):
        assert table in tables
