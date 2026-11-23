"""0004 迁移：建复习/知识点表，回填历史错题，可完整回滚（第 07 章）。"""
import sqlite3

from alembic import command

from app.migrations import alembic_config


def _upgrade(url: str, revision: str) -> None:
    command.upgrade(alembic_config(url), revision)


def _downgrade(url: str, revision: str) -> None:
    command.downgrade(alembic_config(url), revision)


def _seed_graded_wrong(path, second_at: str) -> None:
    """在 0003 结构里插两条同题错答，后一条判分时间更晚。"""
    conn = sqlite3.connect(path)
    conn.executescript(
        f"""
        INSERT INTO classes (id, name, teacher_id) VALUES (1, '高一(1)班', 1);
        INSERT INTO users (id, username, name, role, class_id, password_hash)
        VALUES (1, 't1', '老师', 'teacher', NULL, 'x');
        INSERT INTO users (id, username, name, role, class_id, password_hash)
        VALUES (2, 's1', '学生', 'student', 1, 'x');
        INSERT INTO questions
            (id, stem, type, options, answer, explanation, difficulty, status, created_by, created_at)
        VALUES
            (1, '电解质', 'single', '["NaCl","蔗糖","CO2"]', 'A', NULL, 2, 'approved', 't1',
             '2026-11-20 08:00:00.000000');
        INSERT INTO papers (id, title, status, created_by, created_at)
        VALUES (1, '第一次', 'published', 't1', '2026-11-20 08:00:00.000000');
        INSERT INTO papers (id, title, status, created_by, created_at)
        VALUES (2, '第二次', 'published', 't1', '2026-11-21 08:00:00.000000');
        INSERT INTO answer_records
            (id, paper_id, student_id, class_id, status, score, graded_at, created_at)
        VALUES
            (1, 1, 2, 1, 'graded', 0.0, '2026-11-21 15:30:00.000000',
             '2026-11-21 15:00:00.000000');
        INSERT INTO answer_records
            (id, paper_id, student_id, class_id, status, score, graded_at, created_at)
        VALUES
            (2, 2, 2, 1, 'graded', 0.0, '{second_at}',
             '2026-11-22 15:00:00.000000');
        INSERT INTO answer_items
            (id, record_id, question_id, position, student_answer, is_correct)
        VALUES (1, 1, 1, 1, 'B', 0);
        INSERT INTO answer_items
            (id, record_id, question_id, position, student_answer, is_correct)
        VALUES (2, 2, 1, 1, 'C', 0);
        """
    )
    conn.commit()
    conn.close()


def test_backfill_keeps_latest_wrong_attempt(tmp_path):
    path = tmp_path / "migrate.db"
    url = f"sqlite:///{path.as_posix()}"
    _upgrade(url, "0003_exam")
    # 第一条 15:30 UTC = 23:30 UTC+8，次日是 22 日；
    # 后一条 16:30 UTC 已跨到 UTC+8 的 22 日，次日是 23 日。回填应取后一条。
    _seed_graded_wrong(path, "2026-11-21 16:30:00.000000")

    _upgrade(url, "head")

    conn = sqlite3.connect(path)
    rows = conn.execute(
        "SELECT student_id, question_id, level, due_on, review_count, last_wrong_attempt_id "
        "FROM review_tasks"
    ).fetchall()
    conn.close()

    assert rows == [(2, 1, 0, "2026-11-23", 0, 2)]


def test_downgrade_drops_only_new_tables(tmp_path):
    path = tmp_path / "rollback.db"
    url = f"sqlite:///{path.as_posix()}"
    _upgrade(url, "0003_exam")
    _seed_graded_wrong(path, "2026-11-21 16:30:00.000000")
    _upgrade(url, "head")
    _downgrade(url, "0003_exam")

    conn = sqlite3.connect(path)
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    for table in (
        "review_tasks",
        "question_knowledge_points",
        "knowledge_point_aliases",
        "knowledge_points",
    ):
        assert table not in tables
    assert conn.execute("SELECT count(*) FROM questions").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM papers").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM answer_records").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM answer_items").fetchone()[0] == 2
    conn.close()
