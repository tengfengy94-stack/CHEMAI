"""知识点模糊匹配：名称、别名、无匹配与多候选。"""
from app import knowledge
from app.db import make_engine, make_session_factory
from helpers import auth, login


def _point(client, token, name, parent_id=None, aliases=None):
    r = client.post(
        "/api/knowledge-points",
        headers=auth(token),
        json={"name": name, "parent_id": parent_id, "aliases": aliases or []},
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


def test_find_point_name_alias_and_no_match(client, database_url, make_user):
    make_user("t1", role="teacher")
    token = login(client, "t1")
    root = _point(client, token, "氧化还原", aliases=["redox"])
    _point(client, token, "氧化剂", parent_id=root["id"])

    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    try:
        with factory() as session:
            by_name = knowledge.find_point(session, "氧化还原")
            assert by_name["name"] == "氧化还原"

            by_alias = knowledge.find_point(session, "redox")
            assert by_alias["name"] == "氧化还原"

            child = knowledge.find_point(session, "氧化剂")
            assert child["name"] == "氧化剂"
            assert child["parent_id"] == root["id"]

            assert knowledge.find_point(session, "库里没有这个点") is None
            assert knowledge.find_point(session, "  ") is None
    finally:
        engine.dispose()


def test_find_point_prefers_exact_over_contains(client, database_url, make_user):
    make_user("t1", role="teacher")
    token = login(client, "t1")
    _point(client, token, "氧化还原反应")
    exact = _point(client, token, "氧化还原")

    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    try:
        with factory() as session:
            found = knowledge.find_point(session, "氧化还原")
            assert found["id"] == exact["id"]
    finally:
        engine.dispose()
