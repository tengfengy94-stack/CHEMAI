"""评测轨迹：存储配对、接口鉴权与生产隔离。"""
import json

import pytest
from fastapi.testclient import TestClient

from app.agent import FakeChatModel
from app.config import DEFAULT_DATABASE_PATH
from app.eval_trace import EvalTraceStore
from app.main import create_app
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
    assert str(DEFAULT_DATABASE_PATH.resolve()) != database_url
    app = create_app(database_url=database_url, seed=False, eval_mode=True)
    with TestClient(app) as client:
        yield client


def test_trace_store_pairs_start_and_end():
    store = EvalTraceStore()
    store.start("student:1:eval:a", "run-1", "search_questions", {"limit": 3})
    store.end("student:1:eval:a", "run-1", {"found": True, "questions": []}, True)

    items = store.get("student:1:eval:a")
    assert len(items) == 1
    assert items[0]["tool"] == "search_questions"
    assert items[0]["args"] == {"limit": 3}
    assert items[0]["result"] == {"found": True, "questions": []}
    assert items[0]["ok"] is True


def test_trace_store_keeps_same_tool_twice():
    store = EvalTraceStore()
    store.start("t", "run-1", "due_reviews", {"limit": 5})
    store.end("t", "run-1", {"total": 1}, True)
    store.start("t", "run-2", "due_reviews", {"limit": 2})
    store.end("t", "run-2", {"total": 1}, True)

    items = store.get("t")
    assert [item["args"] for item in items] == [{"limit": 5}, {"limit": 2}]
    assert [item["ok"] for item in items] == [True, True]


def test_trace_store_keeps_failed_call():
    store = EvalTraceStore()
    store.start("t", "run-1", "exam_result", {})
    store.end("t", "run-1", {"found": False, "message": "这一项没查到"}, False)

    item = store.get("t")[0]
    assert item["ok"] is False
    assert item["result"]["found"] is False


def test_trace_endpoint_returns_args_and_result(eval_client, make_user):
    make_user("s1", role="student", name="陈小明")
    token = login(eval_client, "s1")
    install_agents(eval_client, FakeChatModel())

    with eval_client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": "知识地图里氧化还原属于哪一块", "conversation_id": "case-trace"},
        headers=auth(token),
    ) as response:
        assert response.status_code == 200
        events = _sse_events(response)
    assert events[-1]["event"] == "end"
    tool_events = [event for event in events if event["event"] == "tool"]
    assert tool_events
    assert all("args" not in event["data"] for event in tool_events)
    assert all("arguments" not in event["data"] for event in tool_events)

    trace = eval_client.get(
        "/api/eval/trace",
        params={"conversation_id": "case-trace"},
        headers=auth(token),
    )
    assert trace.status_code == 200
    items = trace.json()["data"]["items"]
    assert items
    assert items[0]["tool"] == "knowledge_map"
    assert items[0]["args"]["point_name"] == "氧化还原"
    assert items[0]["result"] is not None
    assert items[0]["ok"] is True


def test_trace_endpoint_rejects_other_student(eval_client, make_user):
    make_user("s1", role="student", name="陈小明")
    make_user("s2", role="student", name="林晓华")
    token_one = login(eval_client, "s1")
    token_two = login(eval_client, "s2")
    install_agents(eval_client, FakeChatModel())

    with eval_client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": "你好", "conversation_id": "case-trace"},
        headers=auth(token_one),
    ) as response:
        assert response.status_code == 200
        _sse_events(response)

    trace = eval_client.get(
        "/api/eval/trace",
        params={"conversation_id": "case-trace"},
        headers=auth(token_two),
    )
    assert trace.status_code == 404


def test_trace_endpoint_requires_login(eval_client):
    response = eval_client.get(
        "/api/eval/trace", params={"conversation_id": "case-trace"}
    )
    assert response.status_code == 401


def test_trace_endpoint_absent_in_production(client):
    response = client.get(
        "/api/eval/trace", params={"conversation_id": "case-trace"}
    )
    assert response.status_code == 404


def test_trace_endpoint_rejects_invalid_line(eval_client, make_user):
    make_user("s1", role="student", name="陈小明")
    token = login(eval_client, "s1")
    response = eval_client.get(
        "/api/eval/trace",
        params={"conversation_id": "Case Trace"},
        headers=auth(token),
    )
    assert response.status_code == 422
