"""卷子：创建、题目池、加题/减题、发布与并发（第 05 章）。"""
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select, update

from app.auth import hash_password
from app.db import make_engine, make_session_factory
from app.models import AnswerRecord, User
from exam_helpers import (
    BLANK_QUESTION,
    MULTIPLE_QUESTION,
    add_question,
    approve_question,
    create_paper,
    create_question,
    make_approved,
    publish,
)
from helpers import auth, login


@pytest.fixture
def classroom(make_user, make_class):
    make_user("t1", role="teacher")
    class_id = make_class("高一(1)班", "t1")
    make_user("s1", role="student", class_id=class_id)
    make_user("s2", role="student", class_id=class_id)
    return class_id


def make_classroom(make_user, make_class, teacher, name):
    class_id = make_class(name, teacher)
    return class_id


def user_id(database_url, username):
    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    with factory() as session:
        uid = session.scalar(select(User.id).where(User.username == username))
    engine.dispose()
    return uid


def set_student_class(database_url, username, class_id):
    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    with factory() as session:
        session.execute(update(User).where(User.username == username).values(class_id=class_id))
        session.commit()
    engine.dispose()


def records_for(database_url, paper_id):
    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    with factory() as session:
        rows = session.scalars(
            select(AnswerRecord).where(AnswerRecord.paper_id == paper_id)
        ).all()
        result = [(r.student_id, r.class_id, r.status) for r in rows]
    engine.dispose()
    return result


# ---- 3.1 卷子创建、列表、详情 ----

def test_create_list_and_detail(client, make_user):
    make_user("t1", role="teacher")
    make_user("t2", role="teacher")
    make_user("s1", role="student")
    t1 = login(client, "t1")
    t2 = login(client, "t2")
    student = login(client, "s1")

    paper = create_paper(client, t1, "周五周测")
    assert paper["status"] == "draft"
    assert paper["question_count"] == 0
    assert paper["title"] == "周五周测"

    items = client.get("/api/papers", headers=auth(t1)).json()["data"]["items"]
    assert [item["id"] for item in items] == [paper["id"]]

    assert client.get("/api/papers", headers=auth(t2)).json()["data"]["items"] == []
    assert client.get(f"/api/papers/{paper['id']}", headers=auth(t2)).status_code == 403
    assert client.get("/api/papers/99999", headers=auth(t1)).status_code == 404
    assert client.get("/api/papers", headers=auth(student)).status_code == 403


def test_create_paper_rejects_empty_title(client, make_user):
    make_user("t1", role="teacher")
    r = client.post("/api/papers", headers=auth(login(client, "t1")), json={"title": "   "})
    assert r.status_code == 422
    assert "卷子名称不能为空" in r.json()["error"]


def test_classes_list_only_own_with_student_counts(client, make_user, make_class):
    make_user("t1", role="teacher")
    make_user("t2", role="teacher")
    make_user("admin", role="admin")
    class_a = make_class("高一(1)班", "t1")
    class_b = make_class("高一(2)班", "t2")
    make_user("s1", role="student", class_id=class_a)
    make_user("s2", role="student", class_id=class_a)
    make_user("s3", role="student", class_id=class_b)

    teacher = login(client, "t1")
    items = client.get("/api/classes", headers=auth(teacher)).json()["data"]["items"]
    assert items == [{"id": class_a, "name": "高一(1)班", "student_count": 2}]

    admin_items = client.get("/api/classes", headers=auth(login(client, "admin"))).json()["data"]["items"]
    assert {item["name"] for item in admin_items} == {"高一(1)班", "高一(2)班"}
    assert client.get("/api/classes", headers=auth(login(client, "s1"))).status_code == 403


# ---- 3.2 题目池、加题、减题 ----

def test_question_pool_only_own_approved(client, make_user):
    make_user("t1", role="teacher")
    make_user("t2", role="teacher")
    make_user("s1", role="student")
    t1 = login(client, "t1")
    t2 = login(client, "t2")

    own = make_approved(client, t1, stem="自己的通过题", difficulty=3)
    create_question(client, t1, stem="自己的草稿题")
    make_approved(client, t2, stem="别人的通过题")

    items = client.get("/api/papers/pool", headers=auth(t1)).json()["data"]["items"]
    assert [item["id"] for item in items] == [own["id"]]

    filtered = client.get(
        "/api/papers/pool", params={"difficulty": 3}, headers=auth(t1)
    ).json()["data"]["items"]
    assert [item["id"] for item in filtered] == [own["id"]]

    searched = client.get(
        "/api/papers/pool", params={"q": "自己"}, headers=auth(t1)
    ).json()["data"]["items"]
    assert [item["id"] for item in searched] == [own["id"]]

    assert client.get("/api/papers/pool", headers=auth(login(client, "s1"))).status_code == 403


