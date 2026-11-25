"""0008 迁移：知识点关联补 is_primary 与部分唯一索引，可回滚。"""
import sqlite3

from alembic import command

from app.migrations import alembic_config


def _upgrade(url: str, revision: str) -> None:
    command.upgrade(alembic_config(url), revision)


def _downgrade(url: str, revision: str) -> None:
    command.downgrade(alembic_config(url), revision)


def test_primary_column_and_partial_index_exist(tmp_path):
    path = tmp_path / "primary.db"
    url = f"sqlite:///{path.as_posix()}"
    _upgrade(url, "head")

    conn = sqlite3.connect(path)
    columns = {
        row[1]: row[4]
        for row in conn.execute("PRAGMA table_info(question_knowledge_points)")
    }
    indexes = {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
    }
    conn.close()

    assert "is_primary" in columns
    assert columns["is_primary"] in ("0", "'0'")
    assert "uq_question_knowledge_primary" in indexes


def test_downgrade_removes_primary_column(tmp_path):
    path = tmp_path / "rollback.db"
    url = f"sqlite:///{path.as_posix()}"
    _upgrade(url, "head")
    _downgrade(url, "0007_user_status")

    conn = sqlite3.connect(path)
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(question_knowledge_points)")
    }
    conn.close()

    assert "is_primary" not in columns
