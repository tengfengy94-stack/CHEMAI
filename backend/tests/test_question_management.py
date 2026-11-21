"""题库管理：编辑、审核流转、删除、筛选分页与角色范围（第 04 章）。"""
import pytest

from app.db import make_engine, make_session_factory
from app.models import Question, utcnow
from helpers import auth, login

QUESTION = {
    "stem": "下列物质中属于电解质的是",
    "type": "single",
    "options": ["NaCl", "蔗糖", "CO2"],
    "answer": "A",
    "explanation": "电解质在水里能电离",
    "difficulty": 2,
}


def create(client, token, **changes):
    r = client.post("/api/questions", headers=auth(token), json={**QUESTION, **changes})
    assert r.status_code == 201, r.text
    return r.json()["data"]


def put_question(client, token, question_id, **changes):
    return client.put(
        f"/api/questions/{question_id}",
        headers=auth(token),
        json={**QUESTION, **changes},
    )


def set_status(client, token, question_id, status):
    return client.post(
        f"/api/questions/{question_id}/status",
        headers=auth(token),
        json={"status": status},
    )


@pytest.fixture
def bulk_insert(database_url):
    """直接往库里插题，避开逐条建题的校验开销。"""
    def _make(created_by, count, status="draft", difficulty=2):
        engine = make_engine(database_url)
        factory = make_session_factory(engine)
        with factory() as session:
            now = utcnow()
            for i in range(count):
                session.add(
                    Question(
                        stem=f"批量题{i + 1}",
                        type="blank",
                        options=None,
                        answer="x",
                        explanation=None,
                        difficulty=difficulty,
                        status=status,
                        created_by=created_by,
                        created_at=now,
                    )
                )
            session.commit()
        engine.dispose()

    return _make


@pytest.fixture
def teacher_with_questions(client, make_user, database_url):
    """t1 名下有 3 道题：草稿/难度2、已通过/难度3、待复核/难度3。"""
    make_user("t1", role="teacher")
    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    rows = [
        ("氧化还原基础", 2, "draft"),
        ("电化学入门", 3, "approved"),
        ("氧化还原进阶", 3, "pending"),
    ]
    with factory() as session:
        for stem, difficulty, status in rows:
            session.add(
                Question(
                    stem=stem,
                    type="blank",
                    options=None,
                    answer="x",
                    explanation=None,
                    difficulty=difficulty,
                    status=status,
                    created_by="t1",
                )
            )
        session.commit()
    engine.dispose()
    return login(client, "t1")


# ---- 编辑（任务 1.2）----

def test_edit_draft_question_saves_content(client, make_user):
    make_user("t1", role="teacher")
    token = login(client, "t1")
    q = create(client, token)
    r = put_question(client, token, q["id"], stem="改过的题干", answer="B")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["stem"] == "改过的题干"
    assert data["answer"] == "B"
    assert data["status"] == "draft"


def test_edit_normalizes_answer(client, make_user):
    make_user("t1", role="teacher")
    token = login(client, "t1")
    q = create(client, token)
    r = put_question(
        client, token, q["id"], type="multiple", options=["甲", "乙", "丙"], answer="C,A"
    )
    assert r.json()["data"]["answer"] == "AC"


def test_edit_pending_question_keeps_status(client, make_user):
    make_user("t1", role="teacher")
    token = login(client, "t1")
    q = create(client, token)
    set_status(client, token, q["id"], "pending")
    r = put_question(client, token, q["id"], stem="待复核也能改")
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "pending"


def test_edit_approved_question_rejected(client, make_user):
    make_user("t1", role="teacher")
    token = login(client, "t1")
    q = create(client, token)
    set_status(client, token, q["id"], "approved")
    r = put_question(client, token, q["id"], stem="想改已通过")
    assert r.status_code == 409
    assert "已通过的题不能修改" in r.json()["error"]


