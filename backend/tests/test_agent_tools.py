"""Agent 只读工具 1–5：搜题、知识点、画像、知识地图、讲错题。"""
import json

import pytest

from agent_helpers import ToolCallModel, install_agents, run_agent, tool_outputs
from app.agent import FakeChatModel, TOOL_FINAL_ANSWER
from exam_helpers import (
    attempt_for_paper,
    make_approved,
    paper_with,
    submit_answers,
)
from helpers import auth, login


@pytest.fixture
def people(make_user, make_class):
    make_user("t1", role="teacher")
    class_id = make_class("一班", "t1")
    make_user("s1", role="student", name="学生一", class_id=class_id)
    return class_id


def _point(client, token, name, parent_id=None, aliases=None):
    r = client.post(
        "/api/knowledge-points",
        headers=auth(token),
        json={"name": name, "parent_id": parent_id, "aliases": aliases or []},
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


def _parse_events(lines):
    events = []
    current = {}
    for line in lines:
        if line == "":
            if current:
                events.append(current)
                current = {}
        elif line.startswith(":"):
            continue
        elif line.startswith("event: "):
            current["event"] = line[len("event: "):]
        elif line.startswith("data: "):
            current["data"] = line[len("data: "):]
    if current:
        events.append(current)
    return events


def test_search_questions_returns_approved_without_answers(client, people):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    approved = make_approved(client, t1, stem="已通过题")
    client.post(
        "/api/questions",
        headers=auth(t1),
        json={
            "stem": "草稿题",
            "type": "single",
            "options": ["A", "B"],
            "answer": "A",
            "difficulty": 1,
        },
    )
    install_agents(client, FakeChatModel())

    result = run_agent(client, "student", "s1", "给我找题练")
    output = tool_outputs(result)[0]
    ids = [item["id"] for item in output["questions"]]
    assert ids == [approved["id"]]
    for item in output["questions"]:
        assert set(item) == {"id", "stem", "type", "difficulty"}
        assert "answer" not in item and "explanation" not in item


def test_find_point_and_knowledge_map(client, people):
    t1 = login(client, "t1")
    root = _point(client, t1, "氧化还原", aliases=["redox"])
    child = _point(client, t1, "氧化剂", parent_id=root["id"])
    install_agents(client, FakeChatModel())

    result = run_agent(client, "student", "s1", "氧化还原这个知识点")
    output = tool_outputs(result)[0]
    assert output["point"]["name"] == "氧化还原"

    result = run_agent(client, "student", "s1", "氧化还原的前置是什么", thread="map-thread")
    output = tool_outputs(result)[0]
    assert output["parent"] is None
    assert output["children"] == [child["name"]]


def test_student_profile_reflects_new_practice(client, people):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    point = _point(client, t1, "氧化还原")
    question = make_approved(client, t1, stem="氧化还原题")
    _set_points(client, t1, question["id"], [point["id"]])

    for _ in range(2):
        r = client.post(
            "/api/practice/answers",
            headers=auth(s1),
            json={"question_id": question["id"], "answer": "B", "difficulty": 2},
        )
        assert r.status_code == 200, r.text

    install_agents(client, FakeChatModel())
    result = run_agent(client, "student", "s1", "我哪块弱")
    output = tool_outputs(result)[0]
    assert output["has_data"] is True
    assert output["weak_items"][0]["knowledge_point_id"] == point["id"]
    assert output["weak_items"][0]["wrong_count"] == 2


def test_explain_wrong_question_and_similar(client, people):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    point = _point(client, t1, "氧化还原")
    wrong = make_approved(client, t1, stem="我答错的题")
    similar = make_approved(client, t1, stem="同知识点另一题")
    _set_points(client, t1, wrong["id"], [point["id"]])
    _set_points(client, t1, similar["id"], [point["id"]])
    paper = paper_with(client, t1, people, [wrong], "周测")
    attempt = attempt_for_paper(client, s1, paper["id"])
    submit_answers(client, s1, attempt, {wrong["id"]: "B"})

    install_agents(client, FakeChatModel())
    result = run_agent(client, "student", "s1", "这道题为什么错")
    output = tool_outputs(result)[0]
    assert output["question"]["student_answer"] == "B"
    assert output["question"]["answer"] == "A"
    assert output["similar"]["id"] == similar["id"]


def test_exam_in_progress_refuses_explain(client, people):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    question = make_approved(client, t1, stem="考试中的题")
    paper = paper_with(client, t1, people, [question], "考试")
    attempt = attempt_for_paper(client, s1, paper["id"])
    started = client.post(f"/api/attempts/{attempt['id']}/start", headers=auth(s1))
    assert started.status_code == 200, started.text

    install_agents(client, FakeChatModel())
    result = run_agent(client, "student", "s1", "这道题为什么错")
    output = tool_outputs(result)[0]
    assert output["found"] is False
    assert "考完" in output["message"]


def test_tool_exception_returns_chinese_failure(client, people, monkeypatch):
    import app.agent_tools as agent_tools

    login(client, "t1")
    login(client, "s1")
    install_agents(client, ToolCallModel(tool_name="student_profile"))

    def boom(*args, **kwargs):
        raise RuntimeError("db is locked")

    monkeypatch.setattr(agent_tools.reporting, "student_report", boom)
    result = run_agent(client, "student", "s1", "我哪块弱")
    output = tool_outputs(result)[0]
    assert output["found"] is False
    assert "没查到" in output["message"]


def test_explain_wrong_question_emits_similar_plan_event(client, people):
    t1 = login(client, "t1")
    s1 = login(client, "s1")
    point = _point(client, t1, "氧化还原")
    wrong = make_approved(client, t1, stem="我答错的题")
    similar = make_approved(client, t1, stem="同知识点另一题")
    _set_points(client, t1, wrong["id"], [point["id"]])
    _set_points(client, t1, similar["id"], [point["id"]])
    paper = paper_with(client, t1, people, [wrong], "周测")
    attempt = attempt_for_paper(client, s1, paper["id"])
    submit_answers(client, s1, attempt, {wrong["id"]: "B"})

    install_agents(client, FakeChatModel())
    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": "这道题为什么错"},
        headers=auth(s1),
    ) as response:
        events = _parse_events(response.iter_lines())

    plan_events = [
        json.loads(event["data"])
        for event in events
        if event["event"] == "tool" and "similar_question_result" in event["data"]
    ]
    assert plan_events
    assert plan_events[0]["questions"] == [similar["id"]]