def test_add_question_rules(client, make_user, classroom):
    make_user("t2", role="teacher")
    t1 = login(client, "t1")
    t2 = login(client, "t2")
    question = make_approved(client, t1)
    draft_question = create_question(client, t1, stem="草稿题")
    other_question = make_approved(client, t2, stem="别人的题")
    paper = create_paper(client, t1)

    r = add_question(client, t1, paper["id"], question["id"])
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["added"] is True
    assert data["paper"]["questions"][0]["id"] == question["id"]
    assert data["paper"]["questions"][0]["position"] == 1

    r = add_question(client, t1, paper["id"], question["id"])
    assert r.status_code == 200
    assert r.json()["data"]["added"] is False
    assert len(r.json()["data"]["paper"]["questions"]) == 1

    r = add_question(client, t1, paper["id"], draft_question["id"])
    assert r.status_code == 400
    assert "只有已通过的题" in r.json()["error"]

    r = add_question(client, t1, paper["id"], other_question["id"])
    assert r.status_code == 403
    assert "不是这道题的创建者" in r.json()["error"]

    r = add_question(client, t1, paper["id"], 99999)
    assert r.status_code == 404
    assert "题目不存在" in r.json()["error"]

    publish(client, t1, paper["id"], classroom)
    r = add_question(client, t1, paper["id"], draft_question["id"])
    assert r.status_code == 400
    assert "已发布的卷子不能修改" in r.json()["error"]


def test_remove_question_keeps_positions_and_rejects_published(client, make_user, classroom):
    t1 = login(client, "t1")
    q1 = make_approved(client, t1, stem="第一题")
    q2 = make_approved(client, t1, stem="第二题")
    q3 = make_approved(client, t1, stem="第三题")
    paper = create_paper(client, t1)
    for q in (q1, q2):
        assert add_question(client, t1, paper["id"], q["id"]).status_code == 200

    r = client.delete(
        f"/api/papers/{paper['id']}/questions/{q1['id']}", headers=auth(t1)
    )
    assert r.status_code == 200
    questions = r.json()["data"]["paper"]["questions"]
    assert [item["id"] for item in questions] == [q2["id"]]
    assert questions[0]["position"] == 2

    r = client.delete(
        f"/api/papers/{paper['id']}/questions/{q1['id']}", headers=auth(t1)
    )
    assert r.status_code == 404
    assert "卷子里没有这道题" in r.json()["error"]

    # 减题留空位，新题接在最大位置后面
    assert add_question(client, t1, paper["id"], q3["id"]).status_code == 200
    detail = client.get(f"/api/papers/{paper['id']}", headers=auth(t1)).json()["data"]
    assert [(item["id"], item["position"]) for item in detail["questions"]] == [
        (q2["id"], 2),
        (q3["id"], 3),
    ]

    publish(client, t1, paper["id"], classroom)
    r = client.delete(
        f"/api/papers/{paper['id']}/questions/{q2['id']}", headers=auth(t1)
    )
    assert r.status_code == 400
    assert "已发布的卷子不能修改" in r.json()["error"]


def test_deleting_question_used_by_paper(client, make_user):
    make_user("t1", role="teacher")
    t1 = login(client, "t1")
    question = make_approved(client, t1)
    paper = create_paper(client, t1)
    assert add_question(client, t1, paper["id"], question["id"]).status_code == 200

    r = client.delete(f"/api/questions/{question['id']}", headers=auth(t1))
    assert r.status_code == 409
    assert "1 份卷子" in r.json()["error"]

    assert client.delete(
        f"/api/papers/{paper['id']}/questions/{question['id']}", headers=auth(t1)
    ).status_code == 200
    assert client.delete(f"/api/questions/{question['id']}", headers=auth(t1)).status_code == 200


# ---- 3.3 发布 ----

def test_publish_creates_one_record_per_student_and_is_idempotent(
    client, make_user, database_url, classroom
):
    t1 = login(client, "t1")
    question = make_approved(client, t1)
    paper = create_paper(client, t1)
    assert add_question(client, t1, paper["id"], question["id"]).status_code == 200

    r = publish(client, t1, paper["id"], classroom)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["created"] == 2
    assert data["skipped"] == 0
    assert data["paper"]["status"] == "published"
    assert len(records_for(database_url, paper["id"])) == 2

    r = publish(client, t1, paper["id"], classroom)
    assert r.status_code == 200
    assert r.json()["data"]["created"] == 0
    assert r.json()["data"]["skipped"] == 2
    assert len(records_for(database_url, paper["id"])) == 2

    for username in ("s1", "s2"):
        items = client.get("/api/attempts", headers=auth(login(client, username))).json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["status"] == "pending"


