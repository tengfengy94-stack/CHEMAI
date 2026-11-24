"""评测模式：对话线后缀、生产忽略、历史按隔离线读取。"""
import json

import pytest
from fastapi.testclient import TestClient

from app.agent import FakeChatModel
from app.agent_runtime import normalize_conversation_id, thread_id_for
from app.main import create_app
from app.models import User
from agent_helpers import install_agents
from helpers import auth, login


def _sse_events(response):
    events = []
    name = None
    data = []
    for line in response.iter_lines():
        if line.startswith("event:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data.append(line.split(":", 1)[1].strip())
        elif line == "" and name is not None:
            events.append({"event": name, "data": json.loads("".join(data) or "{}")})
            name, data = None, []
    return events


@pytest.fixture
def eval_client(database_url):
    app = create_app(database_url=database_url, seed=False, eval_mode=True)
    with TestClient(app) as client:
        yield client


def test_normalize_conversation_id():
    assert normalize_conversation_id("case-01") == "case-01"
    assert normalize_conversation_id("  Case_01  ") is None
    assert normalize_conversation_id("case 01") is None
    assert normalize_conversation_id("case.01") is None
    assert normalize_conversation_id("") is None
    assert normalize_conversation_id(None) is None


def test_thread_id_for_appends_eval_suffix():
    student = User(id=7, username="s", name="学生", role="student", password_hash="x")
    teacher = User(id=9, username="t", name="老师", role="teacher", password_hash="x")
    admin = User(id=1, username="a", name="管理员", role="admin", password_hash="x")

    assert thread_id_for(student, None, "case-01") == "student:7:eval:case-01"
    assert thread_id_for(teacher, 3, "case-01") == "teacher:9:class:3:eval:case-01"
    assert thread_id_for(admin, None, "case-01") == "admin:1:eval:case-01"
    assert thread_id_for(student) == "student:7"


def test_eval_mode_isolates_conversation_lines(eval_client, make_user):
    make_user("s1", role="student", name="陈小明")
    token = login(eval_client, "s1")
    install_agents(eval_client, FakeChatModel())

    for conversation_id, message in (("case-a", "第一句话"), ("case-b", "第二句话")):
        with eval_client.stream(
            "POST",
            "/api/chat/stream",
            json={"message": message, "conversation_id": conversation_id},
            headers=auth(token),
        ) as response:
            assert response.status_code == 200
            events = _sse_events(response)
        assert events[-1]["event"] == "end"

    first = eval_client.get(
        "/api/chat/history",
        params={"conversation_id": "case-a"},
        headers=auth(token),
    )
    second = eval_client.get(
        "/api/chat/history",
        params={"conversation_id": "case-b"},
        headers=auth(token),
    )
    assert first.status_code == 200
    assert second.status_code == 200
    first_texts = [item["content"] for item in first.json()["data"]["items"]]
    second_texts = [item["content"] for item in second.json()["data"]["items"]]
    assert "第一句话" in first_texts
    assert "第二句话" not in first_texts
    assert "第二句话" in second_texts
    assert "第一句话" not in second_texts


def test_production_ignores_conversation_id(client, make_user):
    make_user("s1", role="student", name="陈小明")
    token = login(client, "s1")
    install_agents(client, FakeChatModel())

    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": "生产模式的一句话", "conversation_id": "case-a"},
        headers=auth(token),
    ) as response:
        assert response.status_code == 200
        events = _sse_events(response)
    assert events[-1]["event"] == "end"

    history = client.get("/api/chat/history", headers=auth(token))
    texts = [item["content"] for item in history.json()["data"]["items"]]
    assert "生产模式的一句话" in texts


def test_other_student_cannot_read_isolated_line(eval_client, make_user):
    make_user("s1", role="student", name="陈小明")
    make_user("s2", role="student", name="林晓华")
    token_one = login(eval_client, "s1")
    token_two = login(eval_client, "s2")
    install_agents(eval_client, FakeChatModel())

    with eval_client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": "只有我能看到", "conversation_id": "case-a"},
        headers=auth(token_one),
    ) as response:
        assert response.status_code == 200
        assert _sse_events(response)[-1]["event"] == "end"

    history = eval_client.get(
        "/api/chat/history",
        params={"conversation_id": "case-a"},
        headers=auth(token_two),
    )
    assert history.status_code == 200
    assert history.json()["data"]["items"] == []
