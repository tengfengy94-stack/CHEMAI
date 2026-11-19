"""登录、刷新、身份解析与种子账号的接口测试（tasks 2.2、2.3、4.1）。"""
from datetime import datetime, timedelta, timezone

import jwt
from fastapi.testclient import TestClient

from app import auth as authlib
from app.main import create_app
from helpers import DEMO_PASSWORD, auth, login


def test_login_success_returns_tokens_and_identity(client, make_user):
    make_user("teacher01", role="teacher")
    r = client.post("/api/auth/login", json={"username": "teacher01", "password": DEMO_PASSWORD})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["access_token"] and data["refresh_token"]
    assert data["user"]["username"] == "teacher01"
    assert data["user"]["name"] == "teacher01"
    assert data["user"]["role"] == "teacher"


def test_login_student_returns_class(client, make_user, make_class):
    make_user("teacher01", role="teacher")
    class_id = make_class("高一(1)班", "teacher01")
    make_user("s0101", role="student", class_id=class_id)
    r = client.post("/api/auth/login", json={"username": "s0101", "password": DEMO_PASSWORD})
    assert r.json()["data"]["user"]["class"] == {"id": class_id, "name": "高一(1)班"}


def test_login_teacher_returns_taught_classes(client, make_user, make_class):
    make_user("teacher01", role="teacher")
    make_class("高一(1)班", "teacher01")
    make_class("高一(2)班", "teacher01")
    r = client.post("/api/auth/login", json={"username": "teacher01", "password": DEMO_PASSWORD})
    names = [c["name"] for c in r.json()["data"]["user"]["classes"]]
    assert names == ["高一(1)班", "高一(2)班"]


def test_wrong_password_rejected(client, make_user):
    make_user("teacher01", role="teacher")
    r = client.post("/api/auth/login", json={"username": "teacher01", "password": "不对"})
    assert r.status_code == 401
    assert r.json()["error"] == "用户名或密码不对"


def test_unknown_username_gets_same_message_as_wrong_password(client):
    r = client.post("/api/auth/login", json={"username": "ghost", "password": "无所谓"})
    assert r.status_code == 401
    assert r.json()["error"] == "用户名或密码不对"


def test_refresh_returns_new_access_token(client, make_user):
    make_user("teacher01", role="teacher")
    data = client.post(
        "/api/auth/login", json={"username": "teacher01", "password": DEMO_PASSWORD}
    ).json()["data"]
    r = client.post(
        "/api/auth/refresh", headers=auth(data["refresh_token"])
    )
    assert r.status_code == 200
    new_token = r.json()["data"]["access_token"]
    assert authlib.decode_token(new_token, "access")["sub"] == "teacher01"


def test_expired_refresh_rejected(client, make_user):
    make_user("teacher01", role="teacher")
    expired = jwt.encode(
        {"sub": "teacher01", "type": "refresh", "exp": datetime.now(timezone.utc) - timedelta(hours=1)},
        authlib.jwt_secret(),
        algorithm=authlib.ALGORITHM,
    )
    r = client.post("/api/auth/refresh", headers=auth(expired))
    assert r.status_code == 401


def test_access_token_cannot_refresh(client, make_user):
    make_user("teacher01", role="teacher")
    token = login(client, "teacher01")
    r = client.post("/api/auth/refresh", headers=auth(token))
    assert r.status_code == 401


# ---- 三层权限的第一层：登录校验（tasks 2.3，也是六条越权里的两条）----

def test_missing_token_gets_401_and_no_data(client):
    r = client.get("/api/questions")
    assert r.status_code == 401
    assert r.json()["data"] is None


def test_forged_token_gets_401_and_no_data(client, make_user):
    make_user("teacher01", role="teacher")
    forged = jwt.encode(
        {
            "sub": "teacher01",
            "type": "access",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        "不是密钥的密钥",
        algorithm=authlib.ALGORITHM,
    )
    r = client.get("/api/questions", headers=auth(forged))
    assert r.status_code == 401
    assert r.json()["data"] is None


def test_expired_access_token_gets_401(client, make_user):
    make_user("teacher01", role="teacher")
    expired = jwt.encode(
        {"sub": "teacher01", "type": "access", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        authlib.jwt_secret(),
        algorithm=authlib.ALGORITHM,
    )
    r = client.get("/api/questions", headers=auth(expired))
    assert r.status_code == 401


def test_valid_token_returns_data(client, make_user):
    make_user("teacher01", role="teacher")
    token = login(client, "teacher01")
    r = client.get("/api/questions", headers=auth(token))
    assert r.status_code == 200
    assert r.json()["data"] == []


# ---- 种子账号（tasks 4.1）：空库启动即有演示账号 ----

def start(database_url):
    return TestClient(create_app(database_url=database_url, seed=True))


def test_seed_accounts_can_login_on_empty_database(database_url):
    with start(database_url) as c:
        for username in ("admin", "teacher01", "s0101", "s0102", "s0201"):
            r = c.post("/api/auth/login", json={"username": username, "password": DEMO_PASSWORD})
            assert r.status_code == 200, username


def test_seed_accounts_missing_password_or_unknown_user_rejected(database_url):
    with start(database_url) as c:
        r = c.post("/api/auth/login", json={"username": "teacher01", "password": "错的"})
        assert r.status_code == 401
        r = c.post("/api/auth/login", json={"username": "nobody", "password": DEMO_PASSWORD})
        assert r.status_code == 401


def test_teacher01_sees_three_seed_questions_after_login(database_url):
    with start(database_url) as c:
        token = login(c, "teacher01")
        data = c.get("/api/questions", headers=auth(token)).json()["data"]
    assert len(data) == 3
    assert all(q["created_by"] == "teacher01" for q in data)


def test_s0101_sees_only_approved_seed_question_without_answers(database_url):
    with start(database_url) as c:
        token = login(c, "s0101")
        data = c.get("/api/questions", headers=auth(token)).json()["data"]
    assert len(data) == 1
    assert data[0]["status"] == "approved"
    assert "answer" not in data[0]
    assert "explanation" not in data[0]


def test_restarting_does_not_duplicate_seed_accounts(database_url):
    """重复启动不重插账号：唯一约束会让重复插入直接炸掉启动，登录仍成功即说明没炸。"""
    for _ in range(2):
        with start(database_url):
            pass
    with start(database_url) as c:
        assert c.post(
            "/api/auth/login", json={"username": "teacher01", "password": DEMO_PASSWORD}
        ).status_code == 200
