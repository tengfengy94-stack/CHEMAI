"""三条权限规则的判定级测试（tasks 3.2）。

六条越权用例里四条在本章没有接口可打，先打判定函数；接口随作答（第 05 章）、
班级报告（第 07 章）出现后升级为接口级，判定函数不动（design.md 决策 5）。
"""
import pytest
from sqlalchemy import select

from app.auth import AccessDeniedError, require_own_class, require_owner, require_self_data
from app.db import make_engine, make_session_factory
from app.models import Class, User


@pytest.fixture
def db(database_url):
    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    yield factory
    engine.dispose()


def add_user(db, **kwargs):
    with db() as session:
        session.add(User(**kwargs))
        session.commit()


def get_user(db, username):
    with db() as session:
        return session.scalar(select(User).where(User.username == username))


# ---- 规则① 只能改自己建的 ----

def test_teacher_cannot_modify_others_question(db):
    """越权用例：老师改别人的题。"""
    add_user(db, username="teacher_a", name="甲", role="teacher", password_hash="占位")
    add_user(db, username="teacher_b", name="乙", role="teacher", password_hash="占位")
    other = get_user(db, "teacher_a")
    me = get_user(db, "teacher_b")
    with pytest.raises(AccessDeniedError):
        require_owner(other.username, me)


def test_owner_passes_own_question(db):
    add_user(db, username="teacher_a", name="甲", role="teacher", password_hash="占位")
    owner = get_user(db, "teacher_a")
    require_owner(owner.username, owner)


def test_admin_is_not_limited_by_owner_rule(db):
    """管理员不受规则①限制（设计/01 §6.3 全通）。"""
    add_user(db, username="admin", name="管理员", role="admin", password_hash="占位")
    require_owner("别人的题", get_user(db, "admin"))


# ---- 规则② 只能看自己的 ----

def test_student_cannot_read_others_data(db):
    """越权用例：学生读别人的数据。"""
    add_user(db, username="s0101", name="甲", role="student", password_hash="占位")
    add_user(db, username="s0102", name="乙", role="student", password_hash="占位")
    me = get_user(db, "s0101")
    with pytest.raises(AccessDeniedError):
        require_self_data("s0102", me)


def test_student_cannot_modify_others_answers(db):
    """越权用例：学生改别人的答案。"""
    add_user(db, username="s0101", name="甲", role="student", password_hash="占位")
    add_user(db, username="s0102", name="乙", role="student", password_hash="占位")
    me = get_user(db, "s0101")
    with pytest.raises(AccessDeniedError):
        require_self_data("s0102", me)


def test_self_data_passes_for_owner(db):
    add_user(db, username="s0101", name="甲", role="student", password_hash="占位")
    me = get_user(db, "s0101")
    require_self_data("s0101", me)


def test_admin_reads_any_student_data(db):
    add_user(db, username="admin", name="管理员", role="admin", password_hash="占位")
    require_self_data("随便谁", get_user(db, "admin"))


# ---- 规则③ 只能看自己带的班 ----

def make_class_for(db, name, teacher_username):
    with db() as session:
        teacher = session.scalar(select(User).where(User.username == teacher_username))
        klass = Class(name=name, teacher_id=teacher.id)
        session.add(klass)
        session.commit()
        return klass.id


def test_teacher_cannot_view_other_class(db):
    """越权用例：老师看别班。"""
    add_user(db, username="teacher_a", name="甲", role="teacher", password_hash="占位")
    add_user(db, username="teacher_b", name="乙", role="teacher", password_hash="占位")
    mine_id = make_class_for(db, "a的班", "teacher_a")
    other_id = make_class_for(db, "b的班", "teacher_b")
    me = get_user(db, "teacher_a")
    session = db()
    try:
        require_own_class(mine_id, me, session)
        with pytest.raises(AccessDeniedError):
            require_own_class(other_id, me, session)
    finally:
        session.close()


def test_student_cannot_use_class_rule(db):
    add_user(db, username="teacher_a", name="甲", role="teacher", password_hash="占位")
    class_id = make_class_for(db, "a的班", "teacher_a")
    add_user(db, username="s0101", name="学生", role="student", class_id=class_id, password_hash="占位")
    me = get_user(db, "s0101")
    session = db()
    try:
        with pytest.raises(AccessDeniedError):
            require_own_class(class_id, me, session)
    finally:
        session.close()


def test_admin_sees_any_class(db):
    add_user(db, username="teacher_a", name="甲", role="teacher", password_hash="占位")
    class_id = make_class_for(db, "a的班", "teacher_a")
    add_user(db, username="admin", name="管理员", role="admin", password_hash="占位")
    admin = get_user(db, "admin")
    session = db()
    try:
        require_own_class(class_id, admin, session)
    finally:
        session.close()
