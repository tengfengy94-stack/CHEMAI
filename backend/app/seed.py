"""首次启动、数据为空时插入种子班级、账号与题目。

班级和账号一个闸、题目一个闸：老开发库里有题没账号，启动后照样补上演示账号，
teacher01 才能登录看到那三条题。两个闸都只看各自的数据空不空，不重复插入。
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.models import Class, Question, User, utcnow

DEMO_PASSWORD = "chem2026"

# 老师 → 班级：teacher01 带两个班（设计/05 §4.1 的演示场景）
SEED_CLASS_NAMES = ("高一(1)班", "高一(2)班")
DEMO_TEACHER = "teacher01"

# 用户名、姓名、角色、学生归属的班
SEED_USERS = [
    ("admin", "管理员", "admin", None),
    (DEMO_TEACHER, "演示老师", "teacher", None),
    ("s0101", "陈小明", "student", "高一(1)班"),
    ("s0102", "林晓华", "student", "高一(1)班"),
    ("s0201", "王小雨", "student", "高一(2)班"),
]

SEED_QUESTIONS = [
    {
        "stem": "下列物质中属于电解质的是",
        "type": "single",
        "options": ["NaCl", "蔗糖", "CO2"],
        "answer": "A",
        "difficulty": 2,
        "status": "approved",
    },
    {
        "stem": "配平：Fe + O2 → Fe3O4",
        "type": "blank",
        "options": None,
        "answer": "3Fe + 2O2 → Fe3O4",
        "difficulty": 2,
        "status": "draft",
    },
    {
        "stem": "关于氧化还原反应，下列说法正确的是",
        "type": "multiple",
        "options": ["氧化剂得电子", "还原剂失电子", "化合价不变"],
        "answer": "AB",
        "difficulty": 3,
        "status": "pending",
    },
]


def seed_if_empty(session: Session) -> None:
    seed_users_if_empty(session)
    seed_questions_if_empty(session)


def seed_users_if_empty(session: Session) -> None:
    if session.scalar(select(func.count()).select_from(User)):
        return
    # 五个账号同一口演示密码，哈希只算一次
    password_hash = hash_password(DEMO_PASSWORD)
    users = {}
    for username, name, role, _class_name in SEED_USERS:
        user = User(
            username=username,
            name=name,
            role=role,
            class_id=None,
            password_hash=password_hash,
        )
        session.add(user)
        users[username] = user
    session.flush()  # 先拿到老师、学生的 id，班级表要引用

    teacher = users[DEMO_TEACHER]
    classes = {}
    for class_name in SEED_CLASS_NAMES:
        klass = Class(name=class_name, teacher_id=teacher.id)
        session.add(klass)
        classes[class_name] = klass
    session.flush()

    # 回填学生的班级归属
    for username, _name, _role, class_name in SEED_USERS:
        if class_name:
            users[username].class_id = classes[class_name].id
    session.commit()


def seed_questions_if_empty(session: Session) -> None:
    if session.scalar(select(func.count()).select_from(Question)):
        return
    # 三条用同一个时间，列表按 id 排出 ① 表格里的顺序 1、2、3
    now = utcnow()
    for item in SEED_QUESTIONS:
        session.add(Question(**item, explanation=None, created_by=DEMO_TEACHER, created_at=now))
    session.commit()
