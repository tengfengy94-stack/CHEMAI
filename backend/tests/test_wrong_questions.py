"""错题清单：按学生 + 题去重、最近答案、排序、来源与可见范围（第 06 章）。"""
import pytest
from sqlalchemy import select

import app.routes as routes
from app import review
from app.models import User
from exam_helpers import (
    BLANK_QUESTION,
    MULTIPLE_QUESTION,
    QUESTION,
    attempt_for_paper,
    make_approved,
    paper_with,
    wrong_questions as wrong_list,
)
from helpers import auth, login


@pytest.fixture
def classroom(make_user, make_class):
    make_user("t1", role="teacher")
    make_user("admin", role="admin")
    class_id = make_class("高一(1)班", "t1")
    make_user("s1", role="student", class_id=class_id)
    make_user("s2", role="student", class_id=class_id)
    return class_id


def submit(client, token, attempt, answers):
    started = client.post(f"/api/attempts/{attempt['id']}/start", headers=auth(token))
    assert started.status_code == 200, started.text
    result = client.post(
        f"/api/attempts/{attempt['id']}/submit",
        headers=auth(token),
        json={"answers": answers},
    )
    assert result.status_code == 200, result.text
    return result.json()["data"]


def by_question(items, question_id):
    return next(item for item in items if item["question_id"] == question_id)


def test_wrong_list_dedups_by_question_and_keeps_latest(client, classroom):
    t1 = login(client, "t1")
    single = make_approved(client, t1, **QUESTION)
    first_paper = paper_with(client, t1, classroom, [single], "第一次周测")
    second_paper = paper_with(client, t1, classroom, [single], "第二次周测")

    s1 = login(client, "s1")
    first = attempt_for_paper(client, s1, first_paper["id"])
    submit(client, s1, first, [{"question_id": single["id"], "answer": "B"}])
    second = attempt_for_paper(client, s1, second_paper["id"])
    submit(client, s1, second, [{"question_id": single["id"], "answer": "C"}])

    items = wrong_list(client, s1)
    assert len(items) == 1
    item = items[0]
    assert item["question_id"] == single["id"]
    assert item["student_answer"] == "C"
    assert item["paper_title"] == "第二次周测"
    assert item["attempt_id"] == second["id"]


def test_wrong_list_orders_by_latest_wrong(client, classroom):
    t1 = login(client, "t1")
    first_question = make_approved(client, t1, **QUESTION)
    second_question = make_approved(
        client, t1, **{**QUESTION, "stem": "另一道电解质题", "answer": "B"}
    )
    first_paper = paper_with(client, t1, classroom, [first_question], "先考的卷")
    second_paper = paper_with(client, t1, classroom, [second_question], "后考的卷")

    s1 = login(client, "s1")
    first = attempt_for_paper(client, s1, first_paper["id"])
    submit(client, s1, first, [{"question_id": first_question["id"], "answer": "C"}])
    second = attempt_for_paper(client, s1, second_paper["id"])
    submit(client, s1, second, [{"question_id": second_question["id"], "answer": "C"}])

    items = wrong_list(client, s1)
    assert [item["question_id"] for item in items] == [
        second_question["id"],
        first_question["id"],
    ]
    assert items[0]["paper_title"] == "后考的卷"


def test_correct_answer_does_not_remove_wrong_question(client, classroom):
    t1 = login(client, "t1")
    single = make_approved(client, t1, **QUESTION)
    wrong_paper = paper_with(client, t1, classroom, [single], "错卷")
    correct_paper = paper_with(client, t1, classroom, [single], "对卷")

    s1 = login(client, "s1")
    wrong_attempt = attempt_for_paper(client, s1, wrong_paper["id"])
    submit(client, s1, wrong_attempt, [{"question_id": single["id"], "answer": "B"}])
    correct_attempt = attempt_for_paper(client, s1, correct_paper["id"])
    result = submit(
        client, s1, correct_attempt, [{"question_id": single["id"], "answer": "A"}]
    )
    assert result["score"] == 100.0

    items = wrong_list(client, s1)
    assert len(items) == 1
    assert items[0]["student_answer"] == "B"
    assert items[0]["paper_title"] == "错卷"
    assert items[0]["attempt_id"] == wrong_attempt["id"]


