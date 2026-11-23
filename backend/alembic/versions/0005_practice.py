"""建练习记录表

Revision ID: 0005_practice
Revises: 0004_review_knowledge
Create Date: 2026-11-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_practice"
down_revision = "0004_review_knowledge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "practice_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("question_id", sa.Integer(), sa.ForeignKey("questions.id"), nullable=False),
        sa.Column("difficulty", sa.Integer(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_practice_records_student_id",
        "practice_records",
        ["student_id", "id"],
    )
    op.create_index(
        "ix_practice_records_question_id",
        "practice_records",
        ["question_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_practice_records_question_id", table_name="practice_records")
    op.drop_index("ix_practice_records_student_id", table_name="practice_records")
    op.drop_table("practice_records")
