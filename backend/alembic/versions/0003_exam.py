"""建考试表：卷子、卷内题目、作答记录、逐题作答

Revision ID: 0003_exam
Revises: 0002_auth
Create Date: 2026-11-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_exam"
down_revision = "0002_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "papers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "paper_questions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("paper_id", sa.Integer(), sa.ForeignKey("papers.id"), nullable=False),
        sa.Column("question_id", sa.Integer(), sa.ForeignKey("questions.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint("paper_id", "question_id", name="uq_paper_questions_paper_question"),
        sa.UniqueConstraint("paper_id", "position", name="uq_paper_questions_paper_position"),
    )
    op.create_index("ix_paper_questions_question_id", "paper_questions", ["question_id"])
    op.create_table(
        "answer_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("paper_id", sa.Integer(), sa.ForeignKey("papers.id"), nullable=False),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("class_id", sa.Integer(), sa.ForeignKey("classes.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("graded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("grading_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("paper_id", "student_id", name="uq_answer_records_paper_student"),
    )
    op.create_index("ix_answer_records_paper_id", "answer_records", ["paper_id"])
    op.create_index("ix_answer_records_student_id", "answer_records", ["student_id"])
    op.create_table(
        "answer_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("record_id", sa.Integer(), sa.ForeignKey("answer_records.id"), nullable=False),
        sa.Column("question_id", sa.Integer(), sa.ForeignKey("questions.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("student_answer", sa.Text(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.UniqueConstraint("record_id", "question_id", name="uq_answer_items_record_question"),
    )
    op.create_index("ix_answer_items_record_id", "answer_items", ["record_id"])


def downgrade() -> None:
    op.drop_table("answer_items")
    op.drop_table("answer_records")
    op.drop_table("paper_questions")
    op.drop_table("papers")
