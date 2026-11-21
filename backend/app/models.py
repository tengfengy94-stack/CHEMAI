"""数据结构。改这里之后必须写一条 Alembic 迁移，不靠启动时自动建表。"""
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
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


class Paper(Base):
    """一份卷子。只有草稿和已发布两态，发布后内容只读。"""

    __tablename__ = "papers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    # draft / published
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class PaperQuestion(Base):
    """卷内题目。顺序就是加入顺序，position 从 1 开始。"""

    __tablename__ = "paper_questions"
    __table_args__ = (
        UniqueConstraint("paper_id", "question_id", name="uq_paper_questions_paper_question"),
        UniqueConstraint("paper_id", "position", name="uq_paper_questions_paper_position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"), nullable=False)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class AnswerRecord(Base):
    """一个学生一份卷子的作答记录。卷子和学生组合唯一，班级是发布时的快照。"""

    __tablename__ = "answer_records"
    __table_args__ = (
        UniqueConstraint("paper_id", "student_id", name="uq_answer_records_paper_student"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    # 发布时学生所在的班；学生之后转班不改这里
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False)
    # pending / in_progress / submitted / graded
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    # NULL 表示未判分；0.0 是合法分数
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 交卷/重试判分的租约；不是状态，用来防并发重判
    grading_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class AnswerItem(Base):
    """逐题作答。交卷时每题一条，未答写空串；判分前 is_correct 为 NULL。"""

    __tablename__ = "answer_items"
    __table_args__ = (
        UniqueConstraint("record_id", "question_id", name="uq_answer_items_record_question"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("answer_records.id"), nullable=False)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    student_answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
