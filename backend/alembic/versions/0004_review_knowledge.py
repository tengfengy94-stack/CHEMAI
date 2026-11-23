"""建复习与知识点表，并把历史错题回填成第 0 级复习任务

Revision ID: 0004_review_knowledge
Revises: 0003_exam
Create Date: 2026-11-23
"""
from datetime import datetime, timedelta

from alembic import op
import sqlalchemy as sa

from app.clock import business_date_of

revision = "0004_review_knowledge"
down_revision = "0003_exam"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_points",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "parent_id",
            sa.Integer(),
            sa.ForeignKey("knowledge_points.id"),
            nullable=True,
        ),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_knowledge_points_name"),
    )
    op.create_index("ix_knowledge_points_parent_id", "knowledge_points", ["parent_id"])
    op.create_table(
        "knowledge_point_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "knowledge_point_id",
            sa.Integer(),
            sa.ForeignKey("knowledge_points.id"),
            nullable=False,
        ),
        sa.Column("alias", sa.String(100), nullable=False),
        sa.UniqueConstraint("alias", name="uq_knowledge_point_aliases_alias"),
    )
    op.create_index(
        "ix_knowledge_point_aliases_point_id",
        "knowledge_point_aliases",
        ["knowledge_point_id"],
    )
    op.create_table(
        "question_knowledge_points",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "question_id",
            sa.Integer(),
            sa.ForeignKey("questions.id"),
            nullable=False,
        ),
        sa.Column(
            "knowledge_point_id",
            sa.Integer(),
            sa.ForeignKey("knowledge_points.id"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "question_id",
            "knowledge_point_id",
            name="uq_question_knowledge_points_question_point",
        ),
    )
    op.create_index(
        "ix_question_knowledge_points_question_id",
        "question_knowledge_points",
        ["question_id"],
    )
    op.create_index(
        "ix_question_knowledge_points_point_id",
        "question_knowledge_points",
        ["knowledge_point_id"],
    )
    op.create_table(
        "review_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("question_id", sa.Integer(), sa.ForeignKey("questions.id"), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("review_count", sa.Integer(), nullable=False),
        sa.Column("last_answer", sa.Text(), nullable=True),
        sa.Column("last_answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_is_correct", sa.Boolean(), nullable=True),
        sa.Column("last_wrong_answer", sa.Text(), nullable=True),
        sa.Column("last_wrong_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_wrong_attempt_id",
            sa.Integer(),
            sa.ForeignKey("answer_records.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "student_id", "question_id", name="uq_review_tasks_student_question"
        ),
    )
    op.create_index(
        "ix_review_tasks_student_due", "review_tasks", ["student_id", "due_on"]
    )
    op.create_index("ix_review_tasks_due_on", "review_tasks", ["due_on"])

    # 回填：每个学生每题只取判分时间最晚的一条错误作答，建第 0 级任务。
    # 到期日复用 app.clock 的业务日期，不在迁移里另写一份 +8 规则。
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            """
            SELECT ar.student_id,
                   ai.question_id,
                   ar.id AS attempt_id,
                   coalesce(ar.graded_at, CURRENT_TIMESTAMP) AS graded_at
            FROM answer_items AS ai
            JOIN answer_records AS ar ON ar.id = ai.record_id
            WHERE ar.status = 'graded' AND ai.is_correct = 0
            ORDER BY ar.graded_at ASC, ar.id ASC
            """
        )
    ).mappings()
    latest = {}
    for row in rows:
        latest[(row["student_id"], row["question_id"])] = row

    for row in latest.values():
        graded_at = row["graded_at"]
        if isinstance(graded_at, str):
            graded_at = datetime.fromisoformat(graded_at.replace("Z", "+00:00"))
        due_on = (business_date_of(graded_at) + timedelta(days=1)).isoformat()
        conn.execute(
            sa.text(
                """
                INSERT INTO review_tasks (
                    student_id, question_id, level, due_on, review_count,
                    last_wrong_attempt_id, created_at, updated_at
                ) VALUES (
                    :student_id, :question_id, 0, :due_on, 0,
                    :attempt_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            ),
            {
                "student_id": row["student_id"],
                "question_id": row["question_id"],
                "due_on": due_on,
                "attempt_id": row["attempt_id"],
            },
        )


def downgrade() -> None:
    op.drop_table("review_tasks")
    op.drop_table("question_knowledge_points")
    op.drop_table("knowledge_point_aliases")
    op.drop_table("knowledge_points")
