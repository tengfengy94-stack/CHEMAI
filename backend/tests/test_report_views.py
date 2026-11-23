"""学生报告：掌握度、最近五次分数、待复习数、无数据与老师下钻（第 10 章）。"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import app.events as events
from app import clock
from app.db import make_engine, make_session_factory
from app.models import AnswerRecord, ReviewTask, User
from exam_helpers import (
    QUESTION,
    attempt_for_paper,
    make_approved,
    paper_with,
    submit_answers,
)
from helpers import auth, login


@pytest.fixture
def classroom(make_user, make_class):
    make_user("t1", role="teacher")
    make_user("admin", role="admin")
    class_id = make_class("高一(1)班", "t1")
    make_user("s1", role="student", class_id=class_id)
    return class_id


@pytest.fixture
def two_classes(make_user, make_class):
    make_user("t1", role="teacher")
    make_user("t2", role="teacher")
    make_user("admin", role="admin")
    c1 = make_class("高一(1)班", "t1")
    c2 = make_class("高一(2)班", "t2")
    make_user("s1", role="student", class_id=c1)
    make_user("s2", role="student", class_id=c2)
    return c1, c2


def point(client, token, name):
    r = client.post("/api/knowledge-points", headers=auth(token), json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["data"]


def link(client, token, question_id, point_ids):
    r = client.put(
        f"/api/questions/{question_id}/knowledge-points",
        headers=auth(token),
        json={"knowledge_point_ids": point_ids},
    )
    assert r.status_code == 200, r.text


def question(client, token, stem, answer="A"):
    return make_approved(client, token, **{**QUESTION, "stem": stem, "answer": answer})


def take(client, teacher, student, class_id, questions, answers, title):
    paper = paper_with(client, teacher, class_id, questions, title)
    attempt = attempt_for_paper(client, student, paper["id"])
    return submit_answers(client, student, attempt, answers), paper


def my_report(client, token):
    r = client.get("/api/reports/me", headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()["data"]


def student_report(client, token, student_id):
    return client.get(f"/api/reports/students/{student_id}", headers=auth(token))


def user_id(database_url, username):
    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    with factory() as session:
        uid = session.scalar(select(User.id).where(User.username == username))
    engine.dispose()
    return uid


def test_mastery_is_equal_weight_across_points(client, classroom):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    names = ["氧化还原", "电化学", "化学平衡", "物质结构", "元素周期律"]
    points = {name: point(client, t1, name) for name in names}

    # 设计 §4.5 的示例：8/5、6/3、4/2、2/0、1/1（最后一行样本不够）
    specs = [
        ("氧化还原", 8, 3),
        ("电化学", 6, 3),
        ("化学平衡", 4, 2),
        ("物质结构", 2, 2),
        ("元素周期律", 1, 0),
    ]
    questions = []
    answers = {}
    for name, answered, correct in specs:
        for index in range(answered):
            q = question(client, t1, f"{name}{index}")
            link(client, t1, q["id"], [points[name]["id"]])
            questions.append(q)
            answers[q["id"]] = "A" if index < correct else "B"

    take(client, t1, s1, classroom, questions, answers, "掌握度卷")

    data = my_report(client, s1)
    assert data["has_data"] is True
    assert data["mastery"] == {"value": 59.4, "has_data": True}
    assert [item["name"] for item in data["items"]] == ["氧化还原", "电化学", "化学平衡"]


def test_all_correct_point_has_mastery_but_is_not_weak(client, classroom):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    kp = point(client, t1, "元素周期律")
    q1 = question(client, t1, "周期一")
    q2 = question(client, t1, "周期二")
    link(client, t1, q1["id"], [kp["id"]])
    link(client, t1, q2["id"], [kp["id"]])

    take(client, t1, s1, classroom, [q1, q2], {q1["id"]: "A", q2["id"]: "A"}, "全对卷")

    data = my_report(client, s1)
    assert data["mastery"] == {"value": 100.0, "has_data": True}
    assert data["items"] == []


def test_sample_below_two_has_no_mastery(client, classroom):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    kp = point(client, t1, "电化学")
    q = question(client, t1, "只答一次")
    link(client, t1, q["id"], [kp["id"]])

    take(client, t1, s1, classroom, [q], {q["id"]: "B"}, "样本不足卷")

    data = my_report(client, s1)
    assert data["has_data"] is True
    assert data["mastery"] == {"value": 0.0, "has_data": False}
    assert data["items"] == []


def test_multi_point_question_counts_in_each_point(client, classroom):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    a = point(client, t1, "氧化还原")
    b = point(client, t1, "电化学")
    q = question(client, t1, "同时考两个点")
    link(client, t1, q["id"], [a["id"], b["id"]])

    take(client, t1, s1, classroom, [q], {q["id"]: "B"}, "多知识点一")
    take(client, t1, s1, classroom, [q], {q["id"]: "B"}, "多知识点二")

    data = my_report(client, s1)
    assert data["mastery"] == {"value": 0.0, "has_data": True}
    assert {item["name"]: item["answered_count"] for item in data["items"]} == {
        "氧化还原": 2,
        "电化学": 2,
    }


def test_practice_counts_toward_mastery(client, classroom):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    kp = point(client, t1, "化学平衡")
    q = question(client, t1, "练习计入")
    link(client, t1, q["id"], [kp["id"]])

    for answer in ("B", "A"):
        r = client.post(
            "/api/practice/answers",
            headers=auth(s1),
            json={"question_id": q["id"], "answer": answer, "difficulty": 2},
        )
        assert r.status_code == 200, r.text

    data = my_report(client, s1)
    assert data["mastery"] == {"value": 50.0, "has_data": True}
    assert data["items"][0]["answered_count"] == 2
    assert data["items"][0]["wrong_count"] == 1


def test_review_answer_does_not_count(client, classroom):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    kp = point(client, t1, "物质结构")
    q = question(client, t1, "复习不计")
    link(client, t1, q["id"], [kp["id"]])
    take(client, t1, s1, classroom, [q], {q["id"]: "B"}, "复习不计卷")

    tasks = client.get("/api/review/tasks?scope=all", headers=auth(s1)).json()["data"]["items"]
    assert len(tasks) == 1
    answered = client.post(
        f"/api/review/tasks/{tasks[0]['id']}/answer",
        headers=auth(s1),
        json={"student_answer": "A"},
    )
    assert answered.status_code == 200, answered.text

    data = my_report(client, s1)
    assert data["mastery"] == {"value": 0.0, "has_data": False}
    assert data["items"] == []


def test_ungraded_record_is_not_counted(client, classroom, monkeypatch):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    kp = point(client, t1, "化学平衡")
    q = question(client, t1, "判分失败")
    link(client, t1, q["id"], [kp["id"]])
    paper = paper_with(client, t1, classroom, [q], "判分失败卷")
    attempt = attempt_for_paper(client, s1, paper["id"])

    original = list(events._handlers[events.ATTEMPT_GRADED])
    monkeypatch.setattr(
        events,
        "_handlers",
        {events.ATTEMPT_GRADED: [lambda **_kw: (_ for _ in ()).throw(RuntimeError("x"))]},
    )
    client.post(f"/api/attempts/{attempt['id']}/start", headers=auth(s1))
    client.post(
        f"/api/attempts/{attempt['id']}/submit",
        headers=auth(s1),
        json={"answers": [{"question_id": q["id"], "answer": "B"}]},
    )
    monkeypatch.setattr(events, "_handlers", {events.ATTEMPT_GRADED: original})

    data = my_report(client, s1)
    assert data["has_data"] is False
    assert data["mastery"] == {"value": 0.0, "has_data": False}
    assert data["recent_scores"] == []
    assert data["review_due_count"] == 0


def test_recent_scores_takes_last_five_and_orders_by_time(client, classroom, database_url):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    paper_titles = []
    for index in range(6):
        q = question(client, t1, f"分数题{index}")
        title = f"第{index + 1}次"
        _, paper = take(client, t1, s1, classroom, [q], {q["id"]: "A"}, title)
        paper_titles.append((paper["id"], title))

    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    with factory() as session:
        records = session.scalars(select(AnswerRecord)).all()
        by_paper = {record.paper_id: record for record in records}
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for index, (paper_id, _title) in enumerate(paper_titles):
            by_paper[paper_id].graded_at = base + timedelta(days=index)
        session.commit()
    engine.dispose()

    data = my_report(client, s1)
    assert [item["paper_title"] for item in data["recent_scores"]] == [
        "第2次",
        "第3次",
        "第4次",
        "第5次",
        "第6次",
    ]
    assert [item["score"] for item in data["recent_scores"]] == [100.0] * 5


def test_recent_scores_tie_breaks_by_record_id(client, classroom, database_url):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    for index in range(3):
        q = question(client, t1, f"同秒题{index}")
        take(client, t1, s1, classroom, [q], {q["id"]: "A"}, f"同秒{index}")

    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    with factory() as session:
        for record in session.scalars(select(AnswerRecord)).all():
            record.graded_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        session.commit()
    engine.dispose()

    data = my_report(client, s1)
    assert [item["paper_title"] for item in data["recent_scores"]] == ["同秒0", "同秒1", "同秒2"]


def test_due_count_includes_today_and_overdue_only(client, classroom, database_url):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    questions = [make_approved(client, t1, **{**QUESTION, "stem": f"待复习{i}"}) for i in range(4)]
    today = clock.business_today()

    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    with factory() as session:
        uid = session.scalar(select(User.id).where(User.username == "s1"))
        session.add_all(
            [
                ReviewTask(student_id=uid, question_id=questions[0]["id"], level=0, due_on=today),
                ReviewTask(
                    student_id=uid,
                    question_id=questions[1]["id"],
                    level=2,
                    due_on=today - timedelta(days=1),
                ),
                ReviewTask(
                    student_id=uid,
                    question_id=questions[2]["id"],
                    level=1,
                    due_on=today + timedelta(days=1),
                ),
                ReviewTask(
                    student_id=uid,
                    question_id=questions[3]["id"],
                    level=5,
                    due_on=None,
                ),
            ]
        )
        session.commit()
    engine.dispose()

    data = my_report(client, s1)
    assert data["review_due_count"] == 2


def test_me_rejects_teacher_and_admin_and_requires_login(client, classroom):
    t1 = login(client, "t1")
    admin = login(client, "admin")

    assert client.get("/api/reports/me").status_code == 401
    assert client.get("/api/reports/me", headers=auth(t1)).status_code == 403
    assert client.get("/api/reports/me", headers=auth(admin)).status_code == 403


def test_teacher_drilldown_is_scoped_to_current_class(client, two_classes, database_url):
    c1, c2 = two_classes
    t1 = login(client, "t1")
    t2 = login(client, "t2")
    admin = login(client, "admin")
    s1 = login(client, "s1")
    s2 = login(client, "s2")
    s1_id = user_id(database_url, "s1")
    s2_id = user_id(database_url, "s2")

    assert student_report(client, t1, s1_id).status_code == 200
    assert student_report(client, t1, s2_id).status_code == 403
    assert student_report(client, s2, s1_id).status_code == 403
    assert student_report(client, s1, s1_id).status_code == 200
    assert student_report(client, admin, s2_id).status_code == 200
    assert student_report(client, admin, 99999).status_code == 404

    # 转班后，学生个人报告跟着当前班级走；原班老师不再能下钻。
    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    with factory() as session:
        session.scalar(select(User).where(User.id == s1_id)).class_id = c2
        session.commit()
    engine.dispose()

    assert student_report(client, t1, s1_id).status_code == 403
    assert student_report(client, t2, s1_id).status_code == 200