def test_wrong_question_fields_and_blank_answer(client, classroom):
    t1 = login(client, "t1")
    single = make_approved(client, t1, **QUESTION)
    multiple = make_approved(client, t1, **MULTIPLE_QUESTION)
    blank = make_approved(client, t1, **BLANK_QUESTION)
    paper = paper_with(client, t1, classroom, [single, multiple, blank], "三题型卷")

    s1 = login(client, "s1")
    attempt = attempt_for_paper(client, s1, paper["id"])
    result = submit(
        client,
        s1,
        attempt,
        [
            {"question_id": single["id"], "answer": "B"},
            {"question_id": multiple["id"], "answer": "A"},
        ],
    )
    assert result["score"] == 0.0

    items = wrong_list(client, s1)
    assert len(items) == 3

    single_item = by_question(items, single["id"])
    assert single_item["stem"] == QUESTION["stem"]
    assert single_item["type"] == "single"
    assert single_item["options"] == QUESTION["options"]
    assert single_item["student_answer"] == "B"
    assert single_item["answer"] == "A"
    assert single_item["explanation"] == QUESTION["explanation"]
    assert single_item["source"] == "exam"
    assert single_item["paper_id"] == paper["id"]
    assert single_item["paper_title"] == "三题型卷"
    assert single_item["attempt_id"] == attempt["id"]
    assert single_item["last_wrong_at"]
    assert isinstance(single_item["student_id"], int)
    assert single_item["student_name"] == "s1"

    blank_item = by_question(items, blank["id"])
    assert blank_item["type"] == "blank"
    assert blank_item["options"] is None
    assert blank_item["student_answer"] == ""
    assert blank_item["answer"] == "NaCl"


def test_blank_paper_all_questions_are_wrong(client, classroom):
    t1 = login(client, "t1")
    questions = [
        make_approved(client, t1, **QUESTION),
        make_approved(client, t1, **MULTIPLE_QUESTION),
        make_approved(client, t1, **BLANK_QUESTION),
    ]
    paper = paper_with(client, t1, classroom, questions, "白卷")

    s1 = login(client, "s1")
    attempt = attempt_for_paper(client, s1, paper["id"])
    result = submit(client, s1, attempt, [])
    assert result["score"] == 0.0

    items = wrong_list(client, s1)
    assert {item["question_id"] for item in items} == {q["id"] for q in questions}
    assert all(item["student_answer"] == "" for item in items)


def test_ungraded_record_is_not_listed_until_retry_succeeds(
    client, classroom, monkeypatch
):
    t1 = login(client, "t1")
    single = make_approved(client, t1, **QUESTION)
    paper = paper_with(client, t1, classroom, [single], "判分失败卷")
    s1 = login(client, "s1")
    attempt = attempt_for_paper(client, s1, paper["id"])
    client.post(f"/api/attempts/{attempt['id']}/start", headers=auth(s1))

    original = routes.grade_record

    def boom(session, record):
        raise RuntimeError("判分炸了")

    monkeypatch.setattr(routes, "grade_record", boom)
    failed = client.post(
        f"/api/attempts/{attempt['id']}/submit",
        headers=auth(s1),
        json={"answers": [{"question_id": single["id"], "answer": "B"}]},
    )
    assert failed.status_code == 200, failed.text
    assert failed.json()["data"]["status"] == "submitted"
    assert failed.json()["data"]["score"] is None
    assert wrong_list(client, s1) == []

    monkeypatch.setattr(routes, "grade_record", original)
    # 恢复原判分函数；重试只重跑判分。
    retried = client.post(f"/api/attempts/{attempt['id']}/retry-grading", headers=auth(s1))
    assert retried.status_code == 200, retried.text
    assert retried.json()["data"]["status"] == "graded"

    items = wrong_list(client, s1)
    assert len(items) == 1
    assert items[0]["student_answer"] == "B"
    assert items[0]["attempt_id"] == attempt["id"]


