"""用户状态：停用后不能登录，已签发 token 立即失效，发布跳过停用学生。"""
from sqlalchemy import select, update

from app.db import make_engine, make_session_factory
from app.models import User
from exam_helpers import add_question, create_paper, make_approved, publish
from helpers import auth, login


def set_status(database_url, username, status):
    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    with factory() as session:
        session.execute(update(User).where(User.username == username).values(status=status))
        session.commit()
    engine.dispose()


def test_inactive_user_cannot_login_or_use_existing_token(
    client, database_url, make_user
):
    make_user("s1", role="student")
    s1 = login(client, "s1")
    set_status(database_url, "s1", "inactive")

    login_attempt = client.post(
        "/api/auth/login", json={"username": "s1", "password": "chem2026"}
    )
    assert login_attempt.status_code == 403
    assert "停用" in login_attempt.json()["error"]

    blocked = client.get("/api/questions", headers=auth(s1))
    assert blocked.status_code == 401
    assert "停用" in blocked.json()["error"]


def test_publish_skips_inactive_students(client, database_url, make_user, make_class):
    make_user("t1", role="teacher")
    class_id = make_class("高一(1)班", "t1")
    make_user("s1", role="student", class_id=class_id)
    make_user("s2", role="student", class_id=class_id)
    set_status(database_url, "s2", "inactive")

    t1 = login(client, "t1")
    question = make_approved(client, t1)
    paper = create_paper(client, t1)
    add_question(client, t1, paper["id"], question["id"])

    published = publish(client, t1, paper["id"], class_id)
    assert published.status_code == 200, published.text
    data = published.json()["data"]
    assert data["created"] == 1
    # 停用学生不进入发布名单，所以不计入 skipped（skipped 只表示重复记录）。
    assert data["skipped"] == 0

    classes = client.get("/api/classes", headers=auth(t1)).json()["data"]["items"]
    assert classes[0]["student_count"] == 1

    s1 = login(client, "s1")
    attempts = client.get("/api/attempts", headers=auth(s1)).json()["data"]["items"]
    assert len(attempts) == 1
    s2_login = client.post(
        "/api/auth/login", json={"username": "s2", "password": "chem2026"}
    )
    assert s2_login.status_code == 403
