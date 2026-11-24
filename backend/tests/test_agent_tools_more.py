"""Agent 工具 6–10：复习、练习、加复习、考试结果、班级概况。"""
from datetime import timedelta
import json

import pytest
from sqlalchemy import func, select

from agent_helpers import ToolCallModel, install_agents, run_agent, tool_outputs, user_id
from app.agent import FakeChatModel
from app import clock, review
from app.models import AnswerItem, AnswerRecord, PracticeRecord, ReviewTask, User
from exam_helpers import (
    attempt_for_paper,
    make_approved,
    paper_with,
    submit_answers,
)
from helpers import auth, login


@pytest.fixture
def world(make_user, make_class):
    make_user("t1", role="teacher")
    class_id = make_class("一班", "t1")
    make_user("s1", role="student", name="学生一", class_id=class_id)
    make_user("t2", role="teacher")
    other_class = make_class("二班", "t2")
    make_user("s2", role="student", name="学生二", class_id=other_class)
    return class_id, other_class


def _point(client, token, name):
    r = client.post(
        "/api/knowledge-points",
        headers=auth(token),
        json={"name": name, "aliases": []},
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


def _set_points(client, token, question_id, point_ids):
    r = client.put(
        f"/api/questions/{question_id}/knowledge-points",
        headers=auth(token),
        json={"knowledge_point_ids": point_ids},
    )
    assert r.status_code == 200, r.text


def _install(client, tool_name, args=None):
    install_agents(client, ToolCallModel(tool_name=tool_name, tool_args=args or {}))


def _count(client, model, **conditions):
    with client.app.state.session_factory() as session:
        stmt = select(func.count()).select_from(model)
        for key, value in conditions.items():
            stmt = stmt.where(getattr(model, key) == value)
        return session.scalar(stmt) or 0


def test_assign_practice_does_not_write_records(client, world):
    class_id, _ = world
    login(client, "t1")
    s1 = login(client, "s1")
    t1 = login(client, "t1")
    point = _point(client, t1, "氧化还原")
    question = make_approved(client, t1, stem="练习题")
    _set_points(client, t1, question["id"], [point["id"]])

    _install(client, "assign_practice", {"count": 5})
    result = run_agent(client, "student", "s1", "给我出几道题练")
    output = tool_outputs(result)[0]
    assert output["found"] is True
    assert output["questions"][0]["id"] == question["id"]
    assert _count(client, PracticeRecord, student_id=user_id(client, "s1")) == 0


def test_add_review_new_existing_and_out_of_queue(client, world):
    login(client, "t1")
    s1 = login(client, "s1")
    t1 = login(client, "t1")
    question = make_approved(client, t1, stem="要记的题")

    _install(client, "add_review", {"question_id": question["id"]})
    result = run_agent(client, "student", "s1", "帮我记一下", thread="add-1")
    output = tool_outputs(result)[0]
    assert output["task"]["level"] == 0
    assert output["task"]["due_on"] is not None

    with client.app.state.session_factory() as session:
        task = session.scalar(select(ReviewTask).where(ReviewTask.question_id == question["id"]))
        task.level = 2
        task.due_on = clock.business_today() + timedelta(days=10)
        session.commit()
        task_id = task.id

    _install(client, "add_review", {"question_id": question["id"]})
    result = run_agent(client, "student", "s1", "帮我记一下", thread="add-2")
    output = tool_outputs(result)[0]
    assert output["task"]["level"] == 2

    with client.app.state.session_factory() as session:
        task = session.get(ReviewTask, task_id)
        assert task.level == 2
        assert task.due_on == clock.business_today() + timedelta(days=1)

    with client.app.state.session_factory() as session:
        task = session.get(ReviewTask, task_id)
        task.level = 5
        task.due_on = None
        session.commit()

    _install(client, "add_review", {"question_id": question["id"]})
    result = run_agent(client, "student", "s1", "帮我记一下", thread="add-3")
    output = tool_outputs(result)[0]
    assert output["task"]["level"] == 0
    assert output["task"]["due_on"] == (clock.business_today() + timedelta(days=1)).isoformat()


def test_due_reviews_orders_overdue_first(client, world):
    login(client, "t1")
    s1 = login(client, "s1")
    t1 = login(client, "t1")
    first = make_approved(client, t1, stem="先到期的题")
    second = make_approved(client, t1, stem="后到期的题")
    future = make_approved(client, t1, stem="明天到期的题")
    with client.app.state.session_factory() as session:
        review.add_manual_task(session, user_id(client, "s1"), first["id"])
        review.add_manual_task(session, user_id(client, "s1"), second["id"])
        review.add_manual_task(session, user_id(client, "s1"), future["id"])
        tasks = session.scalars(select(ReviewTask).order_by(ReviewTask.id)).all()
        tasks[0].due_on = clock.business_today() - timedelta(days=1)
        tasks[1].due_on = clock.business_today()
        session.commit()

    _install(client, "due_reviews", {})
    result = run_agent(client, "student", "s1", "今天要复习什么")
    output = tool_outputs(result)[0]
    assert output["total"] == 2
    assert output["tasks"][0]["question_id"] == first["id"]
    assert output["remaining"] == 0
    assert all(task["question_id"] != future["id"] for task in output["tasks"])


def test_exam_result_student_trims_answers(client, world):
    class_id, _ = world
    login(client, "t1")
    s1 = login(client, "s1")
    t1 = login(client, "t1")
    point = _point(client, t1, "氧化还原")
    right = make_approved(client, t1, stem="答对的题")
    wrong = make_approved(client, t1, stem="答错的题")
    _set_points(client, t1, right["id"], [point["id"]])
    _set_points(client, t1, wrong["id"], [point["id"]])
    paper = paper_with(client, t1, class_id, [right, wrong], "周测")
    attempt = attempt_for_paper(client, s1, paper["id"])
    submit_answers(client, s1, attempt, {right["id"]: "A", wrong["id"]: "B"})

    _install(client, "exam_result", {})
    result = run_agent(client, "student", "s1", "我上次考试哪几道错了")
    output = tool_outputs(result)[0]
    assert output["score"] == 50.0
    assert output["total_questions"] == 2
    assert output["correct_count"] == 1
    assert output["wrong_count"] == 1
    for item in output["questions"]:
        assert set(item) == {"position", "question_id", "is_correct"}


def test_exam_result_refuses_ungraded_attempt(client, world):
    class_id, _ = world
    login(client, "t1")
    s1 = login(client, "s1")
    t1 = login(client, "t1")
    question = make_approved(client, t1, stem="未判分题")
    paper = paper_with(client, t1, class_id, [question], "未判分卷")
    attempt = attempt_for_paper(client, s1, paper["id"])

    with client.app.state.session_factory() as session:
        record = session.get(AnswerRecord, attempt["id"])
        record.status = "submitted"
        record.score = None
        record.submitted_at = clock.utcnow()
        session.add(
            AnswerItem(
                record_id=record.id,
                question_id=question["id"],
                position=1,
                student_answer="B",
                is_correct=None,
            )
        )
        session.commit()

    _install(client, "exam_result", {"attempt_id": attempt["id"]})
    result = run_agent(client, "student", "s1", "我上次考试哪几道错了")
    output = tool_outputs(result)[0]
    assert output["found"] is False
    assert "判分" in output["message"]


def test_exam_result_teacher_own_class_only(client, world):
    class_id, other_class = world
    login(client, "t1")
    login(client, "t2")
    s1 = login(client, "s1")
    t1 = login(client, "t1")
    question = make_approved(client, t1, stem="一班的题")
    paper = paper_with(client, t1, class_id, [question], "一班周测")
    attempt = attempt_for_paper(client, s1, paper["id"])
    submit_answers(client, s1, attempt, {question["id"]: "A"})

    _install(client, "exam_result", {"student_name": "学生一"})
    result = run_agent(
        client, "teacher", "t1", "查一下学生一", class_id=class_id
    )
    output = tool_outputs(result)[0]
    assert output["found"] is True
    assert output["score"] == 100.0

    _install(client, "exam_result", {"student_name": "学生一"})
    result = run_agent(
        client, "teacher", "t2", "查一下学生一", class_id=other_class
    )
    output = tool_outputs(result)[0]
    assert output["found"] is False
    assert "本班没有" in output["message"]


def test_exam_result_teacher_same_name_requires_username(client, world, make_user):
    class_id, _ = world
    login(client, "t1")
    s1 = login(client, "s1")
    t1 = login(client, "t1")
    question = make_approved(client, t1, stem="同名题")
    paper = paper_with(client, t1, class_id, [question], "同名卷")
    attempt = attempt_for_paper(client, s1, paper["id"])
    submit_answers(client, s1, attempt, {question["id"]: "A"})
    make_user("s3", role="student", name="学生一", class_id=class_id)

    _install(client, "exam_result", {"student_name": "学生一"})
    result = run_agent(client, "teacher", "t1", "查一下学生一", class_id=class_id)
    output = tool_outputs(result)[0]
    assert output["found"] is False
    assert "多个同名" in output["message"]

    _install(client, "exam_result", {"student_username": "s1"})
    result = run_agent(client, "teacher", "t1", "查一下学生一", class_id=class_id)
    output = tool_outputs(result)[0]
    assert output["found"] is True
    assert output["score"] == 100.0


def test_exam_result_teacher_transferred_student_has_no_entry(client, world):
    """转出后原班仍保留考试快照，但 Agent 不再按当前班给入口（设计/03）。"""
    class_id, other_class = world
    login(client, "t1")
    s1 = login(client, "s1")
    t1 = login(client, "t1")
    question = make_approved(client, t1, stem="转出题")
    paper = paper_with(client, t1, class_id, [question], "转出卷")
    attempt = attempt_for_paper(client, s1, paper["id"])
    submit_answers(client, s1, attempt, {question["id"]: "A"})

    with client.app.state.session_factory() as session:
        student = session.scalar(select(User).where(User.username == "s1"))
        student.class_id = other_class
        session.commit()

    _install(client, "exam_result", {"student_name": "学生一"})
    result = run_agent(client, "teacher", "t1", "查一下学生一", class_id=class_id)
    output = tool_outputs(result)[0]
    assert output["found"] is False
    assert "本班没有" in output["message"]


def test_class_overview_trims_students(client, world):
    class_id, _ = world
    login(client, "t1")
    s1 = login(client, "s1")
    t1 = login(client, "t1")
    point = _point(client, t1, "氧化还原")
    question = make_approved(client, t1, stem="班级题")
    _set_points(client, t1, question["id"], [point["id"]])
    paper = paper_with(client, t1, class_id, [question], "班级周测")
    attempt = attempt_for_paper(client, s1, paper["id"])
    submit_answers(client, s1, attempt, {question["id"]: "B"})

    _install(client, "class_overview", {})
    result = run_agent(client, "teacher", "t1", "我们班哪块最弱", class_id=class_id)
    output = tool_outputs(result)[0]
    assert output["student_count"] == 1
    assert "students" not in output
    assert output["knowledge_points"][0]["name"] == "氧化还原"


def test_tool_args_have_no_identity_fields():
    from app.agent_tools import class_overview, exam_result, student_profile

    assert student_profile.args == {}
    assert class_overview.args == {}
    assert "student_id" not in exam_result.args
    assert "user_id" not in exam_result.args
    assert "class_id" not in exam_result.args


def test_practice_plan_endpoint_returns_public_questions(client, world):
    login(client, "t1")
    s1 = login(client, "s1")
    t1 = login(client, "t1")
    first = make_approved(client, t1, stem="第一道")
    second = make_approved(client, t1, stem="第二道")
    draft = client.post(
        "/api/questions",
        headers=auth(t1),
        json={
            "stem": "草稿题",
            "type": "single",
            "options": ["A", "B"],
            "answer": "A",
            "difficulty": 1,
        },
    ).json()["data"]

    r = client.get(
        f"/api/practice/plan?question_ids={second['id']},{first['id']},{draft['id']}",
        headers=auth(s1),
    )
    assert r.status_code == 200, r.text
    items = r.json()["data"]["items"]
    assert [item["id"] for item in items] == [second["id"], first["id"]]
    for item in items:
        assert set(item) == {"id", "stem", "type", "options", "difficulty"}
        assert "answer" not in item and "explanation" not in item


def test_assign_practice_emits_plan_result_event(client, world):
    login(client, "t1")
    s1 = login(client, "s1")
    t1 = login(client, "t1")
    question = make_approved(client, t1, stem="题单题")
    install_agents(client, FakeChatModel())

    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": "给我出几道题练"},
        headers=auth(s1),
    ) as response:
        lines = list(response.iter_lines())

    events = []
    current = {}
    for line in lines:
        if line == "":
            if current:
                events.append(current)
                current = {}
        elif line.startswith("event: "):
            current["event"] = line[len("event: "):]
        elif line.startswith("data: "):
            current["data"] = line[len("data: "):]

    plan_events = [
        json.loads(event["data"])
        for event in events
        if event["event"] == "tool" and "assign_practice_result" in event["data"]
    ]
    assert plan_events
    assert plan_events[0]["questions"] == [question["id"]]
