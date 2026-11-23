"""弱项统计：错误率口径、样本门槛、排序、无数据与权限（第 07/09 章）。"""
import pytest
from sqlalchemy import select

import app.events as events
from app import clock
from app.db import make_engine, make_session_factory
from app.models import PracticeRecord, User
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
    make_user("s2", role="student", class_id=class_id)
    return class_id


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
    return submit_answers(client, student, attempt, answers)


def weak(client, token, student_id=None):
    url = "/api/reports/weak"
    if student_id is not None:
        url += f"?student_id={student_id}"
    r = client.get(url, headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_error_rate_counts_every_answer(client, classroom):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    kp = point(client, t1, "氧化还原")
    q = question(client, t1, "电解质")
    link(client, t1, q["id"], [kp["id"]])

    take(client, t1, s1, classroom, [q], {q["id"]: "B"}, "错一")
    take(client, t1, s1, classroom, [q], {q["id"]: "B"}, "错二")
    take(client, t1, s1, classroom, [q], {q["id"]: "A"}, "对三")

    data = weak(client, s1)
    assert data["has_data"] is True
    assert data["items"] == [
        {
            "knowledge_point_id": kp["id"],
            "name": "氧化还原",
            "answered_count": 3,
            "wrong_count": 2,
            "error_rate": 66.7,
        }
    ]


def test_sample_below_two_is_not_ranked(client, classroom):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    kp = point(client, t1, "电化学")
    q = question(client, t1, "原电池")
    link(client, t1, q["id"], [kp["id"]])
    take(client, t1, s1, classroom, [q], {q["id"]: "B"}, "只错一次")

    data = weak(client, s1)
    assert data["has_data"] is True
    assert data["items"] == []


def test_question_without_knowledge_point_is_ignored(client, classroom):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    q = question(client, t1, "没有归类")
    take(client, t1, s1, classroom, [q], {q["id"]: "B"}, "未归类卷")

    data = weak(client, s1)
    assert data["has_data"] is True
    assert data["items"] == []


def test_ungraded_record_is_ignored(client, classroom, monkeypatch):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    kp = point(client, t1, "化学平衡")
    q = question(client, t1, "平衡移动")
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

    data = weak(client, s1)
    assert data["has_data"] is False
    assert data["items"] == []


def test_multi_point_counts_in_each_denominator(client, classroom):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    a = point(client, t1, "氧化还原")
    b = point(client, t1, "电化学")
    both = question(client, t1, "同时考两个点")
    only_a = question(client, t1, "只考氧化还原", answer="B")
    only_b = question(client, t1, "只考电化学", answer="C")
    link(client, t1, both["id"], [a["id"], b["id"]])
    link(client, t1, only_a["id"], [a["id"]])
    link(client, t1, only_b["id"], [b["id"]])

    take(
        client,
        t1,
        s1,
        classroom,
        [both, only_a, only_b],
        {both["id"]: "B", only_a["id"]: "B", only_b["id"]: "C"},
        "多知识点卷",
    )

    items = {item["name"]: item for item in weak(client, s1)["items"]}
    assert items["氧化还原"]["answered_count"] == 2
    assert items["氧化还原"]["wrong_count"] == 1
    assert items["电化学"]["answered_count"] == 2
    assert items["电化学"]["wrong_count"] == 1
    assert items["电化学"]["error_rate"] == 50.0


def test_blank_paper_counts_every_question_wrong(client, classroom):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    kp = point(client, t1, "物质结构")
    q1 = question(client, t1, "白卷一")
    q2 = question(client, t1, "白卷二")
    link(client, t1, q1["id"], [kp["id"]])
    link(client, t1, q2["id"], [kp["id"]])
    take(client, t1, s1, classroom, [q1, q2], {}, "白卷")

    data = weak(client, s1)
    assert data["items"][0]["answered_count"] == 2
    assert data["items"][0]["wrong_count"] == 2
    assert data["items"][0]["error_rate"] == 100.0


def test_top_three_excludes_zero_error_with_enough_sample(client, classroom):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    names = ["全对点", "弱项一", "弱项二", "弱项三"]
    points = {name: point(client, t1, name) for name in names}
    questions = {}
    for name in names:
        q = question(client, t1, f"{name}的题")
        link(client, t1, q["id"], [points[name]["id"]])
        questions[name] = q

    for round_no in range(2):
        answers = {questions["全对点"]["id"]: "A"}
        for name in names[1:]:
            answers[questions[name]["id"]] = "B"
        take(
            client,
            t1,
            s1,
            classroom,
            list(questions.values()),
            answers,
            f"第三名卷 {round_no}",
        )

    data = weak(client, s1)
    assert len(data["items"]) == 3
    assert [item["name"] for item in data["items"]] == ["弱项一", "弱项二", "弱项三"]
    assert "全对点" not in [item["name"] for item in data["items"]]


def test_tie_on_rate_sorts_by_answer_count(client, classroom):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    small = point(client, t1, "样本少")
    large = point(client, t1, "样本多")
    s1q1 = question(client, t1, "样本少一")
    s1q2 = question(client, t1, "样本少二")
    l1q1 = question(client, t1, "样本多一")
    l1q2 = question(client, t1, "样本多二")
    link(client, t1, s1q1["id"], [small["id"]])
    link(client, t1, s1q2["id"], [small["id"]])
    link(client, t1, l1q1["id"], [large["id"]])
    link(client, t1, l1q2["id"], [large["id"]])

    # 两个知识点各 50%：样本少的答 4 次，样本多的答 8 次
    for round_no in range(2):
        take(
            client,
            t1,
            s1,
            classroom,
            [s1q1, s1q2, l1q1, l1q2],
            {
                s1q1["id"]: "B",
                s1q2["id"]: "A",
                l1q1["id"]: "B",
                l1q2["id"]: "A",
            },
            f"并列卷 {round_no}",
        )
    for round_no in range(2):
        take(
            client,
            t1,
            s1,
            classroom,
            [l1q1, l1q2],
            {l1q1["id"]: "B", l1q2["id"]: "A"},
            f"样本多卷 {round_no}",
        )

    items = weak(client, s1)["items"]
    assert [item["name"] for item in items] == ["样本多", "样本少"]
    assert items[0]["error_rate"] == items[1]["error_rate"] == 50.0
    assert items[0]["answered_count"] == 8
    assert items[1]["answered_count"] == 4


def test_review_answer_does_not_change_weak_report(client, classroom):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    kp = point(client, t1, "元素周期律")
    q = question(client, t1, "周期表")
    link(client, t1, q["id"], [kp["id"]])
    take(client, t1, s1, classroom, [q], {q["id"]: "B"}, "复习不影响统计")
    take(client, t1, s1, classroom, [q], {q["id"]: "B"}, "复习不影响统计二")

    before = weak(client, s1)
    task = client.get("/api/review/tasks?scope=all", headers=auth(s1)).json()["data"]["items"][0]
    review_answer = client.post(
        f"/api/review/tasks/{task['id']}/answer",
        headers=auth(s1),
        json={"student_answer": "A"},
    )
    assert review_answer.status_code == 200, review_answer.text
    assert weak(client, s1) == before


def test_no_learning_record_returns_has_data_false(client, classroom):
    s2 = login(client, "s2")
    assert weak(client, s2) == {"has_data": False, "items": []}


def user_id(database_url, username):
    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    with factory() as session:
        value = session.scalar(select(User.id).where(User.username == username))
    engine.dispose()
    return value


def add_practice(database_url, student_id, question_id, is_correct, difficulty=2):
    """直接写一条练习记录，避免测试依赖练习接口。"""
    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    with factory() as session:
        session.add(
            PracticeRecord(
                student_id=student_id,
                question_id=question_id,
                difficulty=difficulty,
                is_correct=is_correct,
                created_at=clock.utcnow(),
            )
        )
        session.commit()
    engine.dispose()


def test_merge_recomputes_weak_report(client, classroom):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    source = point(client, t1, "氧化还原")
    target = point(client, t1, "电化学")
    q1 = question(client, t1, "氧化还原题")
    q2 = question(client, t1, "电化学题")
    link(client, t1, q1["id"], [source["id"]])
    link(client, t1, q2["id"], [target["id"]])

    for round_no in range(2):
        take(
            client,
            t1,
            s1,
            classroom,
            [q1, q2],
            {q1["id"]: "B", q2["id"]: "B"},
            f"合并前 {round_no}",
        )

    before = weak(client, s1)["items"]
    assert {item["name"] for item in before} == {"氧化还原", "电化学"}

    merged = client.post(
        f"/api/knowledge-points/{source['id']}/merge",
        headers=auth(t1),
        json={"target_id": target["id"]},
    )
    assert merged.status_code == 200, merged.text

    after = weak(client, s1)["items"]
    assert len(after) == 1
    assert after[0]["knowledge_point_id"] == target["id"]
    assert after[0]["answered_count"] == 4
    assert after[0]["wrong_count"] == 4
    assert after[0]["error_rate"] == 100.0


def test_visibility_and_admin_target(client, classroom, database_url):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    admin = login(client, "admin")
    kp = point(client, t1, "化学反应速率")
    q = question(client, t1, "速率题")
    link(client, t1, q["id"], [kp["id"]])
    take(client, t1, s1, classroom, [q], {q["id"]: "B"}, "权限卷")
    take(client, t1, s1, classroom, [q], {q["id"]: "A"}, "权限卷二")

    s1_id = user_id(database_url, "s1")
    t1_id = user_id(database_url, "t1")

    assert client.get("/api/reports/weak", headers=auth(t1)).status_code == 403
    assert client.get("/api/reports/weak", headers=auth(admin)).status_code == 400
    assert client.get("/api/reports/weak?student_id=99999", headers=auth(admin)).status_code == 404
    assert client.get(
        f"/api/reports/weak?student_id={t1_id}", headers=auth(admin)
    ).status_code == 404
    assert client.get(
        f"/api/reports/weak?student_id={t1_id}", headers=auth(s1)
    ).status_code == 403

    own = weak(client, s1)
    as_admin = weak(client, admin, student_id=s1_id)
    assert as_admin == own
    assert as_admin["items"][0]["answered_count"] == 2


def test_only_practice_records_count_as_learning_data(client, classroom, database_url):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    s1_id = user_id(database_url, "s1")
    kp = point(client, t1, "氧化还原")
    q = question(client, t1, "只练过")
    link(client, t1, q["id"], [kp["id"]])

    add_practice(database_url, s1_id, q["id"], False)
    data = weak(client, s1)
    assert data["has_data"] is True
    assert data["items"] == []  # 练习一次，未到样本门槛

    add_practice(database_url, s1_id, q["id"], True)
    assert weak(client, s1)["items"] == [
        {
            "knowledge_point_id": kp["id"],
            "name": "氧化还原",
            "answered_count": 2,
            "wrong_count": 1,
            "error_rate": 50.0,
        }
    ]


def test_exam_and_practice_merge_meets_threshold(client, classroom, database_url):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    s1_id = user_id(database_url, "s1")
    kp = point(client, t1, "电化学")
    q = question(client, t1, "考试加练习")
    link(client, t1, q["id"], [kp["id"]])

    take(client, t1, s1, classroom, [q], {q["id"]: "B"}, "考试错一次")
    add_practice(database_url, s1_id, q["id"], True)

    assert weak(client, s1)["items"] == [
        {
            "knowledge_point_id": kp["id"],
            "name": "电化学",
            "answered_count": 2,
            "wrong_count": 1,
            "error_rate": 50.0,
        }
    ]


def test_practice_without_knowledge_point_is_ignored(client, classroom, database_url):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    s1_id = user_id(database_url, "s1")
    q = question(client, t1, "练习未归类")

    add_practice(database_url, s1_id, q["id"], False)

    data = weak(client, s1)
    assert data["has_data"] is True
    assert data["items"] == []


def test_merge_recomputes_practice_records(client, classroom, database_url):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    s1_id = user_id(database_url, "s1")
    source = point(client, t1, "氧化还原")
    target = point(client, t1, "电化学")
    q1 = question(client, t1, "氧化还原练习题")
    q2 = question(client, t1, "电化学练习题")
    link(client, t1, q1["id"], [source["id"]])
    link(client, t1, q2["id"], [target["id"]])

    for _ in range(2):
        add_practice(database_url, s1_id, q1["id"], False)
        add_practice(database_url, s1_id, q2["id"], False)

    before = weak(client, s1)["items"]
    assert {item["name"] for item in before} == {"氧化还原", "电化学"}

    merged = client.post(
        f"/api/knowledge-points/{source['id']}/merge",
        headers=auth(t1),
        json={"target_id": target["id"]},
    )
    assert merged.status_code == 200, merged.text

    after = weak(client, s1)["items"]
    assert len(after) == 1
    assert after[0]["knowledge_point_id"] == target["id"]
    assert after[0]["answered_count"] == 4
    assert after[0]["wrong_count"] == 4
    assert after[0]["error_rate"] == 100.0


def test_only_all_correct_point_returns_empty_weak_list(client, classroom):
    """数据够但全对：不进入弱项；旧接口仍返回 has_data=true。"""
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    kp = point(client, t1, "元素周期律")
    q = question(client, t1, "全对唯一知识点")
    link(client, t1, q["id"], [kp["id"]])

    take(client, t1, s1, classroom, [q], {q["id"]: "A"}, "全对一")
    take(client, t1, s1, classroom, [q], {q["id"]: "A"}, "全对二")

    data = weak(client, s1)
    assert data["has_data"] is True
    assert data["items"] == []
