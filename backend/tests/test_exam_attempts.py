"""作答：列表、开始、交卷、判分失败重试、并发与数据一致性（第 05 章）。"""
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import select, update

import app.routes as routes
from app.db import make_engine, make_session_factory
from app.models import AnswerItem, AnswerRecord, utcnow
from exam_helpers import (
    BLANK_QUESTION,
    MULTIPLE_QUESTION,
    QUESTION,
    add_question,
    approve_question,
    create_paper,
    create_question,
    make_approved,
    publish,
)
from helpers import auth, login


def build_exam(client, teacher_token, class_id, question_specs):
    paper = create_paper(client, teacher_token, "考试卷")
    questions = []
    for spec in question_specs:
        question = create_question(client, teacher_token, **spec)
        approve_question(client, teacher_token, question["id"])
        r = add_question(client, teacher_token, paper["id"], question["id"])
        assert r.status_code == 200, r.text
        questions.append(question)
    r = publish(client, teacher_token, paper["id"], class_id)
    assert r.status_code == 200, r.text
    return paper, questions


def attempt_for_paper(client, token, paper_id):
    items = client.get("/api/attempts", headers=auth(token)).json()["data"]["items"]
    return next(item for item in items if item["paper_id"] == paper_id)


def answer_items(database_url, record_id):
    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    with factory() as session:
        rows = session.scalars(
            select(AnswerItem)
            .where(AnswerItem.record_id == record_id)
            .order_by(AnswerItem.position)
        ).all()
        result = [(item.question_id, item.student_answer, item.is_correct) for item in rows]
    engine.dispose()
    return result


def set_record(database_url, record_id, **values):
    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    with factory() as session:
        session.execute(
            update(AnswerRecord).where(AnswerRecord.id == record_id).values(**values)
        )
        session.commit()
    engine.dispose()


@pytest.fixture
def classroom(make_user, make_class):
    make_user("t1", role="teacher")
    make_user("admin", role="admin")
    class_id = make_class("高一(1)班", "t1")
    make_user("s1", role="student", class_id=class_id)
    make_user("s2", role="student", class_id=class_id)
    return class_id


# ---- 4.1 列表与详情 ----

def test_attempt_list_and_detail_fields_by_status(client, database_url, classroom):
    t1 = login(client, "t1")
    paper, (question,) = build_exam(client, t1, classroom, [QUESTION])
    s1 = login(client, "s1")
    s2 = login(client, "s2")
    attempt = attempt_for_paper(client, s1, paper["id"])

    assert attempt["status"] == "pending"
    assert attempt["score"] is None
    assert attempt["grading_in_progress"] is False
    pending = client.get(f"/api/attempts/{attempt['id']}", headers=auth(s1)).json()["data"]
    assert pending["questions"] == []

    started = client.post(f"/api/attempts/{attempt['id']}/start", headers=auth(s1))
    assert started.status_code == 200, started.text
    data = started.json()["data"]
    assert data["status"] == "in_progress"
    assert data["started_at"] is not None
    assert len(data["questions"]) == 1
    assert data["questions"][0]["id"] == question["id"]
    assert "answer" not in data["questions"][0]
    assert "explanation" not in data["questions"][0]
    assert "student_answer" not in data["questions"][0]

    submitted = client.post(
        f"/api/attempts/{attempt['id']}/submit",
        headers=auth(s1),
        json={"answers": [{"question_id": question["id"], "answer": "A"}]},
    )
    assert submitted.status_code == 200, submitted.text
    graded = submitted.json()["data"]
    assert graded["status"] == "graded"
    assert graded["score"] == 100.0
    assert graded["questions"][0]["answer"] == "A"
    assert graded["questions"][0]["student_answer"] == "A"
    assert graded["questions"][0]["is_correct"] is True

    assert client.get(f"/api/attempts/{attempt['id']}", headers=auth(s2)).status_code == 403
    assert client.get("/api/attempts", headers=auth(t1)).status_code == 403
    admin_items = client.get("/api/attempts", headers=auth(login(client, "admin"))).json()["data"]["items"]
    assert len(admin_items) == 2
    assert client.post(
        f"/api/attempts/{attempt['id']}/start", headers=auth(login(client, "admin"))
    ).status_code == 403
    assert client.get("/api/attempts/99999", headers=auth(s1)).status_code == 404


# ---- 4.2 开始 ----

