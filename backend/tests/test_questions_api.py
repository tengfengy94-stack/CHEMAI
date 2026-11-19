"""对外接口：/api/health、GET /api/questions、POST /api/questions。"""
import sqlite3

from fastapi.testclient import TestClient

from app.main import create_app

SINGLE = {
    "stem": "下列物质中属于电解质的是",
    "type": "single",
    "options": ["NaCl", "蔗糖", "CO2"],
    "answer": "a",
    "explanation": "",
    "difficulty": 2,
}


def post(client, **changes):
    return client.post("/api/questions", json={**SINGLE, **changes})


# ---- 信封与健康检查（验收 1）----

def test_health_returns_envelope(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"success": True, "data": {"status": "ok"}, "error": None}


def test_unknown_api_path_still_returns_envelope(client):
    r = client.get("/api/nope")
    assert r.status_code == 404
    body = r.json()
    assert body["success"] is False and body["data"] is None and body["error"]


def test_wrong_method_gets_chinese_error_in_envelope(client):
    r = client.delete("/api/health")
    assert r.status_code == 405
    body = r.json()
    assert body["success"] is False and body["data"] is None
    assert body["error"] == "不支持这种请求方式"


# ---- 建题与列表 ----

def test_list_is_empty_on_fresh_database(client):
    r = client.get("/api/questions")
    assert r.json() == {"success": True, "data": [], "error": None}


def test_created_question_has_all_attributes_and_defaults(client):
    r = post(client)
    assert r.status_code == 201
    body = r.json()
    assert body["success"] is True and body["error"] is None
    q = body["data"]
    assert isinstance(q["id"], int)
    assert q["stem"] == SINGLE["stem"]
    assert q["type"] == "single"
    assert q["options"] == ["NaCl", "蔗糖", "CO2"]
    assert q["answer"] == "A"
    assert q["explanation"] is None
    assert q["difficulty"] == 2
    assert q["status"] == "draft"
    assert q["created_by"]
    assert q["created_at"].endswith("Z")


def test_client_cannot_choose_status_on_create(client):
    assert post(client, status="approved").json()["data"]["status"] == "draft"


def test_created_question_appears_in_list_newest_first(client):
    post(client, stem="第一道")
    post(client, stem="第二道")
    stems = [q["stem"] for q in client.get("/api/questions").json()["data"]]
    assert stems == ["第二道", "第一道"]


def test_multiple_choice_answer_is_normalized_on_save(client):
    r = post(client, type="multiple", options=["甲", "乙", "丙"], answer="C,A")
    assert r.json()["data"]["answer"] == "AC"


def test_blank_question_has_no_options(client):
    r = post(client, type="blank", options=None, answer=" 3Fe + 2O2 → Fe3O4 ")
    assert r.status_code == 201
    q = r.json()["data"]
    assert q["options"] is None
    assert q["answer"] == "3Fe + 2O2 → Fe3O4"


# ---- 校验：拒绝并给中文原因，信封不变 ----

def assert_rejected(r, message):
    assert r.status_code == 422
    body = r.json()
    assert body["success"] is False and body["data"] is None
    assert message in body["error"]


def test_rejects_empty_stem(client):
    assert_rejected(post(client, stem="   "), "题干不能为空")


def test_rejects_unknown_type(client):
    assert_rejected(post(client, type="essay"), "题型")


def test_rejects_difficulty_out_of_range(client):
    assert_rejected(post(client, difficulty=4), "难度")


def test_rejects_malformed_difficulty(client):
    assert_rejected(post(client, difficulty="hard"), "难度")


def test_rejects_choice_with_fewer_than_two_options(client):
    assert_rejected(post(client, options=["NaCl"]), "至少要有 2 个选项")


def test_rejects_choice_with_blank_option(client):
    assert_rejected(post(client, options=["NaCl", "  "]), "选项不能为空")


def test_rejects_blank_question_with_options(client):
    assert_rejected(post(client, type="blank", options=["x", "y"], answer="NaCl"), "填空题不能有选项")


def test_rejects_answer_not_in_options(client):
    assert_rejected(post(client, answer="D"), "不在选项里")


def test_rejected_question_is_not_saved(client):
    post(client, stem="")
    assert client.get("/api/questions").json()["data"] == []


def test_malformed_json_body_gets_chinese_error_in_envelope(client):
    r = client.post("/api/questions", content=b"{not json", headers={"Content-Type": "application/json"})
    assert 400 <= r.status_code < 500
    body = r.json()
    assert body["success"] is False and body["data"] is None
    assert body["error"] == "请求格式不对"


def test_non_utf8_body_gets_chinese_error_in_envelope(client):
    r = client.post("/api/questions", content='{"stem":"题"}'.encode("gbk"), headers={"Content-Type": "application/json"})
    assert 400 <= r.status_code < 500
    body = r.json()
    assert body["success"] is False and body["data"] is None
    assert body["error"] == "请求格式不对"


# ---- 验收 2：数据来自数据库，直接改库后接口返回新值 ----

def test_list_reflects_direct_database_edit(client, database_url):
    qid = post(client).json()["data"]["id"]
    path = database_url.removeprefix("sqlite:///")
    conn = sqlite3.connect(path)
    with conn:
        conn.execute("UPDATE questions SET stem = ? WHERE id = ?", ("改过的题干", qid))
    conn.close()
    assert client.get("/api/questions").json()["data"][0]["stem"] == "改过的题干"


# ---- 验收 3、4：种子题、新建题经得起重启 ----

def start(database_url):
    return TestClient(create_app(database_url=database_url, seed=True))


SEED_STEMS = [
    "下列物质中属于电解质的是",
    "配平：Fe + O2 → Fe3O4",
    "关于氧化还原反应，下列说法正确的是",
]


def test_first_start_on_empty_database_inserts_three_seed_questions(database_url):
    with start(database_url) as c:
        data = c.get("/api/questions").json()["data"]
    assert [q["stem"] for q in data] == SEED_STEMS
    single, blank, multiple = data
    assert (single["type"], single["options"], single["answer"], single["difficulty"], single["status"]) == (
        "single", ["NaCl", "蔗糖", "CO2"], "A", 2, "approved")
    assert (blank["type"], blank["options"], blank["answer"], blank["difficulty"], blank["status"]) == (
        "blank", None, "3Fe + 2O2 → Fe3O4", 2, "draft")
    assert (multiple["type"], multiple["options"], multiple["answer"], multiple["difficulty"], multiple["status"]) == (
        "multiple", ["氧化剂得电子", "还原剂失电子", "化合价不变"], "AB", 3, "pending")
    assert all(q["explanation"] is None for q in data)


def test_restarting_twice_keeps_exactly_three_seed_questions(database_url):
    for _ in range(3):
        with start(database_url) as c:
            count = len(c.get("/api/questions").json()["data"])
    assert count == 3


def test_created_question_survives_two_restarts(database_url):
    with start(database_url) as c:
        post(c, stem="重启后还在吗")
    for _ in range(2):
        with start(database_url) as c:
            data = c.get("/api/questions").json()["data"]
    assert len(data) == 4
    assert data[0]["stem"] == "重启后还在吗"
