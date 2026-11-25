"""数据结构。改这里之后必须写一条 Alembic 迁移，不靠启动时自动建表。"""
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.clock import utcnow


class Base(DeclarativeBase):
    pass


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
    # active / inactive；离职、停用改状态，不删人
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
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


class ReviewTask(Base):
    """一个学生对一道题的复习任务；级别 0–5，5 级出队但仍保留。"""

    __tablename__ = "review_tasks"
    __table_args__ = (
        UniqueConstraint("student_id", "question_id", name="uq_review_tasks_student_question"),
        Index("ix_review_tasks_student_due", "student_id", "due_on"),
        Index("ix_review_tasks_due_on", "due_on"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), nullable=False)
    # 0–5；5 级出队
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # UTC+8 业务日期；出队后为 NULL
    due_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    # 作答次数，同时作为并发条件更新的版本号
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # 最近一次复习答错；为后续错题来源扩展到复习预留
    last_wrong_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_wrong_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 最近一次触发入队的考试作答记录，用来识别重复通知
    last_wrong_attempt_id: Mapped[int | None] = mapped_column(
        ForeignKey("answer_records.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class PracticeRecord(Base):
    """练习作答记录：每答一道追加一条，只增不改。

    difficulty 是出题时实际给出的档位；候选放宽时可能不是学生的目标档。
    """

    __tablename__ = "practice_records"
    __table_args__ = (
        Index("ix_practice_records_student_id", "student_id", "id"),
        Index("ix_practice_records_question_id", "question_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), nullable=False)
    # 学生当时提交的答案；历史记录迁移时为空串
    student_answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 1 / 2 / 3
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class KnowledgePoint(Base):
    """知识点：parent_id 为空是根，指向根是第二层，不允许第三层。"""

    __tablename__ = "knowledge_points"
    __table_args__ = (
        UniqueConstraint("name", name="uq_knowledge_points_name"),
        Index("ix_knowledge_points_parent_id", "parent_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_points.id"), nullable=True
    )
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class KnowledgePointAlias(Base):
    """知识点的别名；全局唯一，改名与合并都往这里收旧叫法。"""

    __tablename__ = "knowledge_point_aliases"
    __table_args__ = (
        UniqueConstraint("alias", name="uq_knowledge_point_aliases_alias"),
        Index("ix_knowledge_point_aliases_point_id", "knowledge_point_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    knowledge_point_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_points.id"), nullable=False
    )
    alias: Mapped[str] = mapped_column(String(100), nullable=False)


class QuestionKnowledgePoint(Base):
    """题目与知识点的多对多关联。"""

    __tablename__ = "question_knowledge_points"
    __table_args__ = (
        UniqueConstraint(
            "question_id",
            "knowledge_point_id",
            name="uq_question_knowledge_points_question_point",
        ),
        Index("ix_question_knowledge_points_question_id", "question_id"),
        Index("ix_question_knowledge_points_point_id", "knowledge_point_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), nullable=False)
    knowledge_point_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_points.id"), nullable=False
    )
    # 主知识点：一题最多一个；统计仍按所有关联计数
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