def test_start_can_repeat_and_is_rejected_after_submit(client, classroom):
    t1 = login(client, "t1")
    paper, (question,) = build_exam(client, t1, classroom, [QUESTION])
    s1 = login(client, "s1")
    s2 = login(client, "s2")
    attempt = attempt_for_paper(client, s1, paper["id"])

    first = client.post(f"/api/attempts/{attempt['id']}/start", headers=auth(s1))
    assert first.status_code == 200
    started_at = first.json()["data"]["started_at"]

    again = client.post(f"/api/attempts/{attempt['id']}/start", headers=auth(s1))
    assert again.status_code == 200
    assert again.json()["data"]["status"] == "in_progress"
    assert again.json()["data"]["started_at"] == started_at

    assert client.post(
        f"/api/attempts/{attempt['id']}/start", headers=auth(s2)
    ).status_code == 403

    assert client.post(
        f"/api/attempts/{attempt['id']}/submit",
        headers=auth(s1),
        json={"answers": [{"question_id": question["id"], "answer": "A"}]},
    ).status_code == 200

    after_submit = client.post(f"/api/attempts/{attempt['id']}/start", headers=auth(s1))
    assert after_submit.status_code == 400
    assert "已经交过卷了" in after_submit.json()["error"]


# ---- 4.3 交卷 ----

def test_submit_rules_missing_answers_and_double_submit(client, database_url, classroom):
    t1 = login(client, "t1")
    paper, questions = build_exam(
        client, t1, classroom, [QUESTION, BLANK_QUESTION]
    )
    single, blank = questions
    s1 = login(client, "s1")
    attempt = attempt_for_paper(client, s1, paper["id"])

    before_start = client.post(
        f"/api/attempts/{attempt['id']}/submit", headers=auth(s1), json={"answers": []}
    )
    assert before_start.status_code == 400
    assert "还没开始作答" in before_start.json()["error"]

    client.post(f"/api/attempts/{attempt['id']}/start", headers=auth(s1))

    unknown = client.post(
        f"/api/attempts/{attempt['id']}/submit",
        headers=auth(s1),
        json={"answers": [{"question_id": 99999, "answer": "A"}]},
    )
    assert unknown.status_code == 400
    assert "不属于这份卷子" in unknown.json()["error"]
    assert answer_items(database_url, attempt["id"]) == []

    duplicate = client.post(
        f"/api/attempts/{attempt['id']}/submit",
        headers=auth(s1),
        json={
            "answers": [
                {"question_id": single["id"], "answer": "A"},
                {"question_id": single["id"], "answer": "B"},
            ]
        },
    )
    assert duplicate.status_code == 400
    assert "同一道题" in duplicate.json()["error"]

    too_long = client.post(
        f"/api/attempts/{attempt['id']}/submit",
        headers=auth(s1),
        json={"answers": [{"question_id": single["id"], "answer": "x" * 501}]},
    )
    assert too_long.status_code == 422
    assert "500" in too_long.json()["error"]

    result = client.post(
        f"/api/attempts/{attempt['id']}/submit",
        headers=auth(s1),
        json={"answers": [{"question_id": single["id"], "answer": "A"}]},
    )
    assert result.status_code == 200, result.text
    data = result.json()["data"]
    assert data["status"] == "graded"
    assert data["score"] == 50.0
    items = answer_items(database_url, attempt["id"])
    assert len(items) == 2
    assert items[0][1] == "A" and items[0][2] is True
    assert items[1][1] == "" and items[1][2] is False

    double = client.post(
        f"/api/attempts/{attempt['id']}/submit",
        headers=auth(s1),
        json={"answers": [{"question_id": single["id"], "answer": "B"}]},
    )
    assert double.status_code == 400
    assert "不能再交卷" in double.json()["error"]
    assert answer_items(database_url, attempt["id"])[0][1] == "A"


def test_blank_paper_scores_zero_not_null(client, classroom):
    t1 = login(client, "t1")
    paper, _questions = build_exam(client, t1, classroom, [QUESTION])
    s1 = login(client, "s1")
    attempt = attempt_for_paper(client, s1, paper["id"])
    client.post(f"/api/attempts/{attempt['id']}/start", headers=auth(s1))
    result = client.post(
        f"/api/attempts/{attempt['id']}/submit", headers=auth(s1), json={"answers": []}
    )
    assert result.status_code == 200
    assert result.json()["data"]["score"] == 0.0
    assert result.json()["data"]["status"] == "graded"