def test_sse_tool_event_before_text_and_no_args(client, people):
    login(client, "t1")
    login(client, "s1")
    install_agents(client, FakeChatModel())
    token = login(client, "s1")

    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": "我哪块弱"},
        headers=auth(token),
    ) as response:
        assert response.status_code == 200
        events = _parse_events(response.iter_lines())

    assert events[0]["event"] == "tool"
    tool = json.loads(events[0]["data"])
    assert tool["name"] == "student_profile"
    assert "label" in tool
    assert "args" not in tool and "arguments" not in tool
    tool_events = [event for event in events if event["event"] == "tool"]
    assert len(tool_events) == 1
    text_events = [event for event in events if event["event"] == "text"]
    # 句级缓冲后，同一句里的多个模型分片会合并成一个 text。
    assert text_events
    text = "".join(json.loads(event["data"])["delta"] for event in text_events)
    assert text == TOOL_FINAL_ANSWER
    assert events[-1]["event"] == "end"


def test_teacher_has_no_student_profile_tool(client, people):
    login(client, "t1")
    token = login(client, "t1")
    install_agents(client, FakeChatModel())

    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": "我哪块弱"},
        headers=auth(token),
    ) as response:
        events = _parse_events(response.iter_lines())

    assert all(event["event"] != "tool" for event in events)
    assert events[-1]["event"] == "end"


def test_general_question_has_no_tool_event(client, people):
    login(client, "s1")
    token = login(client, "s1")
    install_agents(client, FakeChatModel())

    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": "什么是氧化还原"},
        headers=auth(token),
    ) as response:
        events = _parse_events(response.iter_lines())

    assert all(event["event"] != "tool" for event in events)
    assert events[-1]["event"] == "end"


def test_student_class_question_is_refused(client, people):
    login(client, "t1")
    install_agents(client, FakeChatModel())
    token = login(client, "s1")

    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": "我们班哪块最弱"},
        headers=auth(token),
    ) as response:
        events = _parse_events(response.iter_lines())

    assert all(event["event"] != "tool" for event in events)
    text = "".join(
        json.loads(event["data"])["delta"]
        for event in events
        if event["event"] == "text"
    )
    assert "班级概况我查不了" in text
    assert "自己" in text
    assert events[-1]["event"] == "end"
