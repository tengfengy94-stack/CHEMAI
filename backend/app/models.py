"""数据结构。改这里之后必须写一条 Alembic 迁移，不靠启动时自动建表。"""
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