# ---- 4.3 / 2.1 判分规则 ----

def test_grading_rules_through_api(client, classroom):
    t1 = login(client, "t1")
    paper, (single, multiple, blank) = build_exam(
        client, t1, classroom, [QUESTION, MULTIPLE_QUESTION, BLANK_QUESTION]
    )
    s1 = login(client, "s1")
    s2 = login(client, "s2")
    a1 = attempt_for_paper(client, s1, paper["id"])
    a2 = attempt_for_paper(client, s2, paper["id"])
    for token, attempt in ((s1, a1), (s2, a2)):
        client.post(f"/api/attempts/{attempt['id']}/start", headers=auth(token))

    perfect = client.post(
        f"/api/attempts/{a1['id']}/submit",
        headers=auth(s1),
        json={
            "answers": [
                {"question_id": single["id"], "answer": " A "},
                {"question_id": multiple["id"], "answer": "CA"},
                {"question_id": blank["id"], "answer": "Ｎａ Ｃｌ"},
            ]
        },
    )
    assert perfect.status_code == 200
    assert perfect.json()["data"]["score"] == 100.0

    wrong = client.post(
        f"/api/attempts/{a2['id']}/submit",
        headers=auth(s2),
        json={
            "answers": [
                {"question_id": single["id"], "answer": "a"},
                {"question_id": multiple["id"], "answer": "A"},
                {"question_id": blank["id"], "answer": "Co"},
            ]
        },
    )
    assert wrong.status_code == 200
    assert wrong.json()["data"]["score"] == 0.0


# ---- 4.4 判分失败与重试 ----

