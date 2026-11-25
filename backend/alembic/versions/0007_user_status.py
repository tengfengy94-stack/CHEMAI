"""用户状态：离职/停用改状态，不删人

Revision ID: 0007_user_status
Revises: 0006_practice_answer
Create Date: 2026-11-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_user_status"
down_revision = "0006_practice_answer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
    )


def downgrade() -> None:
    op.drop_column("users", "status")
