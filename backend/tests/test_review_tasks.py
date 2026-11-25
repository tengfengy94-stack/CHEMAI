"""间隔复习：自动入队、到期列表、作答推进、并发与权限（第 07 章）。"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import app.events as events
from app import clock, review
from app.db import make_engine, make_session_factory
from app.models import ReviewTask, User
from exam_helpers import (
    BLANK_QUESTION,
    MULTIPLE_QUESTION,
    QUESTION,
    attempt_for_paper,
    make_approved,
    paper_with,
    submit_answers,
    wrong_questions,
)
from helpers import auth, login

FIXED_NOW = datetime(2026, 11, 23, 4, 0, tzinfo=timezone.utc)  # UTC+8 12:00
TODAY = date(2026, 11, 23)


@pytest.fixture
def classroom(make_user, make_class):
    make_user("t1", role="teacher")
    make_user("admin", role="admin")
    class_id = make_class("高一(1)班", "t1")
    make_user("s1", role="student", class_id=class_id)
    make_user("s2", role="student", class_id=class_id)
    return class_id


@pytest.fixture
def fixed_clock(monkeypatch):
    monkeypatch.setattr(clock, "utcnow", lambda: FIXED_NOW)
    return FIXED_NOW


def task_list(client, token, scope="all"):
    r = client.get(f"/api/review/tasks?scope={scope}", headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()["data"]["items"]


def one_task(client, token, question_id):
    return next(item for item in task_list(client, token) if item["question_id"] == question_id)


def answer(client, token, task_id, text):
    return client.post(
        f"/api/review/tasks/{task_id}/answer",
        headers=auth(token),
        json={"student_answer": text},
    )


def make_wrong_task(client, teacher, student, class_id, question=None, wrong="B"):
    question = question or make_approved(client, teacher, **QUESTION)
    paper = paper_with(client, teacher, class_id, [question], "周测")
    attempt = attempt_for_paper(client, student, paper["id"])
    graded = submit_answers(client, student, attempt, {question["id"]: wrong})
    return one_task(client, student, question["id"]), graded


def set_due(database_url, task_id, due_on):
    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    with factory() as session:
        task = session.get(ReviewTask, task_id)
        task.due_on = due_on
        session.commit()
    engine.dispose()


def test_grading_enqueues_wrong_questions_immediately(client, classroom):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    single = make_approved(client, t1, **QUESTION)
    paper = paper_with(client, t1, classroom, [single], "周测")
    attempt = attempt_for_paper(client, s1, paper["id"])
    graded = submit_answers(client, s1, attempt, {single["id"]: "B"})

    items = task_list(client, s1)
    assert len(items) == 1
    item = items[0]
    assert item["level"] == 0
    assert item["in_queue"] is True
    assert item["due_on"] == (
        clock.business_date_of(
            datetime.fromisoformat(graded["graded_at"].replace("Z", "+00:00"))
        )
        + timedelta(days=1)
    ).isoformat()
    assert item["question"]["stem"] == single["stem"]
    assert "answer" not in item["question"]
    assert "explanation" not in item["question"]


def test_unanswered_question_enters_queue(client, classroom):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    single = make_approved(client, t1, **QUESTION)
    blank = make_approved(client, t1, **BLANK_QUESTION)
    paper = paper_with(client, t1, classroom, [single, blank], "周测")
    attempt = attempt_for_paper(client, s1, paper["id"])
    submit_answers(client, s1, attempt, {single["id"]: "A"})

    items = task_list(client, s1)
    assert [item["question_id"] for item in items] == [blank["id"]]


def test_same_question_wrong_again_resets_without_duplicate(client, classroom, fixed_clock):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    single = make_approved(client, t1, **QUESTION)
    first_task, _ = make_wrong_task(client, t1, s1, classroom, single)
    # 先复习答对，级别升到 1
    assert answer(client, s1, first_task["id"], "A").status_code == 200
    assert one_task(client, s1, single["id"])["level"] == 1

    second = paper_with(client, t1, classroom, [single], "第二次周测")
    attempt = attempt_for_paper(client, s1, second["id"])
    graded = submit_answers(client, s1, attempt, {single["id"]: "C"})
    expected_due = (
        clock.business_date_of(
            datetime.fromisoformat(graded["graded_at"].replace("Z", "+00:00"))
        )
        + timedelta(days=1)
    )

    items = task_list(client, s1)
    assert len(items) == 1
    assert items[0]["id"] == first_task["id"]
    assert items[0]["level"] == 0
    assert items[0]["due_on"] == expected_due.isoformat()


def test_correct_answers_walk_all_levels_and_leave_queue(client, classroom, fixed_clock):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    single = make_approved(client, t1, **QUESTION)
    task, _ = make_wrong_task(client, t1, s1, classroom, single)

    expected = [
        (1, 3),
        (2, 7),
        (3, 14),
        (4, 30),
    ]
    for level, days in expected:
        r = answer(client, s1, task["id"], "A")
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["level"] == level
        assert data["due_on"] == (TODAY + timedelta(days=days)).isoformat()
        assert data["in_queue"] is True

    # 第 4 级答对 → 第 5 级出队
    r = answer(client, s1, task["id"], "A")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["level"] == 5
    assert data["due_on"] is None
    assert data["in_queue"] is False

    assert task_list(client, s1, scope="due") == []
    all_items = task_list(client, s1)
    assert len(all_items) == 1
    assert all_items[0]["level"] == 5
    assert all_items[0]["review_count"] == 5

    # 已出队不能再答
    assert answer(client, s1, task["id"], "A").status_code == 400

    # 出队后新考试又错：仍在原任务上重新入队
    paper = paper_with(client, t1, classroom, [single], "出队后再错")
    attempt = attempt_for_paper(client, s1, paper["id"])
    graded = submit_answers(client, s1, attempt, {single["id"]: "B"})
    expected_due = (
        clock.business_date_of(
            datetime.fromisoformat(graded["graded_at"].replace("Z", "+00:00"))
        )
        + timedelta(days=1)
    )
    reentered = task_list(client, s1)
    assert len(reentered) == 1
    assert reentered[0]["id"] == task["id"]
    assert reentered[0]["level"] == 0
    assert reentered[0]["in_queue"] is True
    assert reentered[0]["due_on"] == expected_due.isoformat()


def test_wrong_answer_resets_to_zero(client, classroom, fixed_clock):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    single = make_approved(client, t1, **QUESTION)
    task, _ = make_wrong_task(client, t1, s1, classroom, single)
    for _ in range(3):
        assert answer(client, s1, task["id"], "A").status_code == 200
    assert one_task(client, s1, single["id"])["level"] == 3

    r = answer(client, s1, task["id"], "B")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["level"] == 0
    assert data["due_on"] == (TODAY + timedelta(days=1)).isoformat()


def test_answer_uses_exam_grading_rules(client, classroom, fixed_clock):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    single = make_approved(client, t1, **QUESTION)
    multiple = make_approved(client, t1, **MULTIPLE_QUESTION)
    blank = make_approved(client, t1, **BLANK_QUESTION)
    paper = paper_with(client, t1, classroom, [single, multiple, blank], "规则卷")
    attempt = attempt_for_paper(client, s1, paper["id"])
    submit_answers(
        client,
        s1,
        attempt,
        {single["id"]: "B", multiple["id"]: "A", blank["id"]: "Na"},
    )

    items = {item["question_id"]: item for item in task_list(client, s1)}
    assert answer(client, s1, items[single["id"]]["id"], " A ").json()["data"]["is_correct"] is True
    assert answer(client, s1, items[multiple["id"]]["id"], "CA").json()["data"]["is_correct"] is True
    assert (
        answer(client, s1, items[blank["id"]]["id"], "Ｎａ Ｃｌ").json()["data"]["is_correct"]
        is True
    )
    assert answer(client, s1, items[blank["id"]]["id"], "nacl").json()["data"]["is_correct"] is False


def test_answer_returns_previous_answer(client, classroom, fixed_clock):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    single = make_approved(client, t1, **QUESTION)
    task, _ = make_wrong_task(client, t1, s1, classroom, single)

    first = answer(client, s1, task["id"], "A").json()["data"]
    assert first["previous_answer"] is None
    assert first["student_answer"] == "A"
    assert first["answer"] == "A"

    second = answer(client, s1, task["id"], "B").json()["data"]
    assert second["previous_answer"] == "A"
    assert second["is_correct"] is False


def test_same_day_two_answers_both_succeed(client, classroom, fixed_clock):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    single = make_approved(client, t1, **QUESTION)
    task, _ = make_wrong_task(client, t1, s1, classroom, single)

    assert answer(client, s1, task["id"], "A").json()["data"]["level"] == 1
    assert answer(client, s1, task["id"], "A").json()["data"]["level"] == 2


def test_due_list_filters_sorts_and_does_not_mutate(
    client, classroom, fixed_clock, database_url
):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    q1 = make_approved(client, t1, **{**QUESTION, "stem": "逾期题"})
    q2 = make_approved(client, t1, **{**QUESTION, "stem": "今天题", "answer": "B"})
    q3 = make_approved(client, t1, **{**QUESTION, "stem": "明天题", "answer": "C"})
    paper = paper_with(client, t1, classroom, [q1, q2, q3], "到期卷")
    attempt = attempt_for_paper(client, s1, paper["id"])
    submit_answers(client, s1, attempt, {q1["id"]: "B", q2["id"]: "A", q3["id"]: "A"})

    items = {item["question_id"]: item for item in task_list(client, s1)}
    set_due(database_url, items[q1["id"]]["id"], TODAY - timedelta(days=5))
    set_due(database_url, items[q2["id"]]["id"], TODAY)
    set_due(database_url, items[q3["id"]]["id"], TODAY + timedelta(days=1))

    due = task_list(client, s1, scope="due")
    assert [item["question_id"] for item in due] == [q1["id"], q2["id"]]
    snapshot = [(item["id"], item["level"], item["due_on"]) for item in due]

    due_again = task_list(client, s1, scope="due")
    assert [(item["id"], item["level"], item["due_on"]) for item in due_again] == snapshot


def test_answer_permissions_and_errors(client, classroom, fixed_clock):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    s2 = login(client, "s2")
    admin = login(client, "admin")
    single = make_approved(client, t1, **QUESTION)
    task, _ = make_wrong_task(client, t1, s1, classroom, single)

    assert client.get("/api/review/tasks", headers=auth(t1)).status_code == 403
    assert client.get("/api/review/tasks?scope=bad", headers=auth(s1)).status_code == 400
    assert answer(client, s2, task["id"], "A").status_code == 403
    assert answer(client, t1, task["id"], "A").status_code == 403
    assert answer(client, admin, task["id"], "A").status_code == 403
    assert answer(client, s1, 99999, "A").status_code == 404
    assert answer(client, s1, task["id"], "x" * 501).status_code == 422


def test_admin_reads_all_tasks_with_student_identity(client, classroom, fixed_clock):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    admin = login(client, "admin")
    single = make_approved(client, t1, **QUESTION)
    make_wrong_task(client, t1, s1, classroom, single)

    items = task_list(client, admin)
    assert len(items) == 1
    assert items[0]["student_id"] is not None
    assert items[0]["student_name"] == "s1"


def test_review_answer_does_not_touch_exam_or_wrong_list(client, classroom, fixed_clock):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    single = make_approved(client, t1, **QUESTION)
    task, graded = make_wrong_task(client, t1, s1, classroom, single)
    before_attempt = client.get(f"/api/attempts/{graded['id']}", headers=auth(s1)).json()["data"]
    before_wrong = wrong_questions(client, s1)

    assert answer(client, s1, task["id"], "A").status_code == 200

    after_attempt = client.get(f"/api/attempts/{graded['id']}", headers=auth(s1)).json()["data"]
    after_wrong = wrong_questions(client, s1)
    assert after_attempt["score"] == before_attempt["score"]
    assert after_attempt["questions"] == before_attempt["questions"]
    # wrong 列表本身不因复习作答改变；task 的级别/到期日会变，比较时排除。
    core = lambda items: [  # noqa: E731 - 测试内小工具
        {key: value for key, value in item.items() if key != "task"} for item in items
    ]
    assert core(after_wrong) == core(before_wrong)


def test_concurrent_answers_only_one_succeeds(client, classroom, fixed_clock):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    single = make_approved(client, t1, **QUESTION)
    task, _ = make_wrong_task(client, t1, s1, classroom, single)

    def submit():
        return answer(client, s1, task["id"], "A").status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(lambda _: submit(), range(2)))

    assert statuses == [200, 400]
    assert one_task(client, s1, single["id"])["level"] == 1


def test_enqueue_failure_rolls_back_grading_then_retry_succeeds(
    client, classroom, monkeypatch
):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    single = make_approved(client, t1, **QUESTION)
    paper = paper_with(client, t1, classroom, [single], "回滚卷")
    attempt = attempt_for_paper(client, s1, paper["id"])

    original = list(events._handlers[events.ATTEMPT_GRADED])

    def boom(**_kwargs):
        raise RuntimeError("入队失败")

    monkeypatch.setattr(events, "_handlers", {events.ATTEMPT_GRADED: [boom]})

    started = client.post(f"/api/attempts/{attempt['id']}/start", headers=auth(s1))
    assert started.status_code == 200, started.text
    result = client.post(
        f"/api/attempts/{attempt['id']}/submit",
        headers=auth(s1),
        json={"answers": [{"question_id": single["id"], "answer": "B"}]},
    )
    assert result.status_code == 200, result.text
    failed = result.json()["data"]
    assert failed["status"] == "submitted"
    assert failed["score"] is None
    assert task_list(client, s1) == []

    # 恢复订阅后重试判分，任务出现
    monkeypatch.setattr(
        events, "_handlers", {events.ATTEMPT_GRADED: original}
    )
    retried = client.post(
        f"/api/attempts/{attempt['id']}/retry-grading", headers=auth(s1)
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["data"]["status"] == "graded"
    assert len(task_list(client, s1)) == 1


def test_delete_question_with_manual_review_task_is_blocked(client, classroom):
    t1 = login(client, "t1")
    question = make_approved(client, t1, **QUESTION)
    with client.app.state.session_factory() as session:
        student_id = session.scalar(select(User.id).where(User.username == "s1"))
        review.add_manual_task(session, student_id, question["id"])

    deleted = client.delete(f"/api/questions/{question['id']}", headers=auth(t1))
    assert deleted.status_code == 409, deleted.text
    assert "复习" in deleted.json()["error"]
    still_there = client.get("/api/questions", headers=auth(t1)).json()["data"]["items"]
    assert any(item["id"] == question["id"] for item in still_there)


def test_review_tasks_pagination_metadata(client, classroom):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    q1 = make_approved(client, t1, **{**QUESTION, "stem": "错题一", "answer": "A"})
    q2 = make_approved(client, t1, **{**QUESTION, "stem": "错题二", "answer": "A"})
    paper = paper_with(client, t1, classroom, [q1, q2], "两错题卷")
    attempt = attempt_for_paper(client, s1, paper["id"])
    submit_answers(client, s1, attempt, {q1["id"]: "B", q2["id"]: "C"})

    first = client.get(
        "/api/review/tasks?scope=all&page=1&page_size=1", headers=auth(s1)
    )
    assert first.status_code == 200, first.text
    data = first.json()["data"]
    assert data["total"] == 2
    assert len(data["items"]) == 1
    second = client.get(
        "/api/review/tasks?scope=all&page=2&page_size=1", headers=auth(s1)
    )
    assert second.status_code == 200, second.text
    assert len(second.json()["data"]["items"]) == 1
    assert second.json()["data"]["items"][0]["id"] != data["items"][0]["id"]