def test_edit_others_question_rejected(client, make_user):
    make_user("t1", role="teacher")
    make_user("t2", role="teacher")
    q = create(client, login(client, "t1"))
    r = put_question(client, login(client, "t2"), q["id"], stem="改别人的")
    assert r.status_code == 403
    assert "不是这道题的创建者" in r.json()["error"]


def test_admin_can_edit_others_question(client, make_user):
    make_user("t1", role="teacher")
    make_user("admin", role="admin")
    q = create(client, login(client, "t1"))
    r = put_question(client, login(client, "admin"), q["id"], stem="管理员改的")
    assert r.status_code == 200
    assert r.json()["data"]["stem"] == "管理员改的"


def test_edit_nonexistent_question_404(client, make_user):
    make_user("t1", role="teacher")
    token = login(client, "t1")
    r = client.put("/api/questions/99999", headers=auth(token), json=QUESTION)
    assert r.status_code == 404
    assert r.json()["error"] == "题目不存在"


# ---- 审核流转（任务 1.3）----

def test_draft_to_pending(client, make_user):
    make_user("t1", role="teacher")
    token = login(client, "t1")
    q = create(client, token)
    r = set_status(client, token, q["id"], "pending")
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "pending"


def test_draft_directly_to_approved(client, make_user):
    make_user("t1", role="teacher")
    token = login(client, "t1")
    q = create(client, token)
    r = set_status(client, token, q["id"], "approved")
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "approved"


def test_pending_to_approved(client, make_user):
    make_user("t1", role="teacher")
    token = login(client, "t1")
    q = create(client, token)
    set_status(client, token, q["id"], "pending")
    r = set_status(client, token, q["id"], "approved")
    assert r.json()["data"]["status"] == "approved"


def test_pending_cannot_repeat_pending(client, make_user):
    make_user("t1", role="teacher")
    token = login(client, "t1")
    q = create(client, token)
    set_status(client, token, q["id"], "pending")
    r = set_status(client, token, q["id"], "pending")
    assert r.status_code == 409
    assert "不能这样改状态" in r.json()["error"]


def test_approved_cannot_change_status(client, make_user):
    make_user("t1", role="teacher")
    token = login(client, "t1")
    q = create(client, token)
    set_status(client, token, q["id"], "approved")
    r = set_status(client, token, q["id"], "pending")
    assert r.status_code == 409
    assert "已通过的题不能再改状态" in r.json()["error"]


def test_back_to_draft_is_not_a_supported_action(client, make_user):
    make_user("t1", role="teacher")
    token = login(client, "t1")
    q = create(client, token)
    set_status(client, token, q["id"], "pending")
    r = set_status(client, token, q["id"], "draft")
    assert r.status_code == 422
    assert "审核状态格式不对" in r.json()["error"]


def test_non_creator_cannot_review(client, make_user):
    make_user("t1", role="teacher")
    make_user("t2", role="teacher")
    q = create(client, login(client, "t1"))
    r = set_status(client, login(client, "t2"), q["id"], "approved")
    assert r.status_code == 403
    assert "不是这道题的创建者" in r.json()["error"]


def test_student_cannot_review(client, make_user):
    make_user("t1", role="teacher")
    make_user("s1", role="student")
    q = create(client, login(client, "t1"))
    r = set_status(client, login(client, "s1"), q["id"], "approved")
    assert r.status_code == 403


# ---- 删除与使用检查（任务 1.4）----

def test_delete_unused_question(client, make_user):
    make_user("t1", role="teacher")
    token = login(client, "t1")
    q = create(client, token)
    r = client.delete(f"/api/questions/{q['id']}", headers=auth(token))
    assert r.status_code == 200
    assert client.get("/api/questions", headers=auth(token)).json()["data"]["total"] == 0


def test_usage_reports_zero_papers(client, make_user):
    make_user("t1", role="teacher")
    token = login(client, "t1")
    q = create(client, token)
    r = client.get(f"/api/questions/{q['id']}/usage", headers=auth(token))
    assert r.status_code == 200
    assert r.json()["data"] == {"papers": 0}


