"""0007 迁移：users 增加 status，默认 active，可回滚。"""
import sqlite3

from alembic import command

from app.migrations import alembic_config


def _upgrade(url: str, revision: str) -> None:
    command.upgrade(alembic_config(url), revision)


def _downgrade(url: str, revision: str) -> None:
    command.downgrade(alembic_config(url), revision)


def test_user_status_column_exists_with_active_default(tmp_path):
    path = tmp_path / "status.db"
    url = f"sqlite:///{path.as_posix()}"
    _upgrade(url, "head")

    conn = sqlite3.connect(path)
    columns = {
        row[1]: row[4] for row in conn.execute("PRAGMA table_info(users)")
    }
    conn.close()

    assert "status" in columns
    assert columns["status"] in ("'active'", "active")


def test_downgrade_removes_user_status(tmp_path):
    path = tmp_path / "rollback.db"
    url = f"sqlite:///{path.as_posix()}"
    _upgrade(url, "head")
    _downgrade(url, "0006_practice_answer")

    conn = sqlite3.connect(path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    conn.close()

    assert "status" not in columns
