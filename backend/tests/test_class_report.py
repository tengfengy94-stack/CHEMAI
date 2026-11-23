"""班级报告：考试列表、提交情况、逐题正确率、知识点分布、学生表与权限（第 10 章）。"""
import pytest
from sqlalchemy import select

import app.events as events
from app.db import make_engine, make_session_factory
from app.models import User
from exam_helpers import (
    QUESTION,
    attempt_for_paper,
    make_approved,
    paper_with,
    publish,
    submit_answers,
)
from helpers import auth, login


@pytest.fixture
def setup(make_user, make_class):
    make_user("t1", role="teacher")
    make_user("t2", role="teacher")
    make_user("admin", role="admin")
    c1 = make_class("高一(1)班", "t1")
    c2 = make_class("高一(2)班", "t2")
    for index in range(1, 5):
        make_user(f"s{index}", role="student", class_id=c1)
    make_user("x1", role="student", class_id=c2)
    return {"c1": c1, "c2": c2}


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


def overview(client, token, class_id):
    r = client.get(f"/api/reports/classes/{class_id}", headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()["data"]


def exam_report(client, token, class_id, paper_id):
    return client.get(
        f"/api/reports/classes/{class_id}/exams/{paper_id}", headers=auth(token)
    )


def user_id(database_url, username):
    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    with factory() as session:
        uid = session.scalar(select(User.id).where(User.username == username))
    engine.dispose()
    return uid


def submit_with_grading_failure(client, student, paper_id, monkeypatch, answers=None):
    """交卷落库成功、判分失败：记录停在 submitted + 空分。"""
    attempt = attempt_for_paper(client, student, paper_id)
    started = client.post(f"/api/attempts/{attempt['id']}/start", headers=auth(student))
    assert started.status_code == 200, started.text
    original = list(events._handlers[events.ATTEMPT_GRADED])
    monkeypatch.setattr(
        events,
        "_handlers",
        {events.ATTEMPT_GRADED: [lambda **_kw: (_ for _ in ()).throw(RuntimeError("x"))]},
    )
    try:
        result = client.post(
            f"/api/attempts/{attempt['id']}/submit",
            headers=auth(student),
            json={"answers": answers or []},
        )
    finally:
        monkeypatch.setattr(events, "_handlers", {events.ATTEMPT_GRADED: original})
    assert result.status_code == 200, result.text
    return result.json()["data"]


def test_exam_list_is_scoped_to_published_class(client, setup, make_class):
    c1, c2 = setup["c1"], setup["c2"]
    t1 = login(client, "t1")
    t2 = login(client, "t2")
    admin = login(client, "admin")
    q1 = question(client, t1, "一班题")
    q2 = question(client, admin, "共享题")

    own = paper_with(client, t1, c1, [q1], "一班卷")
    shared = paper_with(client, admin, c1, [q2], "共享卷")
    published = publish(client, admin, shared["id"], c2)
    assert published.status_code == 200, published.text

    data = overview(client, t1, c1)
    assert data["exam_count"] == 2
    assert {item["paper_title"] for item in data["exams"]} == {"一班卷", "共享卷"}
    assert all(item["student_count"] == 4 for item in data["exams"])

    only_c2 = overview(client, t2, c2)
    assert only_c2["exam_count"] == 1
    assert only_c2["exams"][0]["paper_title"] == "共享卷"
    assert only_c2["exams"][0]["student_count"] == 1

    # 重复发布同一份卷子只补缺，不重复加人
    again = publish(client, admin, shared["id"], c1)
    assert again.status_code == 200, again.text
    after = overview(client, t1, c1)
    assert after["exam_count"] == 2
    assert next(
        item for item in after["exams"] if item["paper_title"] == "共享卷"
    )["student_count"] == 4

    empty = make_class("空班", "t2")
    empty_data = overview(client, t2, empty)
    assert empty_data["exam_count"] == 0
    assert empty_data["exams"] == []
    assert empty_data["knowledge_points"] == []
    assert empty_data["students"] == []
    assert own["id"] != shared["id"]


def test_submission_counts_and_unsubmitted_list(client, setup, monkeypatch):
    c1 = setup["c1"]
    t1 = login(client, "t1")
    s1, s2, s3, s4 = (login(client, f"s{i}") for i in range(1, 5))
    q = question(client, t1, "提交情况题")
    paper = paper_with(client, t1, c1, [q], "提交卷")

    submit_answers(
        client, s1, attempt_for_paper(client, s1, paper["id"]), {q["id"]: "A"}
    )
    s2_attempt = attempt_for_paper(client, s2, paper["id"])
    client.post(f"/api/attempts/{s2_attempt['id']}/start", headers=auth(s2))
    submit_with_grading_failure(client, s3, paper["id"], monkeypatch)

    data = exam_report(client, t1, c1, paper["id"]).json()["data"]
    assert data["submission"] == {
        "total": 4,
        "submitted": 2,
        "in_progress": 1,
        "pending": 1,
    }
    unsubmitted = {item["student_name"]: item["status"] for item in data["unsubmitted"]}
    assert unsubmitted == {"s2": "in_progress", "s4": "pending"}
    assert "s1" not in unsubmitted


def test_question_accuracy_uses_graded_denominator(client, setup, monkeypatch):
    c1 = setup["c1"]
    t1 = login(client, "t1")
    s1, s2, s3, s4 = (login(client, f"s{i}") for i in range(1, 5))
    q1 = question(client, t1, "第一题")
    q2 = question(client, t1, "第二题")
    paper = paper_with(client, t1, c1, [q1, q2], "正确率卷")

    submit_answers(
        client,
        s1,
        attempt_for_paper(client, s1, paper["id"]),
        {q1["id"]: "A", q2["id"]: "A"},
    )
    submit_answers(
        client,
        s2,
        attempt_for_paper(client, s2, paper["id"]),
        {q1["id"]: "A", q2["id"]: "B"},
    )
    submit_with_grading_failure(
        client,
        s3,
        paper["id"],
        monkeypatch,
        answers=[
            {"question_id": q1["id"], "answer": "A"},
            {"question_id": q2["id"], "answer": "A"},
        ],
    )

    data = exam_report(client, t1, c1, paper["id"]).json()["data"]
    assert [item["position"] for item in data["questions"]] == [1, 2]
    first, second = data["questions"]
    assert (first["graded_count"], first["correct_count"], first["correct_rate"]) == (
        2,
        2,
        100.0,
    )
    assert (second["graded_count"], second["correct_count"], second["correct_rate"]) == (
        2,
        1,
        50.0,
    )

    # 无人判分：分母为 0，正确率返回 null，前端显示「—」
    empty_paper = paper_with(client, t1, c1, [q1], "无人判分卷")
    empty = exam_report(client, t1, c1, empty_paper["id"]).json()["data"]
    assert empty["questions"][0]["graded_count"] == 0
    assert empty["questions"][0]["correct_rate"] is None


def test_blank_paper_counts_every_question_wrong(client, setup):
    c1 = setup["c1"]
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    q = question(client, t1, "白卷题")
    paper = paper_with(client, t1, c1, [q], "白卷")

    submit_answers(client, s1, attempt_for_paper(client, s1, paper["id"]), {})

    data = exam_report(client, t1, c1, paper["id"]).json()["data"]
    assert data["questions"][0]["graded_count"] == 1
    assert data["questions"][0]["correct_count"] == 0
    assert data["questions"][0]["correct_rate"] == 0.0


def test_knowledge_distribution_pools_and_student_wrong_count_dedupes(client, setup):
    c1 = setup["c1"]
    t1 = login(client, "t1")
    s1, s2 = login(client, "s1"), login(client, "s2")
    kp = point(client, t1, "氧化还原")
    questions = [question(client, t1, f"知识点题{i}") for i in range(4)]
    for q in questions:
        link(client, t1, q["id"], [kp["id"]])

    first = paper_with(client, t1, c1, questions, "四题卷")
    submit_answers(
        client,
        s1,
        attempt_for_paper(client, s1, first["id"]),
        {
            questions[0]["id"]: "A",
            questions[1]["id"]: "A",
            questions[2]["id"]: "A",
            questions[3]["id"]: "B",
        },
    )

    repeat = questions[3]
    for round_no in range(2):
        paper = paper_with(client, t1, c1, [repeat], f"重复错题卷{round_no}")
        submit_answers(
            client,
            s2,
            attempt_for_paper(client, s2, paper["id"]),
            {repeat["id"]: "B"},
        )

    data = overview(client, t1, c1)
    assert data["exam_count"] == 3
    assert data["knowledge_points"] == [
        {
            "knowledge_point_id": kp["id"],
            "name": "氧化还原",
            "answered_count": 6,
            "wrong_count": 3,
            "error_rate": 50.0,
        }
    ]

    students = {item["student_name"]: item for item in data["students"]}
    assert students["s1"]["latest_score"] == 75.0
    assert students["s1"]["wrong_count"] == 1
    assert students["s2"]["latest_score"] == 0.0
    assert students["s2"]["wrong_count"] == 1
    assert students["s3"]["latest_score"] is None
    assert students["s3"]["wrong_count"] == 0

    target = point(client, t1, "电化学")
    merged = client.post(
        f"/api/knowledge-points/{kp['id']}/merge",
        headers=auth(t1),
        json={"target_id": target["id"]},
    )
    assert merged.status_code == 200, merged.text
    after = overview(client, t1, c1)
    assert len(after["knowledge_points"]) == 1
    assert after["knowledge_points"][0]["knowledge_point_id"] == target["id"]
    assert after["knowledge_points"][0]["answered_count"] == 6
    assert after["knowledge_points"][0]["wrong_count"] == 3


def test_class_and_exam_report_permissions(client, setup):
    c1, c2 = setup["c1"], setup["c2"]
    t1, t2 = login(client, "t1"), login(client, "t2")
    admin = login(client, "admin")
    s1 = login(client, "s1")
    q = question(client, t1, "权限题")
    paper = paper_with(client, t1, c1, [q], "权限卷")
    other_q = question(client, t2, "二班题")
    other_paper = paper_with(client, t2, c2, [other_q], "二班卷")

    assert overview(client, t1, c1)["exam_count"] == 1
    assert client.get(f"/api/reports/classes/{c1}", headers=auth(t2)).status_code == 403
    assert client.get(f"/api/reports/classes/{c1}", headers=auth(s1)).status_code == 403
    assert overview(client, admin, c1)["exam_count"] == 1
    assert client.get("/api/reports/classes/99999", headers=auth(t1)).status_code == 404

    assert exam_report(client, t1, c1, paper["id"]).status_code == 200
    assert exam_report(client, t2, c1, paper["id"]).status_code == 403
    assert exam_report(client, s1, c1, paper["id"]).status_code == 403
    assert exam_report(client, admin, c1, paper["id"]).status_code == 200
    assert exam_report(client, t1, c1, 99999).status_code == 404
    assert exam_report(client, t1, c1, other_paper["id"]).status_code == 404


def test_class_report_excludes_practice_and_ungraded(client, setup, monkeypatch):
    c1 = setup["c1"]
    t1 = login(client, "t1")
    s1, s2, s3 = login(client, "s1"), login(client, "s2"), login(client, "s3")
    kp = point(client, t1, "化学平衡")
    q1 = question(client, t1, "班级题一")
    q2 = question(client, t1, "班级题二")
    link(client, t1, q1["id"], [kp["id"]])
    link(client, t1, q2["id"], [kp["id"]])
    paper = paper_with(client, t1, c1, [q1, q2], "数据范围卷")

    submit_answers(
        client,
        s1,
        attempt_for_paper(client, s1, paper["id"]),
        {q1["id"]: "A", q2["id"]: "B"},
    )
    practiced = client.post(
        "/api/practice/answers",
        headers=auth(s2),
        json={"question_id": q1["id"], "answer": "B", "difficulty": 2},
    )
    assert practiced.status_code == 200, practiced.text
    submit_with_grading_failure(
        client,
        s3,
        paper["id"],
        monkeypatch,
        answers=[
            {"question_id": q1["id"], "answer": "A"},
            {"question_id": q2["id"], "answer": "A"},
        ],
    )

    data = overview(client, t1, c1)
    assert data["knowledge_points"] == [
        {
            "knowledge_point_id": kp["id"],
            "name": "化学平衡",
            "answered_count": 2,
            "wrong_count": 1,
            "error_rate": 50.0,
        }
    ]
    students = {item["student_name"]: item for item in data["students"]}
    assert students["s1"]["latest_score"] == 50.0
    assert students["s1"]["grading_pending"] is False
    assert students["s3"]["latest_score"] is None
    assert students["s3"]["grading_pending"] is True


def test_class_students_mark_transferred_and_gate_report_link(
    client, setup, database_url, make_class
):
    c1, c2 = setup["c1"], setup["c2"]
    t1, t2 = login(client, "t1"), login(client, "t2")
    admin = login(client, "admin")
    s1 = login(client, "s1")
    q = question(client, t1, "转班题")
    paper = paper_with(client, t1, c1, [q], "转班卷")
    submit_answers(
        client, s1, attempt_for_paper(client, s1, paper["id"]), {q["id"]: "A"}
    )

    s1_id = user_id(database_url, "s1")
    s2_id = user_id(database_url, "s2")
    c3 = make_class("高一(3)班", "t1")

    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    with factory() as session:
        session.scalar(select(User).where(User.id == s1_id)).class_id = c2
        session.scalar(select(User).where(User.id == s2_id)).class_id = c3
        session.commit()
    engine.dispose()

    data = overview(client, t1, c1)
    students = {item["student_name"]: item for item in data["students"]}
    assert students["s1"]["latest_score"] == 100.0
    assert students["s1"]["is_current_member"] is False
    assert students["s1"]["can_view_report"] is False
    assert students["s2"]["is_current_member"] is False
    # 转到同一位老师别的班：原班历史行不再给报告入口，要从新班报告进。
    assert students["s2"]["can_view_report"] is False
    assert students["s3"]["is_current_member"] is True
    assert students["s3"]["can_view_report"] is True

    assert client.get(f"/api/reports/students/{s1_id}", headers=auth(t1)).status_code == 403
    assert client.get(f"/api/reports/students/{s1_id}", headers=auth(t2)).status_code == 200
    assert client.get(f"/api/reports/students/{s2_id}", headers=auth(t1)).status_code == 200
    assert client.get(f"/api/reports/students/{s1_id}", headers=auth(admin)).status_code == 200
