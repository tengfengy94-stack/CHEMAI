"""题库接口的角色分叉（tasks 3.1）：老师只看自己建的、学生只看已通过且无答案字段、管理员全量。"""
import pytest

from app.db import make_engine, make_session_factory
from app.models import Question
from helpers import auth, login

QUESTION = {
    "stem": "下列物质中属于电解质的是",
    "type": "single",
    "options": ["NaCl", "蔗糖", "CO2"],
    "answer": "A",
    "explanation": "电解质在水里能电离",
    "difficulty": 2,
}


@pytest.fixture
def insert_question(database_url):
    """直接往库里写指定状态的题，模拟老师审过、发过之后的真实数据。"""
    def _make(created_by, status, stem=QUESTION["stem"]):
        engine = make_engine(database_url)
        factory = make_session_factory(engine)
        with factory() as session:
            session.add(
                Question(
                    stem=stem,
                    type="blank",
                    options=None,
                    answer="NaCl",
                    explanation="解析内容",
                    difficulty=2,
                    status=status,
                    created_by=created_by,
                )
            )
            session.commit()
        engine.dispose()

    return _make


def test_teacher_sees_only_own_questions(client, make_user):
    make_user("teacher_a", role="teacher")
    make_user("teacher_b", role="teacher")
    token_a = login(client, "teacher_a")
    token_b = login(client, "teacher_b")
    r = client.post("/api/questions", headers=auth(token_a), json=QUESTION)
    assert r.status_code == 201
    client.post("/api/questions", headers=auth(token_b), json={**QUESTION, "stem": "b 的题"})

    stems_a = [q["stem"] for q in client.get("/api/questions", headers=auth(token_a)).json()["data"]]
    stems_b = [q["stem"] for q in client.get("/api/questions", headers=auth(token_b)).json()["data"]]
    assert stems_a == [QUESTION["stem"]]
    assert stems_b == ["b 的题"]


def test_student_sees_only_approved_questions(client, make_user, insert_question):
    make_user("t", role="teacher")
    make_user("s", role="student")
    insert_question("t", "draft", "草稿题")
    insert_question("t", "pending", "待复核题")
    insert_question("t", "approved", "已通过题")

    token_s = login(client, "s")
    data = client.get("/api/questions", headers=auth(token_s)).json()["data"]
    assert [q["stem"] for q in data] == ["已通过题"]


def test_student_entries_have_no_answer_or_explanation(client, make_user, insert_question):
    make_user("t", role="teacher")
    make_user("s", role="student")
    insert_question("t", "approved")

    token_s = login(client, "s")
    q = client.get("/api/questions", headers=auth(token_s)).json()["data"][0]
    assert "answer" not in q
    assert "explanation" not in q


def test_teacher_entries_keep_answer_and_explanation(client, make_user, insert_question):
    make_user("t", role="teacher")
    insert_question("t", "approved")
    token_t = login(client, "t")
    q = client.get("/api/questions", headers=auth(token_t)).json()["data"][0]
    assert q["answer"] == "NaCl"
    assert q["explanation"] == "解析内容"


def test_admin_sees_all_questions(client, make_user, insert_question):
    make_user("t", role="teacher")
    insert_question("t", "draft")
    insert_question("t", "pending")
    insert_question("t", "approved")
    make_user("admin", role="admin")

    token_admin = login(client, "admin")
    data = client.get("/api/questions", headers=auth(token_admin)).json()["data"]
    assert [q["status"] for q in data] == ["approved", "pending", "draft"]


def test_student_cannot_create_question(client, make_user):
    make_user("s", role="student")
    token_s = login(client, "s")
    r = client.post("/api/questions", headers=auth(token_s), json=QUESTION)
    assert r.status_code == 403
    assert r.json()["data"] is None
    assert r.json()["error"]


def test_admin_can_create_question(client, make_user):
    make_user("admin", role="admin")
    token_admin = login(client, "admin")
    r = client.post("/api/questions", headers=auth(token_admin), json=QUESTION)
    assert r.status_code == 201
    assert r.json()["data"]["created_by"] == "admin"


def test_created_question_belongs_to_creator(client, make_user):
    """规则① 的赋值面：建题归属当前用户（spec：建题归属创建者）。"""
    make_user("teacher_a", role="teacher")
    token_a = login(client, "teacher_a")
    r = client.post("/api/questions", headers=auth(token_a), json=QUESTION)
    assert r.json()["data"]["created_by"] == "teacher_a"