def test_grading_failure_leaves_submitted_and_retry_regrades(
    client, database_url, classroom, monkeypatch
):
    t1 = login(client, "t1")
    paper, (question,) = build_exam(client, t1, classroom, [QUESTION])
    s1 = login(client, "s1")
    attempt = attempt_for_paper(client, s1, paper["id"])
    client.post(f"/api/attempts/{attempt['id']}/start", headers=auth(s1))

    original = routes.grade_record

    def boom(session, record):
        item = session.scalar(select(AnswerItem).where(AnswerItem.record_id == record.id))
        item.is_correct = True
        raise RuntimeError("判分炸了")

    monkeypatch.setattr(routes, "grade_record", boom)
    failed = client.post(
        f"/api/attempts/{attempt['id']}/submit",
        headers=auth(s1),
        json={"answers": [{"question_id": question["id"], "answer": "A"}]},
    )
    assert failed.status_code == 200
    data = failed.json()["data"]
    assert data["status"] == "submitted"
    assert data["score"] is None
    assert data["grading_in_progress"] is False
    assert answer_items(database_url, attempt["id"]) == [
        (question["id"], "A", None)
    ]

    # 判分失败后记录是 submitted，重复交卷仍然 400，不能从交卷入口走重试
    duplicate = client.post(
        f"/api/attempts/{attempt['id']}/submit",
        headers=auth(s1),
        json={"answers": [{"question_id": question["id"], "answer": "B"}]},
    )
    assert duplicate.status_code == 400
    assert "已经交过了" in duplicate.json()["error"]
    assert answer_items(database_url, attempt["id"]) == [
        (question["id"], "A", None)
    ]

    monkeypatch.setattr(routes, "grade_record", original)
    retried = client.post(
        f"/api/attempts/{attempt['id']}/retry-grading", headers=auth(s1)
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["data"]["status"] == "graded"
    assert retried.json()["data"]["score"] == 100.0
    assert answer_items(database_url, attempt["id"]) == [
        (question["id"], "A", True)
    ]

    again = client.post(f"/api/attempts/{attempt['id']}/retry-grading", headers=auth(s1))
    assert again.status_code == 400
    assert "分数已经定了" in again.json()["error"]


def test_slow_grading_rejects_second_submit_without_overwriting(
    client, database_url, classroom, monkeypatch
):
    t1 = login(client, "t1")
    paper, (question,) = build_exam(client, t1, classroom, [QUESTION])
    s1 = login(client, "s1")
    attempt = attempt_for_paper(client, s1, paper["id"])
    client.post(f"/api/attempts/{attempt['id']}/start", headers=auth(s1))

    original = routes.grade_record
    grading_started = threading.Event()
    release_grading = threading.Event()

    def slow(session, record):
        grading_started.set()
        assert release_grading.wait(5)
        return original(session, record)

    monkeypatch.setattr(routes, "grade_record", slow)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(
            client.post,
            f"/api/attempts/{attempt['id']}/submit",
            headers=auth(s1),
            json={"answers": [{"question_id": question["id"], "answer": "A"}]},
        )
        assert grading_started.wait(5)
        second = client.post(
            f"/api/attempts/{attempt['id']}/submit",
            headers=auth(s1),
            json={"answers": [{"question_id": question["id"], "answer": "B"}]},
        )
        assert second.status_code == 400
        assert "已经交过了" in second.json()["error"]
        release_grading.set()
        first_response = first.result(timeout=10)

    assert first_response.status_code == 200
    assert first_response.json()["data"]["status"] == "graded"
    assert answer_items(database_url, attempt["id"]) == [
        (question["id"], "A", True)
    ]


def test_retry_is_leased_and_expiry_allows_retry(
    client, database_url, classroom, monkeypatch
):
    t1 = login(client, "t1")
    paper, (question,) = build_exam(client, t1, classroom, [QUESTION])
    s1 = login(client, "s1")
    s2 = login(client, "s2")
    a1 = attempt_for_paper(client, s1, paper["id"])
    a2 = attempt_for_paper(client, s2, paper["id"])

    original = routes.grade_record

    def fail(session, record):
        raise RuntimeError("判分失败")

    for token, attempt in ((s1, a1), (s2, a2)):
        client.post(f"/api/attempts/{attempt['id']}/start", headers=auth(token))
        monkeypatch.setattr(routes, "grade_record", fail)
        client.post(
            f"/api/attempts/{attempt['id']}/submit",
            headers=auth(token),
            json={"answers": [{"question_id": question["id"], "answer": "A"}]},
        )

    # 并发重试：第一个占租约，第二个 400
    grading_started = threading.Event()
    release_grading = threading.Event()

    def slow(session, record):
        grading_started.set()
        assert release_grading.wait(5)
        return original(session, record)

    monkeypatch.setattr(routes, "grade_record", slow)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(
            client.post, f"/api/attempts/{a1['id']}/retry-grading", headers=auth(s1)
        )
        assert grading_started.wait(5)
        second = client.post(
            f"/api/attempts/{a1['id']}/retry-grading", headers=auth(s1)
        )
        assert second.status_code == 400
        assert "判分正在进行" in second.json()["error"]
        release_grading.set()
        assert first.result(timeout=10).status_code == 200

    # 租约过期后可以再次重试
    set_record(database_url, a2["id"], grading_started_at=utcnow() - timedelta(seconds=120))
    monkeypatch.setattr(routes, "grade_record", original)
    expired = client.post(
        f"/api/attempts/{a2['id']}/retry-grading", headers=auth(s2)
    )
    assert expired.status_code == 200, expired.text
    assert expired.json()["data"]["score"] == 100.0


# ---- 4.5 错误码与不变量 ----

def test_invalid_bodies_are_422_and_unknown_status_is_400(
    client, database_url, classroom
):
    t1 = login(client, "t1")
    paper, (question,) = build_exam(client, t1, classroom, [QUESTION])
    s1 = login(client, "s1")
    attempt = attempt_for_paper(client, s1, paper["id"])
    client.post(f"/api/attempts/{attempt['id']}/start", headers=auth(s1))

    bad_answers = client.post(
        f"/api/attempts/{attempt['id']}/submit",
        headers=auth(s1),
        json={"answers": "A"},
    )
    assert bad_answers.status_code == 422

    missing_question = client.post(
        f"/api/attempts/{attempt['id']}/submit",
        headers=auth(s1),
        json={"answers": [{"answer": "A"}]},
    )
    assert missing_question.status_code == 422
    assert "缺少题目" in missing_question.json()["error"]

    set_record(database_url, attempt["id"], status="weird")
    assert client.post(
        f"/api/attempts/{attempt['id']}/start", headers=auth(s1)
    ).status_code == 400
    assert client.post(
        f"/api/attempts/{attempt['id']}/submit", headers=auth(s1), json={"answers": []}
    ).status_code == 400
    assert client.post(
        f"/api/attempts/{attempt['id']}/retry-grading", headers=auth(s1)
    ).status_code == 400