def test_publish_to_thirty_students_creates_thirty_records(
    client, make_user, make_class, database_url
):
    make_user("t1", role="teacher")
    class_id = make_class("大班", "t1")
    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    password_hash = hash_password("chem2026")
    with factory() as session:
        for i in range(30):
            session.add(
                User(
                    username=f"bulk{i:02d}",
                    name=f"学生{i:02d}",
                    role="student",
                    class_id=class_id,
                    password_hash=password_hash,
                )
            )
        session.commit()
    engine.dispose()

    t1 = login(client, "t1")
    question = make_approved(client, t1)
    paper = create_paper(client, t1)
    assert add_question(client, t1, paper["id"], question["id"]).status_code == 200
    r = publish(client, t1, paper["id"], class_id)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["created"] == 30
    assert len(records_for(database_url, paper["id"])) == 30


def test_publish_rejects_empty_paper_and_empty_class(client, make_user, make_class):
    make_user("t1", role="teacher")
    t1 = login(client, "t1")
    class_id = make_class("高一(1)班", "t1")
    make_user("s1", role="student", class_id=class_id)
    empty_class = make_class("空班", "t1")

    empty_paper = create_paper(client, t1)
    r = publish(client, t1, empty_paper["id"], class_id)
    assert r.status_code == 400
    assert "卷子里还没有题" in r.json()["error"]
    assert client.get(f"/api/papers/{empty_paper['id']}", headers=auth(t1)).json()["data"]["status"] == "draft"

    paper = create_paper(client, t1, "有题卷")
    question = make_approved(client, t1)
    assert add_question(client, t1, paper["id"], question["id"]).status_code == 200
    r = publish(client, t1, paper["id"], empty_class)
    assert r.status_code == 400
    assert "该班还没有学生" in r.json()["error"]
    assert client.get(f"/api/papers/{paper['id']}", headers=auth(t1)).json()["data"]["status"] == "draft"


def test_publish_to_other_teachers_class_is_forbidden(client, make_user, make_class):
    make_user("t1", role="teacher")
    make_user("t2", role="teacher")
    t1 = login(client, "t1")
    other_class = make_class("高一(2)班", "t2")
    make_user("s9", role="student", class_id=other_class)
    question = make_approved(client, t1)
    paper = create_paper(client, t1)
    assert add_question(client, t1, paper["id"], question["id"]).status_code == 200

    r = publish(client, t1, paper["id"], other_class)
    assert r.status_code == 403
    assert "只能发布给自己带的班" in r.json()["error"]


def test_publish_second_class_and_transfer_snapshot(
    client, make_user, make_class, database_url, classroom
):
    t1 = login(client, "t1")
    class_b = make_class("高一(2)班", "t1")
    make_user("s3", role="student", class_id=class_b)
    make_user("s4", role="student", class_id=class_b)
    question = make_approved(client, t1)
    paper = create_paper(client, t1)
    assert add_question(client, t1, paper["id"], question["id"]).status_code == 200

    assert publish(client, t1, paper["id"], classroom).status_code == 200
    assert publish(client, t1, paper["id"], class_b).status_code == 200
    records = records_for(database_url, paper["id"])
    assert len(records) == 4
    by_student = {student_id: (class_id, status) for student_id, class_id, status in records}
    assert by_student[user_id(database_url, "s1")][0] == classroom
    assert by_student[user_id(database_url, "s3")][0] == class_b

    # s1 转到 B 班：已有记录仍归 A 班；再发 A 不删除、再发 B 也不重复
    set_student_class(database_url, "s1", class_b)
    r = publish(client, t1, paper["id"], classroom)
    assert r.status_code == 200
    assert r.json()["data"]["created"] == 0
    r = publish(client, t1, paper["id"], class_b)
    assert r.status_code == 200
    assert r.json()["data"]["created"] == 0
    records = records_for(database_url, paper["id"])
    assert len(records) == 4
    assert {sid: cid for sid, cid, _ in records}[user_id(database_url, "s1")] == classroom

    # 新转进 A 班的学生，再发 A 只补这一条
    make_user("s5", role="student", class_id=classroom)
    r = publish(client, t1, paper["id"], classroom)
    assert r.status_code == 200
    assert r.json()["data"]["created"] == 1
    assert len(records_for(database_url, paper["id"])) == 5


def test_publish_to_empty_class_with_history_still_rejected(
    client, make_user, make_class, database_url, classroom
):
    t1 = login(client, "t1")
    class_b = make_class("高一(2)班", "t1")
    question = make_approved(client, t1)
    paper = create_paper(client, t1)
    assert add_question(client, t1, paper["id"], question["id"]).status_code == 200
    assert publish(client, t1, paper["id"], classroom).status_code == 200

    set_student_class(database_url, "s1", class_b)
    set_student_class(database_url, "s2", class_b)
    r = publish(client, t1, paper["id"], classroom)
    assert r.status_code == 400
    assert "该班还没有学生" in r.json()["error"]
    assert len(records_for(database_url, paper["id"])) == 2


