"""建班级与账号表，旧占位创建人改成 teacher01

Revision ID: 0002_auth
Revises: 0001_questions
Create Date: 2026-11-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_auth"
down_revision = "0001_questions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # classes 与 users 互相引用（users.class_id -> classes.id，classes.teacher_id -> users.id），
    # SQLite 建表分三步：先建 classes（teacher_id 暂为普通整数），
    # 再建 users（class_id 带外键），最后给 classes 补外键。
    op.create_table(
        "classes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("class_id", sa.Integer(), sa.ForeignKey("classes.id"), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    with op.batch_alter_table("classes") as batch:
        batch.create_foreign_key("fk_classes_teacher_id_users", "users", ["teacher_id"], ["id"])
    # 第 02 章的建题人写的是占位符"演示老师"，迁移后归到演示账号 teacher01
    op.execute("UPDATE questions SET created_by = 'teacher01' WHERE created_by = '演示老师'")


def downgrade() -> None:
    # questions.created_by 不回写占位值：旧代码已不读它
    op.drop_table("users")
    op.drop_table("classes")
