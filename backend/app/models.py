"""数据结构。改这里之后必须写一条 Alembic 迁移，不靠启动时自动建表。"""
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Class(Base):
    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    # 班主任：一个老师可带多个班；环形外键，迁移里最后一步补约束
    teacher_id: Mapped[int] = mapped_column(Integer, nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    # teacher / student / admin
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    # 学生归属的班；老师、管理员为 NULL
    class_id: Mapped[int | None] = mapped_column(ForeignKey("classes.id"), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    # single / multiple / blank
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    # 选择题：选项文字按 A、B、C 顺序的列表；填空题：NULL
    options: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    # 已按 answers.normalize_answer 整理过
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 1 / 2 / 3
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False)
    # draft / pending / approved
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    # 第 03 章改成关联用户
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
