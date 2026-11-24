"""评测专用数据库与固定夹具。

不碰开发库：路径必须与 chemai.db 不同，每轮先删后建。
"""
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config, knowledge, knowledge_migrate
from app.clock import business_today, utcnow
from app.db import make_engine, make_session_factory
from app.migrations import upgrade_to_head
from app.models import (
    AnswerItem,
    AnswerRecord,
    Class,
    KnowledgePoint,
    Paper,
    PaperQuestion,
    PracticeRecord,
    Question,
    QuestionKnowledgePoint,
    ReviewTask,
    User,
)
from app.seed import (
    DEMO_PASSWORD,
    DEMO_TEACHER,
    SEED_CLASS_NAMES,
    SEED_USERS,
    seed_if_empty,
)


@dataclass
class EvalFixture:
    database_url: str
    password: str = DEMO_PASSWORD
    users: dict[str, str] = field(default_factory=dict)
    classes: dict[str, int] = field(default_factory=dict)
    points: dict[str, int] = field(default_factory=dict)
    question_refs: dict[str, int] = field(default_factory=dict)
    question_stems: dict[str, str] = field(default_factory=dict)


# key -> 题目定义；knowledge 是正式词表里的名字。
QUESTION_DEFS = (
    {
        "key": "redox_1",
        "stem": "氧化还原反应中，氧化剂在反应中",
        "type": "single",
        "options": ["得电子", "失电子", "被氧化", "化合价升高"],
        "answer": "A",
        "explanation": "氧化剂得电子、化合价降低，本身被还原。",
        "difficulty": 2,
        "point": "氧化还原",
    },
    {
        "key": "redox_2",
        "stem": "下列反应属于氧化还原反应的是",
        "type": "single",
        "options": ["Fe + CuSO4 → FeSO4 + Cu", "NaOH + HCl → NaCl + H2O", "CaCO3 → CaO + CO2", "CO2 + H2O → H2CO3"],
        "answer": "A",
        "explanation": "只有 A 有元素化合价变化。",
        "difficulty": 2,
        "point": "氧化还原",
    },
    {
        "key": "redox_3",
        "stem": "配平：Fe + O2 → Fe3O4",
        "type": "blank",
        "options": None,
        "answer": "3Fe + 2O2 → Fe3O4",
        "explanation": "按得失电子守恒配平。",
        "difficulty": 3,
        "point": "氧化还原",
    },
    {
        "key": "redox_wrong",
        "stem": "关于氧化还原反应，下列说法正确的是",
        "type": "multiple",
        "options": ["氧化剂得电子", "还原剂失电子", "化合价不变"],
        "answer": "AB",
        "explanation": "氧化剂得电子、还原剂失电子，化合价一定变化。",
        "difficulty": 3,
        "point": "氧化还原",
    },
    {
        "key": "redox_easy",
        "stem": "氧化还原反应中，还原剂在反应中",
        "type": "single",
        "options": ["失电子", "得电子", "被还原", "化合价降低"],
        "answer": "A",
        "explanation": "还原剂失电子、化合价升高，本身被氧化。",
        "difficulty": 1,
        "point": "氧化还原",
    },
    {
        "key": "add_review_target",
        "stem": "氧化还原反应中，还原剂的性质是",
        "type": "single",
        "options": ["还原性", "氧化性", "酸性", "碱性"],
        "answer": "A",
        "explanation": "还原剂具有还原性，反应中被氧化。",
        "difficulty": 2,
        "point": "氧化还原",
    },
    {
        "key": "equilibrium_1",
        "stem": "化学平衡移动的方向取决于",
        "type": "single",
        "options": ["浓度、压强和温度的变化", "反应物的颜色", "催化剂用量", "容器大小"],
        "answer": "A",
        "explanation": "勒夏特列原理描述外界条件变化对平衡的影响。",
        "difficulty": 2,
        "point": "化学平衡",
    },
    {
        "key": "equilibrium_2",
        "stem": "升高温度对吸热反应平衡的影响是",
        "type": "single",
        "options": ["向正反应方向移动", "向逆反应方向移动", "不移动", "无法判断"],
        "answer": "A",
        "explanation": "升温向吸热方向移动。",
        "difficulty": 3,
        "point": "化学平衡",
    },
    {
        "key": "structure_1",
        "stem": "氯化钠的化学式是",
        "type": "blank",
        "options": None,
        "answer": "NaCl",
        "explanation": "钠显 +1 价，氯显 -1 价。",
        "difficulty": 1,
        "point": "物质结构",
    },
    {
        "key": "structure_2",
        "stem": "下列物质属于共价化合物的是",
        "type": "single",
        "options": ["NaCl", "HCl", "NaOH", "K2O"],
        "answer": "B",
        "explanation": "HCl 由共用电子对形成，是共价化合物。",
        "difficulty": 2,
        "point": "物质结构",
    },
    {
        "key": "electrochem_1",
        "stem": "原电池中负极发生的是",
        "type": "single",
        "options": ["氧化反应", "还原反应", "中和反应", "复分解反应"],
        "answer": "A",
        "explanation": "负极失电子，发生氧化反应。",
        "difficulty": 2,
        "point": "电化学",
    },
    {
        "key": "periodic_1",
        "stem": "同周期元素从左到右原子半径的变化是",
        "type": "single",
        "options": ["逐渐减小", "逐渐增大", "先增大后减小", "不变"],
        "answer": "A",
        "explanation": "核电荷数增大，原子半径逐渐减小。",
        "difficulty": 2,
        "point": "元素周期律",
    },
)

