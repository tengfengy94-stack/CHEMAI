"""练习记录补学生答案，供错题清单三来源使用

Revision ID: 0006_practice_answer
Revises: 0005_practice
Create Date: 2026-11-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_practice_answer"
down_revision = "0005_practice"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "practice_records",
        sa.Column("student_answer", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("practice_records", "student_answer")