def test_non_creator_cannot_delete(client, make_user):
    make_user("t1", role="teacher")
    make_user("t2", role="teacher")
    q = create(client, login(client, "t1"))
    r = client.delete(f"/api/questions/{q['id']}", headers=auth(login(client, "t2")))
    assert r.status_code == 403
    assert "不是这道题的创建者" in r.json()["error"]


def test_delete_nonexistent_404(client, make_user):
    make_user("t1", role="teacher")
    token = login(client, "t1")
    r = client.delete("/api/questions/99999", headers=auth(token))
    assert r.status_code == 404


# ---- 筛选与分页（任务 2.1、2.2）----

def test_filter_by_difficulty(client, teacher_with_questions):
    data = client.get(
        "/api/questions", params={"difficulty": 3}, headers=auth(teacher_with_questions)
    ).json()["data"]
    assert {q["stem"] for q in data["items"]} == {"电化学入门", "氧化还原进阶"}
    assert data["total"] == 2


def test_filter_by_status(client, teacher_with_questions):
    data = client.get(
        "/api/questions", params={"status": "draft"}, headers=auth(teacher_with_questions)
    ).json()["data"]
    assert [q["stem"] for q in data["items"]] == ["氧化还原基础"]


def test_filter_by_keyword(client, teacher_with_questions):
    data = client.get(
        "/api/questions", params={"q": "氧化还原"}, headers=auth(teacher_with_questions)
    ).json()["data"]
    assert {q["stem"] for q in data["items"]} == {"氧化还原基础", "氧化还原进阶"}


def test_filters_combine(client, teacher_with_questions):
    data = client.get(
        "/api/questions",
        params={"difficulty": 3, "status": "pending"},
        headers=auth(teacher_with_questions),
    ).json()["data"]
    assert [q["stem"] for q in data["items"]] == ["氧化还原进阶"]


def test_pagination_returns_total_and_second_page(client, make_user, bulk_insert):
    make_user("t1", role="teacher")
    bulk_insert("t1", 25)
    token = login(client, "t1")
    page1 = client.get("/api/questions", params={"page": 1}, headers=auth(token)).json()["data"]
    page2 = client.get("/api/questions", params={"page": 2}, headers=auth(token)).json()["data"]
    assert page1["total"] == 25 and len(page1["items"]) == 20
    assert page2["total"] == 25 and [q["stem"] for q in page2["items"]] == [
        "批量题21", "批量题22", "批量题23", "批量题24", "批量题25",
    ]
    assert page1["page_size"] == 20


def test_invalid_filters_rejected(client, teacher_with_questions):
    token = teacher_with_questions
    assert client.get("/api/questions", params={"difficulty": 4}, headers=auth(token)).status_code == 422
    assert client.get("/api/questions", params={"status": "bogus"}, headers=auth(token)).status_code == 422
    assert client.get("/api/questions", params={"page": 0}, headers=auth(token)).status_code == 422


# ---- 筛选不得越过角色范围（任务 2.1）----

def test_student_cannot_get_drafts_even_with_filter(client, make_user, bulk_insert):
    make_user("t1", role="teacher")
    make_user("s1", role="student")
    bulk_insert("t1", 2, status="draft")
    bulk_insert("t1", 1, status="approved")
    token = login(client, "s1")
    data = client.get(
        "/api/questions", params={"status": "draft"}, headers=auth(token)
    ).json()["data"]
    assert data["items"] == [] and data["total"] == 0


def test_teacher_keyword_cannot_reach_colleagues_questions(client, make_user, bulk_insert):
    make_user("t1", role="teacher")
    make_user("t2", role="teacher")
    bulk_insert("t1", 1, status="draft")
    token = login(client, "t2")
    data = client.get(
        "/api/questions", params={"q": "批量题"}, headers=auth(token)
    ).json()["data"]
    assert data["items"] == []


def test_unknown_role_is_rejected(client, make_user):
    make_user("ghost", role="guest")
    token = login(client, "ghost")
    r = client.get("/api/questions", headers=auth(token))
    assert r.status_code == 403
    assert r.json()["data"] is None
