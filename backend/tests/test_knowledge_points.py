"""知识点：两层结构、别名、题目关联、合并与权限（第 07 章）。"""
import pytest
from exam_helpers import create_question
from helpers import auth, login


@pytest.fixture
def people(make_user):
    make_user("t1", role="teacher")
    make_user("t2", role="teacher")
    make_user("admin", role="admin")
    make_user("s1", role="student")
    return None


def point(client, token, name, parent_id=None, aliases=None):
    r = client.post(
        "/api/knowledge-points",
        headers=auth(token),
        json={"name": name, "parent_id": parent_id, "aliases": aliases or []},
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


def tree(client, token):
    r = client.get("/api/knowledge-points", headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()["data"]["items"]


def set_points(client, token, question_id, point_ids, primary_point_id=None):
    body = {"knowledge_point_ids": point_ids}
    if primary_point_id is not None:
        body["primary_point_id"] = primary_point_id
    return client.put(
        f"/api/questions/{question_id}/knowledge-points",
        headers=auth(token),
        json=body,
    )


def node_by_name(nodes, name):
    for node in nodes:
        if node["name"] == name:
            return node
        found = node_by_name(node.get("children", []), name)
        if found:
            return found
    return None


def test_two_level_tree_and_duplicate_name(client, people):
    t1 = login(client, "t1")
    root = point(client, t1, "氧化还原")
    child = point(client, t1, "氧化剂", parent_id=root["id"])
    assert root["parent_id"] is None
    assert child["parent_id"] == root["id"]

    third = client.post(
        "/api/knowledge-points",
        headers=auth(t1),
        json={"name": "氧化剂之一", "parent_id": child["id"]},
    )
    assert third.status_code == 400

    duplicate = client.post(
        "/api/knowledge-points", headers=auth(t1), json={"name": "氧化还原"}
    )
    assert duplicate.status_code == 400

    missing = client.post(
        "/api/knowledge-points",
        headers=auth(t1),
        json={"name": "孤立节点", "parent_id": 99999},
    )
    assert missing.status_code == 404

    nodes = tree(client, t1)
    assert len(nodes) == 1
    assert nodes[0]["name"] == "氧化还原"
    assert nodes[0]["children"][0]["name"] == "氧化剂"


def test_aliases_rename_and_conflicts(client, people):
    t1 = login(client, "t1")
    first = point(client, t1, "氧化还原", aliases=[" 氧化还原反应 ", "氧化还原反应"])
    assert first["aliases"] == ["氧化还原反应"]

    second = point(client, t1, "电化学")
    clash = client.put(
        f"/api/knowledge-points/{second['id']}",
        headers=auth(t1),
        json={"aliases": ["氧化还原反应"]},
    )
    assert clash.status_code == 400

    renamed = client.put(
        f"/api/knowledge-points/{first['id']}",
        headers=auth(t1),
        json={"name": "氧化还原反应", "aliases": ["redox"]},
    )
    assert renamed.status_code == 200, renamed.text
    data = renamed.json()["data"]
    assert data["name"] == "氧化还原反应"
    assert set(data["aliases"]) == {"氧化还原", "redox"}

    rename_clash = client.put(
        f"/api/knowledge-points/{second['id']}",
        headers=auth(t1),
        json={"name": "氧化还原"},
    )
    assert rename_clash.status_code == 400


def test_question_association_replace_dedup_and_clear(client, people):
    t1 = login(client, "t1")
    t2 = login(client, "t2")
    admin = login(client, "admin")
    student = login(client, "s1")
    redox = point(client, t1, "氧化还原")
    electro = point(client, t1, "电化学")
    question = create_question(client, t1)
    other = create_question(client, t2, stem="另一道题")

    r = set_points(client, t1, question["id"], [redox["id"], electro["id"], redox["id"]])
    assert r.status_code == 200, r.text
    assert [item["id"] for item in r.json()["data"]["knowledge_points"]] == [
        redox["id"],
        electro["id"],
    ]
    assert node_by_name(tree(client, t1), "氧化还原")["question_count"] == 1

    r = set_points(client, t1, question["id"], [electro["id"]])
    assert [item["id"] for item in r.json()["data"]["knowledge_points"]] == [electro["id"]]
    assert node_by_name(tree(client, t1), "氧化还原")["question_count"] == 0

    r = set_points(client, t1, question["id"], [])
    assert r.json()["data"]["knowledge_points"] == []

    assert set_points(client, t2, question["id"], [redox["id"]]).status_code == 403
    assert set_points(client, student, question["id"], [redox["id"]]).status_code == 403
    assert set_points(client, admin, other["id"], [redox["id"]]).status_code == 200
    assert set_points(client, t1, 99999, [redox["id"]]).status_code == 404
    assert set_points(client, t1, question["id"], [99999]).status_code == 404


def test_point_questions_lists_own_questions_and_admin_all(client, people):
    t1 = login(client, "t1")
    t2 = login(client, "t2")
    admin = login(client, "admin")
    student = login(client, "s1")
    redox = point(client, t1, "氧化还原")
    q1 = create_question(client, t1, stem="t1 的题")
    q2 = create_question(client, t2, stem="t2 的题")
    assert set_points(client, t1, q1["id"], [redox["id"]]).status_code == 200
    assert set_points(client, t2, q2["id"], [redox["id"]]).status_code == 200

    own = client.get(
        f"/api/knowledge-points/{redox['id']}/questions", headers=auth(t1)
    )
    assert own.status_code == 200, own.text
    own_data = own.json()["data"]
    assert own_data["total"] == 1
    assert [item["id"] for item in own_data["items"]] == [q1["id"]]
    assert "answer" in own_data["items"][0]

    everything = client.get(
        f"/api/knowledge-points/{redox['id']}/questions?page_size=1",
        headers=auth(admin),
    )
    assert everything.status_code == 200, everything.text
    assert everything.json()["data"]["total"] == 2
    assert len(everything.json()["data"]["items"]) == 1

    assert (
        client.get(
            f"/api/knowledge-points/{redox['id']}/questions", headers=auth(student)
        ).status_code
        == 403
    )
    assert (
        client.get("/api/knowledge-points/99999/questions", headers=auth(t1)).status_code
        == 404
    )


def test_question_primary_point_and_readback(client, people):
    t1 = login(client, "t1")
    t2 = login(client, "t2")
    redox = point(client, t1, "氧化还原")
    electro = point(client, t1, "电化学")
    third = point(client, t1, "化学平衡")
    question = create_question(client, t1, stem="主次题")

    r = set_points(
        client,
        t1,
        question["id"],
        [redox["id"], electro["id"]],
        primary_point_id=redox["id"],
    )
    assert r.status_code == 200, r.text
    flags = {item["id"]: item["is_primary"] for item in r.json()["data"]["knowledge_points"]}
    assert flags == {redox["id"]: True, electro["id"]: False}

    readback = client.get(
        f"/api/questions/{question['id']}/knowledge-points", headers=auth(t1)
    )
    assert readback.status_code == 200, readback.text
    assert {
        item["id"]: item["is_primary"]
        for item in readback.json()["data"]["knowledge_points"]
    } == {redox["id"]: True, electro["id"]: False}
    assert (
        client.get(
            f"/api/questions/{question['id']}/knowledge-points", headers=auth(t2)
        ).status_code
        == 403
    )

    moved = set_points(
        client,
        t1,
        question["id"],
        [redox["id"], electro["id"]],
        primary_point_id=electro["id"],
    )
    assert moved.status_code == 200, moved.text
    assert {
        item["id"]: item["is_primary"]
        for item in moved.json()["data"]["knowledge_points"]
    } == {redox["id"]: False, electro["id"]: True}

    invalid = set_points(
        client,
        t1,
        question["id"],
        [redox["id"]],
        primary_point_id=third["id"],
    )
    assert invalid.status_code == 400
    assert "主知识点" in invalid.json()["error"]


def test_merge_moves_aliases_links_and_children(client, people):
    t1 = login(client, "t1")
    source = point(client, t1, "氧化还原", aliases=["redox"])
    source_child = point(client, t1, "氧化剂", parent_id=source["id"])
    target = point(client, t1, "电化学", aliases=["electrochem"])
    target_child = point(client, t1, "原电池", parent_id=target["id"])

    q1 = create_question(client, t1, stem="共同题")
    q2 = create_question(client, t1, stem="目标题")
    set_points(client, t1, q1["id"], [source["id"], target["id"]])
    set_points(client, t1, q2["id"], [target["id"]])

    r = client.post(
        f"/api/knowledge-points/{source['id']}/merge",
        headers=auth(t1),
        json={"target_id": target["id"]},
    )
    assert r.status_code == 200, r.text
    merged = r.json()["data"]
    assert merged["id"] == target["id"]
    assert set(merged["aliases"]) == {"electrochem", "氧化还原", "redox"}
    assert merged["question_count"] == 2

    nodes = tree(client, t1)
    assert [node["id"] for node in nodes] == [target["id"]]
    assert {child["id"] for child in nodes[0]["children"]} == {
        source_child["id"],
        target_child["id"],
    }
    assert node_by_name(nodes, "氧化还原") is None
    assert node_by_name(nodes, "氧化剂")["parent_id"] == target["id"]


def test_merge_rejects_self_child_and_third_level(client, people):
    t1 = login(client, "t1")
    source = point(client, t1, "物质结构")
    source_child = point(client, t1, "原子结构", parent_id=source["id"])
    target = point(client, t1, "元素周期律")
    target_child = point(client, t1, "周期表", parent_id=target["id"])

    def merge(src, dst):
        return client.post(
            f"/api/knowledge-points/{src}/merge",
            headers=auth(t1),
            json={"target_id": dst},
        ).status_code

    assert merge(source["id"], source["id"]) == 400
    assert merge(source["id"], source_child["id"]) == 400
    assert merge(source["id"], target_child["id"]) == 400
    assert merge(99999, target["id"]) == 404
    assert merge(source["id"], 99999) == 404


def test_request_validation_messages_are_chinese(client, people):
    t1 = login(client, "t1")
    missing = client.post("/api/knowledge-points", headers=auth(t1), json={"parent_id": None})
    assert missing.status_code == 422
    assert "名称" in missing.json()["error"]

    bad_parent = client.post(
        "/api/knowledge-points",
        headers=auth(t1),
        json={"name": "新点", "parent_id": "abc"},
    )
    assert bad_parent.status_code == 422
    assert "上级知识点" in bad_parent.json()["error"]

    bad_links = client.put(
        "/api/questions/1/knowledge-points",
        headers=auth(t1),
        json={"knowledge_point_ids": "abc"},
    )
    assert bad_links.status_code == 422
    assert "知识点" in bad_links.json()["error"]


def test_delete_question_clears_knowledge_links(client, people):
    t1 = login(client, "t1")
    kp = point(client, t1, "临时知识点")
    question = create_question(client, t1, stem="带知识点关联的题")
    assert set_points(client, t1, question["id"], [kp["id"]]).status_code == 200

    deleted = client.delete(f"/api/questions/{question['id']}", headers=auth(t1))
    assert deleted.status_code == 200, deleted.text
    assert node_by_name(tree(client, t1), "临时知识点")["question_count"] == 0
    assert set_points(client, t1, question["id"], [kp["id"]]).status_code == 404


def test_read_permission_and_shared_writes(client, people):
    t1 = login(client, "t1")
    t2 = login(client, "t2")
    student = login(client, "s1")
    created = point(client, t1, "共享词条")

    # 老师既能看，也能改别人建的知识点
    assert client.get("/api/knowledge-points", headers=auth(t2)).status_code == 200
    updated = client.put(
        f"/api/knowledge-points/{created['id']}",
        headers=auth(t2),
        json={"aliases": ["别名"]},
    )
    assert updated.status_code == 200, updated.text

    assert client.get("/api/knowledge-points", headers=auth(student)).status_code == 403