def test_concurrent_publish_does_not_duplicate_records(
    client, make_user, database_url, classroom
):
    t1 = login(client, "t1")
    question = make_approved(client, t1)
    paper = create_paper(client, t1)
    assert add_question(client, t1, paper["id"], question["id"]).status_code == 200

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(publish, client, t1, paper["id"], classroom) for _ in range(2)]
        responses = [future.result() for future in futures]

    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    assert len(records_for(database_url, paper["id"])) == 2


def test_publish_and_remove_concurrently_never_publish_empty_paper(
    client, make_user, classroom
):
    t1 = login(client, "t1")
    question = make_approved(client, t1)
    for _ in range(3):
        paper = create_paper(client, t1)
        assert add_question(client, t1, paper["id"], question["id"]).status_code == 200
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(publish, client, t1, paper["id"], classroom),
                pool.submit(
                    client.delete,
                    f"/api/papers/{paper['id']}/questions/{question['id']}",
                    headers=auth(t1),
                ),
            ]
            publish_response, remove_response = [future.result() for future in futures]

        detail = client.get(f"/api/papers/{paper['id']}", headers=auth(t1)).json()["data"]
        if detail["status"] == "published":
            assert len(detail["questions"]) >= 1
        else:
            assert detail["questions"] == []
        assert publish_response.status_code in (200, 400)
        assert remove_response.status_code in (200, 400)


def test_concurrent_add_questions_get_unique_positions(client, make_user):
    make_user("t1", role="teacher")
    t1 = login(client, "t1")
    q1 = make_approved(client, t1, stem="并发题一")
    q2 = make_approved(client, t1, stem="并发题二")
    paper = create_paper(client, t1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(add_question, client, t1, paper["id"], q1["id"]),
            pool.submit(add_question, client, t1, paper["id"], q2["id"]),
        ]
        responses = [future.result() for future in futures]

    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    detail = client.get(f"/api/papers/{paper['id']}", headers=auth(t1)).json()["data"]
    assert sorted(item["position"] for item in detail["questions"]) == [1, 2]


def test_preview_hides_answers_and_lists_published_classes(
    client, classroom, make_user
):
    t1 = login(client, "t1")
    q = make_approved(client, t1)
    paper = create_paper(client, t1)
    add_question(client, t1, paper["id"], q["id"])

    preview = client.get(f"/api/papers/{paper['id']}/preview", headers=auth(t1))
    assert preview.status_code == 200, preview.text
    preview_data = preview.json()["data"]
    assert preview_data["questions"][0]["position"] == 1
    assert preview_data["questions"][0]["stem"] == q["stem"]
    assert "answer" not in preview_data["questions"][0]
    assert "explanation" not in preview_data["questions"][0]

    make_user("t2", role="teacher")
    t2 = login(client, "t2")
    assert client.get(f"/api/papers/{paper['id']}/preview", headers=auth(t2)).status_code == 403

    assert client.get(f"/api/papers/{paper['id']}/classes", headers=auth(t1)).json()[
        "data"
    ]["items"] == []
    assert publish(client, t1, paper["id"], classroom).status_code == 200
    classes = client.get(f"/api/papers/{paper['id']}/classes", headers=auth(t1))
    assert classes.status_code == 200, classes.text
    items = classes.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["class_id"] == classroom
    assert items[0]["student_count"] == 2


def test_papers_and_pool_pagination_metadata(client, make_user):
    make_user("t1", role="teacher")
    make_user("admin", role="admin")
    t1 = login(client, "t1")
    create_paper(client, t1, "卷子一")
    create_paper(client, t1, "卷子二")
    make_approved(client, t1, stem="题一")
    make_approved(client, t1, stem="题二")

    papers = client.get("/api/papers?page=1&page_size=1", headers=auth(t1))
    assert papers.status_code == 200, papers.text
    paper_data = papers.json()["data"]
    assert paper_data["total"] == 2
    assert len(paper_data["items"]) == 1

    pool = client.get("/api/papers/pool?page=2&page_size=1", headers=auth(t1))
    assert pool.status_code == 200, pool.text
    pool_data = pool.json()["data"]
    assert pool_data["total"] == 2
    assert pool_data["page"] == 2
    assert len(pool_data["items"]) == 1

    admin = login(client, "admin")
    all_papers = client.get("/api/papers?page_size=1", headers=auth(admin))
    assert all_papers.status_code == 200, all_papers.text
    assert all_papers.json()["data"]["total"] == 2
