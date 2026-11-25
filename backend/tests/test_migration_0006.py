"""0006 迁移：练习记录补 student_answer，可回滚。"""
import sqlite3

from alembic import command

from app.migrations import alembic_config


def _upgrade(url: str, revision: str) -> None:
    command.upgrade(alembic_config(url), revision)


def _downgrade(url: str, revision: str) -> None:
    command.downgrade(alembic_config(url), revision)


def test_practice_answer_column_exists_with_default(tmp_path):
    path = tmp_path / "answer.db"
    url = f"sqlite:///{path.as_posix()}"
    _upgrade(url, "head")

    conn = sqlite3.connect(path)
    columns = {
        row[1]: row[4] for row in conn.execute("PRAGMA table_info(practice_records)")
    }
    conn.close()

    assert "student_answer" in columns
    assert columns["student_answer"] in ("", "''")


def test_downgrade_removes_practice_answer_column(tmp_path):
    path = tmp_path / "rollback.db"
    url = f"sqlite:///{path.as_posix()}"
    _upgrade(url, "head")
    _downgrade(url, "0005_practice")

    conn = sqlite3.connect(path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(practice_records)")}
    conn.close()

    assert "student_answer" not in columns
