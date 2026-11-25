"""知识点关联补主次标记

Revision ID: 0008_knowledge_primary
Revises: 0007_user_status
Create Date: 2026-11-25
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_knowledge_primary"
down_revision = "0007_user_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "question_knowledge_points",
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.create_index(
        "uq_question_knowledge_primary",
        "question_knowledge_points",
        ["question_id"],
        unique=True,
        sqlite_where=sa.text("is_primary = 1"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_question_knowledge_primary", table_name="question_knowledge_points"
    )
    op.drop_column("question_knowledge_points", "is_primary")
