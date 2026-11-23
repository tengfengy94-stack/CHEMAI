"""自适应练习：难度重放、排除窗口、选题阶梯、作答与副作用边界（第 09 章）。"""
import pytest
from sqlalchemy import func, select

import app.practice as practice
from app import clock
from app.db import make_engine, make_session_factory
from app.models import (
    AnswerItem,
    AnswerRecord,
    PracticeRecord,
    Question,
    ReviewTask,
    User,
)
from exam_helpers import (
    BLANK_QUESTION,
    MULTIPLE_QUESTION,
    QUESTION,
    attempt_for_paper,
    create_question,
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
    make_user("s2", role="student", class_id=class_id)
    return class_id


@pytest.fixture
def db(database_url):
    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    yield factory
    engine.dispose()


@pytest.fixture
def students(db, classroom):
    with db() as session:
        return {
            "s1": session.scalar(select(User.id).where(User.username == "s1")),
            "s2": session.scalar(select(User.id).where(User.username == "s2")),
        }


def add_record(db, student_id, question_id, is_correct, difficulty=2):
    with db() as session:
        record = PracticeRecord(
            student_id=student_id,
            question_id=question_id,
            difficulty=difficulty,
            is_correct=is_correct,
            created_at=clock.utcnow(),
        )
        session.add(record)
        session.commit()
        return record.id


def make_question_row(db, *, stem, difficulty=2, status="approved"):
    with db() as session:
        question = Question(
            stem=stem,
            type="single",
            options=["A", "B", "C"],
            answer="A",
            explanation=None,
            difficulty=difficulty,
            status=status,
            created_by="t1",
            created_at=clock.utcnow(),
        )
        session.add(question)
        session.commit()
        return question.id


def create_point(client, token, name):
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


def patch_report(monkeypatch, items, has_data=True):
    monkeypatch.setattr(
        practice.reporting,
        "weak_report",
        lambda session, student_id: {"has_data": has_data, "items": items},
    )


def item(point_id, name="氧化还原"):
    return {
        "knowledge_point_id": point_id,
        "name": name,
        "answered_count": 2,
        "wrong_count": 2,
        "error_rate": 100.0,
    }


def first_pick(monkeypatch):
    monkeypatch.setattr(
        practice,
        "_pick",
        lambda candidates: sorted(candidates, key=lambda question: question.id)[0],
    )


# ---- 难度重放 ----


def test_difficulty_starts_at_two(db, students):
    with db() as session:
        assert practice.current_difficulty(session, students["s1"]) == 2


def test_difficulty_one_correct_stays_two(db, students):
    qid = make_question_row(db, stem="一")
    add_record(db, students["s1"], qid, True)
    with db() as session:
        assert practice.current_difficulty(session, students["s1"]) == 2


def test_difficulty_two_correct_up_to_three(db, students):
    qid = make_question_row(db, stem="一")
    add_record(db, students["s1"], qid, True)
    add_record(db, students["s1"], qid, True)
    with db() as session:
        assert practice.current_difficulty(session, students["s1"]) == 3


def test_difficulty_caps_at_three(db, students):
    qid = make_question_row(db, stem="一")
    for _ in range(6):
        add_record(db, students["s1"], qid, True)
    with db() as session:
        assert practice.current_difficulty(session, students["s1"]) == 3


def test_difficulty_wrong_drops_one(db, students):
    qid = make_question_row(db, stem="一")
    add_record(db, students["s1"], qid, True)
    add_record(db, students["s1"], qid, True)
    add_record(db, students["s1"], qid, False)
    with db() as session:
        assert practice.current_difficulty(session, students["s1"]) == 2


def test_difficulty_floor_one(db, students):
    qid = make_question_row(db, stem="一")
    for _ in range(5):
        add_record(db, students["s1"], qid, False)
    with db() as session:
        assert practice.current_difficulty(session, students["s1"]) == 1


def test_difficulty_four_correct_from_one(db, students):
    qid = make_question_row(db, stem="一")
    add_record(db, students["s1"], qid, False)  # 降到 1
    for _ in range(4):
        add_record(db, students["s1"], qid, True)  # 1 → 2 → 3
    with db() as session:
        assert practice.current_difficulty(session, students["s1"]) == 3


def test_difficulty_wrong_resets_streak(db, students):
    qid = make_question_row(db, stem="一")
    add_record(db, students["s1"], qid, False)  # 1 档
    add_record(db, students["s1"], qid, True)  # 连续 1
    add_record(db, students["s1"], qid, False)  # 连续清零，仍 1 档
    add_record(db, students["s1"], qid, True)  # 连续 1，不升
    with db() as session:
        assert practice.current_difficulty(session, students["s1"]) == 1


def test_difficulty_ignores_relaxed_served_difficulty(db, students):
    qid = make_question_row(db, stem="一")
    add_record(db, students["s1"], qid, True)
    add_record(db, students["s1"], qid, True)  # 到 3 档
    add_record(db, students["s1"], qid, True, difficulty=1)  # 放宽出的 1 档题
    with db() as session:
        assert practice.current_difficulty(session, students["s1"]) == 3


def test_difficulty_different_student_isolated(db, students):
    qid = make_question_row(db, stem="一")
    add_record(db, students["s1"], qid, True)
    add_record(db, students["s1"], qid, True)
    with db() as session:
        assert practice.current_difficulty(session, students["s2"]) == 2


# ---- 排除窗口 ----


def test_recent_window_returns_latest_20_records(db, students):
    qids = [make_question_row(db, stem=f"题{i}") for i in range(21)]
    for qid in qids:
        add_record(db, students["s1"], qid, True)
    with db() as session:
        recent = practice.recent_question_ids(session, students["s1"], 20)
    assert len(recent) == 20
    assert qids[0] not in recent
    assert recent[0] == qids[-1]  # 最近的排最前


def test_recent_window_less_than_20_returns_all(db, students):
    qids = [make_question_row(db, stem=f"题{i}") for i in range(3)]
    for qid in qids:
        add_record(db, students["s1"], qid, True)
    with db() as session:
        recent = practice.recent_question_ids(session, students["s1"], 20)
    assert recent == list(reversed(qids))


def test_recent_window_is_shared_across_points(db, students):
    qid = make_question_row(db, stem="共享题")
    add_record(db, students["s1"], qid, True)
    with db() as session:
        assert qid in practice.recent_question_ids(session, students["s1"], 20)


def test_window_allows_question_outside_latest_20(db, students):
    """第 21 条之前的题不在排除窗口里，选题时可以被选中。"""
    qids = [make_question_row(db, stem=f"题{i}") for i in range(21)]
    for qid in qids:
        add_record(db, students["s1"], qid, True)
    with db() as session:
        recent = practice.recent_question_ids(session, students["s1"], 20)
        assert qids[0] not in recent
        oldest = session.get(Question, qids[0])
        chosen = practice._choose({oldest.id: oldest}, recent, 2)
    assert chosen is not None
    assert chosen.id == qids[0]


# ---- 选题阶梯 ----


def test_selection_prefers_first_weak_point(client, db, students, monkeypatch):
    t1 = login(client, "t1")
    p1 = create_point(client, t1, "氧化还原")
    p2 = create_point(client, t1, "电化学")
    q1 = make_approved(client, t1, **QUESTION)
    q2 = make_approved(client, t1, **{**QUESTION, "stem": "电化学题"})
    link(client, t1, q1["id"], [p1["id"]])
    link(client, t1, q2["id"], [p2["id"]])
    patch_report(monkeypatch, [item(p1["id"], "氧化还原"), item(p2["id"], "电化学")])
    first_pick(monkeypatch)

    with db() as session:
        result = practice.next_question(session, students["s1"])
    assert result["status"] == "question"
    assert result["knowledge_point"] == {"id": p1["id"], "name": "氧化还原"}
    assert result["question"]["id"] == q1["id"]


def test_selection_falls_through_empty_first_point(client, db, students, monkeypatch):
    t1 = login(client, "t1")
    p1 = create_point(client, t1, "氧化还原")
    p2 = create_point(client, t1, "电化学")
    q2 = make_approved(client, t1, **QUESTION)
    link(client, t1, q2["id"], [p2["id"]])
    patch_report(monkeypatch, [item(p1["id"], "氧化还原"), item(p2["id"], "电化学")])
    first_pick(monkeypatch)

    with db() as session:
        result = practice.next_question(session, students["s1"])
    assert result["status"] == "question"
    assert result["knowledge_point"]["id"] == p2["id"]
    assert result["question"]["id"] == q2["id"]


def test_selection_all_weak_points_empty(client, db, students, monkeypatch):
    t1 = login(client, "t1")
    p1 = create_point(client, t1, "氧化还原")
    p2 = create_point(client, t1, "电化学")
    patch_report(monkeypatch, [item(p1["id"], "氧化还原"), item(p2["id"], "电化学")])

    with db() as session:
        result = practice.next_question(session, students["s1"])
    assert result["status"] == "empty"
    assert result["reason"] == "no_question_in_point"
    assert result["message"] == "该知识点暂无题"
    assert result["question"] is None


def test_selection_does_not_leave_weak_points(client, db, students, monkeypatch):
    t1 = login(client, "t1")
    p1 = create_point(client, t1, "氧化还原")
    outside = create_point(client, t1, "化学平衡")
    q = make_approved(client, t1, **QUESTION)
    link(client, t1, q["id"], [outside["id"]])
    patch_report(monkeypatch, [item(p1["id"], "氧化还原")])

    with db() as session:
        result = practice.next_question(session, students["s1"])
    assert result["status"] == "empty"
    assert result["question"] is None


def test_selection_question_can_belong_to_two_points(client, db, students, monkeypatch):
    t1 = login(client, "t1")
    p1 = create_point(client, t1, "氧化还原")
    p2 = create_point(client, t1, "电化学")
    q = make_approved(client, t1, **QUESTION)
    link(client, t1, q["id"], [p1["id"], p2["id"]])
    with db() as session:
        assert q["id"] in practice._approved_questions_for_point(session, p1["id"])
        assert q["id"] in practice._approved_questions_for_point(session, p2["id"])


def test_selection_relaxes_difficulty_before_shrinking_window(client, db, students, monkeypatch):
    t1 = login(client, "t1")
    p1 = create_point(client, t1, "氧化还原")
    repeated = make_approved(client, t1, **{**QUESTION, "stem": "重复题", "difficulty": 2})
    relaxed = make_approved(client, t1, **{**QUESTION, "stem": "放宽题", "difficulty": 3})
    link(client, t1, repeated["id"], [p1["id"]])
    link(client, t1, relaxed["id"], [p1["id"]])
    add_record(db, students["s1"], repeated["id"], True, difficulty=2)
    patch_report(monkeypatch, [item(p1["id"], "氧化还原")])
    first_pick(monkeypatch)

    with db() as session:
        result = practice.next_question(session, students["s1"])
    assert result["question"]["id"] == relaxed["id"]
    assert result["served_difficulty"] == 3
    assert result["current_difficulty"] == 2


def test_selection_window_zero_allows_repeat(client, db, students, monkeypatch):
    t1 = login(client, "t1")
    p1 = create_point(client, t1, "氧化还原")
    only = make_approved(client, t1, **QUESTION)
    link(client, t1, only["id"], [p1["id"]])
    add_record(db, students["s1"], only["id"], True, difficulty=2)
    patch_report(monkeypatch, [item(p1["id"], "氧化还原")])
    first_pick(monkeypatch)

    with db() as session:
        result = practice.next_question(session, students["s1"])
    assert result["question"]["id"] == only["id"]


def test_selection_only_approved(client, db, students, monkeypatch):
    t1 = login(client, "t1")
    p1 = create_point(client, t1, "氧化还原")
    draft = make_approved(client, t1, **QUESTION)
    link(client, t1, draft["id"], [p1["id"]])
    # 把题改回草稿：审核状态是单向的，直接改库模拟不可练习的题
    with db() as session:
        question = session.get(Question, draft["id"])
        question.status = "draft"
        session.commit()
    patch_report(monkeypatch, [item(p1["id"], "氧化还原")])

    with db() as session:
        result = practice.next_question(session, students["s1"])
    assert result["status"] == "empty"


# ---- 无弱项 ----


def test_no_weak_starts_with_middle_difficulty(client, db, students, monkeypatch):
    t1 = login(client, "t1")
    q = make_approved(client, t1, **QUESTION)
    patch_report(monkeypatch, [], has_data=False)

    with db() as session:
        result = practice.next_question(session, students["s1"])
    assert result["status"] == "question"
    assert result["has_weak_data"] is False
    assert result["reason"] == "no_data"
    assert result["message"] == "先做几道题，系统才能找到你的弱项"
    assert result["current_difficulty"] == 2
    assert result["served_difficulty"] == 2
    assert result["question"]["id"] == q["id"]


def test_no_weak_but_practiced_uses_derived_difficulty(client, db, students, monkeypatch):
    t1 = login(client, "t1")
    easy = make_approved(client, t1, **{**QUESTION, "stem": "一档", "difficulty": 1})
    hard = make_approved(client, t1, **{**QUESTION, "stem": "三档", "difficulty": 3})
    add_record(db, students["s1"], easy["id"], True, difficulty=1)
    add_record(db, students["s1"], easy["id"], True, difficulty=1)
    patch_report(monkeypatch, [], has_data=True)

    with db() as session:
        result = practice.next_question(session, students["s1"])
    assert result["current_difficulty"] == 3
    assert result["reason"] == "no_weak_point"
    assert result["message"] == "暂无可统计的弱项"
    assert result["question"]["id"] == hard["id"]
    assert result["served_difficulty"] == 3


def test_no_weak_no_approved_questions(client, db, students, monkeypatch):
    t1 = login(client, "t1")
    make_approved(client, t1, **QUESTION)
    with db() as session:
        question = session.scalar(select(Question).where(Question.status == "approved"))
        question.status = "draft"
        session.commit()
    patch_report(monkeypatch, [], has_data=False)

    with db() as session:
        result = practice.next_question(session, students["s1"])
    assert result["status"] == "empty"
    assert result["reason"] == "no_approved_question"
    assert result["message"] == "题库里还没有可练习的题"


# ---- 作答 ----


def test_answer_judges_single(client, db, students):
    t1 = login(client, "t1")
    q = make_approved(client, t1, **QUESTION)
    with db() as session:
        result = practice.answer_question(session, students["s1"], q["id"], "A", 2)
    assert result["is_correct"] is True
    assert result["answer"] == "A"
    assert result["explanation"] == QUESTION["explanation"]
    assert result["next_difficulty"] == 2


def test_answer_judges_multiple(client, db, students):
    t1 = login(client, "t1")
    q = make_approved(client, t1, **MULTIPLE_QUESTION)
    with db() as session:
        result = practice.answer_question(session, students["s1"], q["id"], "CA", 2)
    assert result["is_correct"] is True


def test_answer_judges_blank(client, db, students):
    t1 = login(client, "t1")
    q = make_approved(client, t1, **BLANK_QUESTION)
    with db() as session:
        result = practice.answer_question(session, students["s1"], q["id"], "Ｎａ Ｃｌ", 1)
    assert result["is_correct"] is True


def test_answer_records_served_difficulty_and_outcome(client, db, students):
    t1 = login(client, "t1")
    q = make_approved(client, t1, **QUESTION)
    with db() as session:
        practice.answer_question(session, students["s1"], q["id"], "B", 3)
    with db() as session:
        record = session.scalar(select(PracticeRecord))
        assert record.student_id == students["s1"]
        assert record.question_id == q["id"]
        assert record.difficulty == 3
        assert record.is_correct is False


def test_answer_same_question_twice_creates_two_records(client, db, students):
    t1 = login(client, "t1")
    q = make_approved(client, t1, **QUESTION)
    with db() as session:
        practice.answer_question(session, students["s1"], q["id"], "A", 2)
        practice.answer_question(session, students["s1"], q["id"], "B", 2)
    with db() as session:
        assert session.scalar(select(func.count()).select_from(PracticeRecord)) == 2


def test_answer_too_long_rejected(client, db, students):
    t1 = login(client, "t1")
    q = make_approved(client, t1, **QUESTION)
    with db() as session:
        with pytest.raises(practice.PracticeAnswerTooLong):
            practice.answer_question(session, students["s1"], q["id"], "A" * 501, 2)
    with db() as session:
        assert session.scalar(select(func.count()).select_from(PracticeRecord)) == 0


def test_answer_missing_or_draft_question_rejected(client, db, students):
    t1 = login(client, "t1")
    q = make_approved(client, t1, **QUESTION)
    with db() as session:
        question = session.get(Question, q["id"])
        question.status = "draft"
        session.commit()
    with db() as session:
        with pytest.raises(practice.PracticeQuestionNotFound):
            practice.answer_question(session, students["s1"], q["id"], "A", 2)
        with pytest.raises(practice.PracticeQuestionNotFound):
            practice.answer_question(session, students["s1"], 999999, "A", 2)


def test_answer_two_correct_raises_next_difficulty(client, db, students):
    t1 = login(client, "t1")
    q = make_approved(client, t1, **QUESTION)
    with db() as session:
        first = practice.answer_question(session, students["s1"], q["id"], "A", 2)
        second = practice.answer_question(session, students["s1"], q["id"], "A", 2)
    assert first["next_difficulty"] == 2
    assert second["next_difficulty"] == 3


# ---- 副作用边界 ----


def test_practice_answer_does_not_touch_exam_or_review(client, db, classroom, students):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    question = make_approved(client, t1, **QUESTION)
    paper = paper_with(client, t1, classroom, [question], "周测")
    attempt = attempt_for_paper(client, s1, paper["id"])
    graded = submit_answers(client, s1, attempt, {question["id"]: "B"})

    with db() as session:
        task_before = session.scalar(select(ReviewTask))
        assert task_before is not None
        task_state = (
            task_before.level,
            task_before.due_on,
            task_before.last_answer,
            task_before.review_count,
        )
        item_before = session.scalar(select(AnswerItem))
        answer_record = session.get(AnswerRecord, item_before.record_id)
        score_before = answer_record.score
        item_count_before = session.scalar(select(func.count()).select_from(AnswerItem))
        task_count_before = session.scalar(select(func.count()).select_from(ReviewTask))

    with db() as session:
        practice.answer_question(session, students["s1"], question["id"], "A", 2)

    with db() as session:
        task_after = session.scalar(select(ReviewTask))
        item_after = session.scalar(select(AnswerItem))
        answer_record = session.get(AnswerRecord, item_after.record_id)
        assert (
            task_after.level,
            task_after.due_on,
            task_after.last_answer,
            task_after.review_count,
        ) == task_state
        assert answer_record.score == score_before
        assert item_after.is_correct is False
        assert session.scalar(select(func.count()).select_from(AnswerItem)) == item_count_before
        assert session.scalar(select(func.count()).select_from(ReviewTask)) == task_count_before
        assert graded["score"] == score_before


# ---- 接口与权限 ----


def test_next_requires_student(client, students, monkeypatch):
    t1 = login(client, "t1")
    admin = login(client, "admin")
    s1 = login(client, "s1")
    make_approved(client, t1, **QUESTION)
    patch_report(monkeypatch, [], has_data=False)

    assert client.get("/api/practice/next", headers=auth(t1)).status_code == 403
    assert client.get("/api/practice/next", headers=auth(admin)).status_code == 403
    assert client.get("/api/practice/next", headers=auth(s1)).status_code == 200


def test_next_returns_question_without_answer(client, students, monkeypatch):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    q = make_approved(client, t1, **QUESTION)
    patch_report(monkeypatch, [], has_data=False)

    r = client.get("/api/practice/next", headers=auth(s1))
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["status"] == "question"
    assert data["reason"] == "no_data"
    assert data["message"] == "先做几道题，系统才能找到你的弱项"
    assert data["current_difficulty"] == 2
    assert data["served_difficulty"] == 2
    assert data["question"] == {
        "id": q["id"],
        "stem": q["stem"],
        "type": q["type"],
        "options": q["options"],
    }
    assert "answer" not in data["question"]
    assert "explanation" not in data["question"]


def test_next_empty_state_is_success_envelope(client, students, monkeypatch):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    p = create_point(client, t1, "氧化还原")
    patch_report(monkeypatch, [item(p["id"], "氧化还原")])

    r = client.get("/api/practice/next", headers=auth(s1))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["data"]["status"] == "empty"
    assert body["data"]["reason"] == "no_question_in_point"
    assert body["data"]["message"] == "该知识点暂无题"


def test_answer_returns_feedback_after_submit(client, students, monkeypatch):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    q = make_approved(client, t1, **QUESTION)
    patch_report(monkeypatch, [], has_data=False)

    question = client.get("/api/practice/next", headers=auth(s1)).json()["data"]
    r = client.post(
        "/api/practice/answers",
        headers=auth(s1),
        json={
            "question_id": question["question"]["id"],
            "answer": "A",
            "difficulty": question["served_difficulty"],
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["is_correct"] is True
    assert data["student_answer"] == "A"
    assert data["answer"] == "A"
    assert data["explanation"] == QUESTION["explanation"]
    assert data["served_difficulty"] == 2
    assert data["next_difficulty"] == 2
    assert data["record_id"]


def test_answer_requires_student(client, db, students, monkeypatch):
    t1 = login(client, "t1")
    admin = login(client, "admin")
    q = make_approved(client, t1, **QUESTION)
    payload = {"question_id": q["id"], "answer": "A", "difficulty": 2}

    assert client.post("/api/practice/answers", headers=auth(t1), json=payload).status_code == 403
    assert client.post("/api/practice/answers", headers=auth(admin), json=payload).status_code == 403
    with db() as session:
        assert session.scalar(select(func.count()).select_from(PracticeRecord)) == 0


def test_answer_too_long_returns_422_and_writes_nothing(client, db, students):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    q = make_approved(client, t1, **QUESTION)
    r = client.post(
        "/api/practice/answers",
        headers=auth(s1),
        json={"question_id": q["id"], "answer": "A" * 501, "difficulty": 2},
    )
    assert r.status_code == 422, r.text
    assert r.json()["error"] == "单题答案最多 500 字"
    with db() as session:
        assert session.scalar(select(func.count()).select_from(PracticeRecord)) == 0


def test_answer_missing_question_returns_404(client, db, students):
    s1 = login(client, "s1")
    r = client.post(
        "/api/practice/answers",
        headers=auth(s1),
        json={"question_id": 999999, "answer": "A", "difficulty": 2},
    )
    assert r.status_code == 404, r.text
    assert r.json()["error"] == "题目不存在"
    with db() as session:
        assert session.scalar(select(func.count()).select_from(PracticeRecord)) == 0


def test_answer_draft_question_returns_404(client, db, students):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    q = create_question(client, t1, **QUESTION)
    r = client.post(
        "/api/practice/answers",
        headers=auth(s1),
        json={"question_id": q["id"], "answer": "A", "difficulty": 2},
    )
    assert r.status_code == 404, r.text
    with db() as session:
        assert session.scalar(select(func.count()).select_from(PracticeRecord)) == 0


def test_answer_invalid_difficulty_returns_422(client, students):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    q = make_approved(client, t1, **QUESTION)
    r = client.post(
        "/api/practice/answers",
        headers=auth(s1),
        json={"question_id": q["id"], "answer": "A", "difficulty": 4},
    )
    assert r.status_code == 422, r.text
    assert r.json()["error"] == "难度格式不对"


def test_delete_practiced_question_is_blocked(client, db, students):
    t1 = login(client, "t1")
    q = make_approved(client, t1, **QUESTION)
    with db() as session:
        practice.answer_question(session, students["s1"], q["id"], "A", 2)

    r = client.delete(f"/api/questions/{q['id']}", headers=auth(t1))
    assert r.status_code == 409, r.text
    assert r.json()["error"] == "这道题已被学生练习过，不能删除"

    with db() as session:
        assert session.get(Question, q["id"]) is not None
        assert session.scalar(select(func.count()).select_from(PracticeRecord)) == 1