# 正式词表之外的别名，用来覆盖“别名也算真实存在”。
ALIASES = {
    "氧化还原": ["氧化还原反应"],
    "电化学": ["电解质", "电离"],
    "物质结构": ["化学式与化合价", "化学式"],
}


def eval_database_path() -> Path:
    return config.PROJECT_ROOT / "chemai-eval.db"


def _reset_sqlite_files(path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            candidate.unlink()


def _point_id(session: Session, name: str) -> int:
    found = session.scalar(select(KnowledgePoint).where(KnowledgePoint.name == name))
    assert found is not None, f"缺少知识点：{name}"
    return found.id


def _insert_questions(session: Session, teacher: User) -> dict[str, int]:
    refs: dict[str, int] = {}
    point_ids = {
        name: _point_id(session, name)
        for name in {item["point"] for item in QUESTION_DEFS}
    }
    for item in QUESTION_DEFS:
        question = Question(
            stem=item["stem"],
            type=item["type"],
            options=item["options"],
            answer=item["answer"],
            explanation=item["explanation"],
            difficulty=item["difficulty"],
            status="approved",
            created_by=teacher.username,
            created_at=utcnow(),
        )
        session.add(question)
        session.flush()
        session.add(
            QuestionKnowledgePoint(
                question_id=question.id,
                knowledge_point_id=point_ids[item["point"]],
            )
        )
        refs[item["key"]] = question.id
    session.flush()
    return refs


def _insert_paper(
    session: Session,
    *,
    title: str,
    teacher: User,
    question_ids: list[int],
) -> Paper:
    paper = Paper(
        title=title,
        status="published",
        created_by=teacher.username,
        created_at=utcnow(),
    )
    session.add(paper)
    session.flush()
    for position, question_id in enumerate(question_ids, start=1):
        session.add(
            PaperQuestion(
                paper_id=paper.id,
                question_id=question_id,
                position=position,
            )
        )
    session.flush()
    return paper


def _insert_attempt(
    session: Session,
    *,
    paper: Paper,
    student: User,
    class_id: int,
    status: str,
    score: float | None = None,
    answers: list[tuple[int, str, bool | None]] | None = None,
) -> AnswerRecord:
    now = utcnow()
    record = AnswerRecord(
        paper_id=paper.id,
        student_id=student.id,
        class_id=class_id,
        status=status,
        score=score,
        started_at=now - timedelta(hours=1),
        submitted_at=now if status in {"submitted", "graded"} else None,
        graded_at=now if status == "graded" else None,
        created_at=now - timedelta(hours=1),
    )
    session.add(record)
    session.flush()
    for position, (question_id, student_answer, is_correct) in enumerate(
        answers or [], start=1
    ):
        session.add(
            AnswerItem(
                record_id=record.id,
                question_id=question_id,
                position=position,
                student_answer=student_answer,
                is_correct=is_correct,
            )
        )
    session.flush()
    return record


def seed_eval_fixture(session: Session) -> EvalFixture:
    """在已跑过 seed_if_empty 的会话里补评测数据。"""
    teacher = session.scalar(select(User).where(User.username == DEMO_TEACHER))
    assert teacher is not None, "缺少教师种子账号"

    knowledge_migrate.run_migration(session)
    for name, aliases in ALIASES.items():
        point_id = _point_id(session, name)
        knowledge.update_point(session, point_id, name=None, aliases=aliases)

    teacher = session.scalar(select(User).where(User.username == DEMO_TEACHER))
    question_refs = _insert_questions(session, teacher)

    # seed_if_empty 建的第 1 题是已通过题，挂到电化学，保证三个工具都有数据。
    seed_approved = session.scalar(
        select(Question).where(Question.status == "approved").order_by(Question.id)
    )
    electrochem_id = _point_id(session, "电化学")
    if seed_approved is not None:
        session.add(
            QuestionKnowledgePoint(
                question_id=seed_approved.id,
                knowledge_point_id=electrochem_id,
            )
        )
        session.flush()

    students = {
        row.username: row
        for row in session.scalars(
            select(User).where(User.role == "student").order_by(User.id)
        ).all()
    }
    classes = {
        row.name: row
        for row in session.scalars(select(Class).order_by(Class.id)).all()
    }
    class_one = classes[SEED_CLASS_NAMES[0]]
    class_two = classes[SEED_CLASS_NAMES[1]]
    student_names = [
        username for username, _name, role, _class_name in SEED_USERS if role == "student"
    ]
    student = students[student_names[0]]
    other_student = students[student_names[1]]
    exam_student = students[student_names[2]]

    monthly = _insert_paper(
        session,
        title="第一次月考",
        teacher=teacher,
        question_ids=[
            question_refs["redox_wrong"],
            question_refs["structure_1"],
            question_refs["equilibrium_1"],
        ],
    )
    _insert_attempt(
        session,
        paper=monthly,
        student=student,
        class_id=class_one.id,
        status="graded",
        score=60.0,
        answers=[
            (question_refs["redox_wrong"], "C", False),
            (question_refs["structure_1"], "NaCl", True),
            (question_refs["equilibrium_1"], "A", True),
        ],
    )
    _insert_attempt(
        session,
        paper=monthly,
        student=other_student,
        class_id=class_one.id,
        status="graded",
        score=80.0,
        answers=[
            (question_refs["redox_wrong"], "AB", True),
            (question_refs["structure_1"], "NaCl", True),
            (question_refs["equilibrium_1"], "A", False),
        ],
    )
    in_progress = _insert_paper(
        session,
        title="第二次月考",
        teacher=teacher,
        question_ids=[question_refs["redox_1"]],
    )
    _insert_attempt(
        session,
        paper=in_progress,
        student=exam_student,
        class_id=class_two.id,
        status="in_progress",
    )

    # 练习记录：弱项 + 连续答错三次，最后三条都是错的。
    practice = (
        ("equilibrium_2", True),
        ("redox_1", True),
        ("structure_1", True),
        ("equilibrium_1", False),
        ("redox_2", False),
        ("redox_3", False),
    )
    for key, is_correct in practice:
        session.add(
            PracticeRecord(
                student_id=student.id,
                question_id=question_refs[key],
                difficulty=2,
                is_correct=is_correct,
                created_at=utcnow(),
            )
        )

    today = business_today()
    for key, level, due in (
        ("redox_1", 0, today - timedelta(days=1)),
        ("structure_1", 1, today),
        ("equilibrium_1", 0, today + timedelta(days=1)),
    ):
        session.add(
            ReviewTask(
                student_id=student.id,
                question_id=question_refs[key],
                level=level,
                due_on=due,
            )
        )

    session.commit()

    return EvalFixture(
        database_url="",
        users={
            "student": student.username,
            "exam_student": exam_student.username,
            "teacher": DEMO_TEACHER,
        },
        classes={"class_1": class_one.id, "class_2": class_two.id},
        points={
            name: _point_id(session, name)
            for name in ("氧化还原", "电化学", "化学平衡", "物质结构", "元素周期律", "氧化剂", "还原剂")
        },
        question_refs=question_refs,
        question_stems={item["key"]: item["stem"] for item in QUESTION_DEFS},
    )


def build_eval_database(path: Path | None = None) -> EvalFixture:
    """删除并重建评测库，返回夹具引用。"""
    target = (path or eval_database_path()).resolve()
    if target == config.DEFAULT_DATABASE_PATH.resolve():
        raise ValueError("不能拿开发库当评测库")
    _reset_sqlite_files(target)
    url = f"sqlite:///{target.as_posix()}"
    upgrade_to_head(url)
    engine = make_engine(url)
    factory = make_session_factory(engine)
    try:
        with factory() as session:
            seed_if_empty(session)
            fixture = seed_eval_fixture(session)
    finally:
        engine.dispose()
    fixture.database_url = url
    return fixture