def test_wrong_list_scope_and_empty_state(client, classroom, make_user, make_class):
    t1 = login(client, "t1")
    single = make_approved(client, t1, **QUESTION)
    paper = paper_with(client, t1, classroom, [single], "权限卷")

    s1 = login(client, "s1")
    s2 = login(client, "s2")
    s1_attempt = attempt_for_paper(client, s1, paper["id"])
    submit(client, s1, s1_attempt, [{"question_id": single["id"], "answer": "B"}])
    s2_attempt = attempt_for_paper(client, s2, paper["id"])
    submit(client, s2, s2_attempt, [{"question_id": single["id"], "answer": "C"}])

    s1_items = wrong_list(client, s1)
    assert len(s1_items) == 1
    assert s1_items[0]["student_name"] == "s1"
    assert s1_items[0]["student_answer"] == "B"

    s2_items = wrong_list(client, s2)
    assert len(s2_items) == 1
    assert s2_items[0]["student_name"] == "s2"
    assert s2_items[0]["student_answer"] == "C"

    # 老师必须指定自己带的班；本班能看到，别班/不存在的班拒绝。
    assert client.get("/api/wrong-questions", headers=auth(t1)).status_code == 422
    teacher = client.get(
        f"/api/wrong-questions?class_id={classroom}", headers=auth(t1)
    )
    assert teacher.status_code == 200, teacher.text
    teacher_items = teacher.json()["data"]["items"]
    assert len(teacher_items) == 2
    assert {item["student_name"] for item in teacher_items} == {"s1", "s2"}

    make_user("t2", role="teacher")
    other_class = make_class("别班", "t2")
    other = client.get(
        f"/api/wrong-questions?class_id={other_class}", headers=auth(t1)
    )
    assert other.status_code == 403

    # 学生不能按班级查，也不能按来源参数越权。
    assert (
        client.get(
            f"/api/wrong-questions?class_id={classroom}", headers=auth(s1)
        ).status_code
        == 403
    )
    assert (
        client.get("/api/wrong-questions?source=bad", headers=auth(s1)).status_code
        == 422
    )

    admin = login(client, "admin")
    admin_items = wrong_list(client, admin)
    assert len(admin_items) == 2
    assert {item["student_name"] for item in admin_items} == {"s1", "s2"}
    assert {item["student_answer"] for item in admin_items} == {"B", "C"}

    make_user("s3", role="student", class_id=classroom)
    s3 = login(client, "s3")
    assert wrong_list(client, s3) == []


def test_wrong_list_includes_practice_and_review_sources(client, classroom):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    practice_question = make_approved(client, t1, stem="练习错题")
    review_question = make_approved(client, t1, stem="复习错题")

    practiced = client.post(
        "/api/practice/answers",
        headers=auth(s1),
        json={"question_id": practice_question["id"], "answer": "B", "difficulty": 2},
    )
    assert practiced.status_code == 200, practiced.text
    assert practiced.json()["data"]["is_correct"] is False

    with client.app.state.session_factory() as session:
        student_id = session.scalar(select(User.id).where(User.username == "s1"))
        task = review.add_manual_task(session, student_id, review_question["id"])
        task_id = task.id

    reviewed = client.post(
        f"/api/review/tasks/{task_id}/answer",
        headers=auth(s1),
        json={"student_answer": "B"},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["data"]["is_correct"] is False

    items = wrong_list(client, s1)
    by_question = {item["question_id"]: item for item in items}
    practice_item = by_question[practice_question["id"]]
    assert practice_item["source"] == "practice"
    assert practice_item["student_answer"] == "B"
    assert practice_item["paper_title"] is None
    assert practice_item["attempt_id"] is None

    review_item = by_question[review_question["id"]]
    assert review_item["source"] == "review"
    assert review_item["student_answer"] == "B"
    assert review_item["paper_title"] is None

    only_practice = client.get(
        "/api/wrong-questions?source=practice", headers=auth(s1)
    )
    assert only_practice.status_code == 200, only_practice.text
    assert {item["source"] for item in only_practice.json()["data"]["items"]} == {
        "practice"
    }

    only_review = client.get("/api/wrong-questions?source=review", headers=auth(s1))
    assert only_review.status_code == 200, only_review.text
    assert {item["source"] for item in only_review.json()["data"]["items"]} == {
        "review"
    }

    queued = client.get("/api/wrong-questions?in_queue=true", headers=auth(s1))
    assert queued.status_code == 200, queued.text
    assert {item["question_id"] for item in queued.json()["data"]["items"]} == {
        review_question["id"]
    }
    not_queued = client.get("/api/wrong-questions?in_queue=false", headers=auth(s1))
    assert not_queued.status_code == 200, not_queued.text
    assert {item["question_id"] for item in not_queued.json()["data"]["items"]} == {
        practice_question["id"]
    }

    paged = client.get("/api/wrong-questions?page=1&page_size=1", headers=auth(s1))
    assert paged.status_code == 200, paged.text
    assert paged.json()["data"]["total"] == 2
    assert len(paged.json()["data"]["items"]) == 1
    page_two = client.get("/api/wrong-questions?page=2&page_size=1", headers=auth(s1))
    assert page_two.status_code == 200, page_two.text
    assert len(page_two.json()["data"]["items"]) == 1
    assert (
        page_two.json()["data"]["items"][0]["question_id"]
        != paged.json()["data"]["items"][0]["question_id"]
    )
