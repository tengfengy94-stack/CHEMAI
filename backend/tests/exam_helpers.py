"""考试接口测试共用的小工具：建题、审题、建卷、加题、发布。"""
from helpers import auth

QUESTION = {
    "stem": "下列物质中属于电解质的是",
    "type": "single",
    "options": ["NaCl", "蔗糖", "CO2"],
    "answer": "A",
    "explanation": "电解质在水里能电离",
    "difficulty": 2,
}

MULTIPLE_QUESTION = {
    "stem": "关于氧化还原反应，下列说法正确的是",
    "type": "multiple",
    "options": ["氧化剂得电子", "还原剂失电子", "化合价不变"],
    "answer": "AC",
    "explanation": None,
    "difficulty": 2,
}

BLANK_QUESTION = {
    "stem": "氯化钠的化学式",
    "type": "blank",
    "options": None,
    "answer": "NaCl",
    "explanation": None,
    "difficulty": 1,
}


def create_question(client, token, **changes):
    r = client.post("/api/questions", headers=auth(token), json={**QUESTION, **changes})
    assert r.status_code == 201, r.text
    return r.json()["data"]


def approve_question(client, token, question_id):
    r = client.post(
        f"/api/questions/{question_id}/status",
        headers=auth(token),
        json={"status": "approved"},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


def create_paper(client, token, title="周五周测"):
    r = client.post("/api/papers", headers=auth(token), json={"title": title})
    assert r.status_code == 201, r.text
    return r.json()["data"]


def add_question(client, token, paper_id, question_id):
    return client.post(
        f"/api/papers/{paper_id}/questions",
        headers=auth(token),
        json={"question_id": question_id},
    )


def publish(client, token, paper_id, class_id):
    return client.post(
        f"/api/papers/{paper_id}/publish",
        headers=auth(token),
        json={"class_id": class_id},
    )


def make_approved(client, token, **changes):
    question = create_question(client, token, **changes)
    approve_question(client, token, question["id"])
    return question


def paper_with(client, token, class_id, questions, title):
    """建卷、按顺序加题、发布给班级，返回卷子。"""
    paper = create_paper(client, token, title)
    for question in questions:
        r = add_question(client, token, paper["id"], question["id"])
        assert r.status_code == 200, r.text
    r = publish(client, token, paper["id"], class_id)
    assert r.status_code == 200, r.text
    return paper


def attempt_for_paper(client, token, paper_id):
    items = client.get("/api/attempts", headers=auth(token)).json()["data"]["items"]
    return next(item for item in items if item["paper_id"] == paper_id)


def submit_answers(client, token, attempt, answers):
    """开始并按 {question_id: answer} 交卷，返回判分后的作答记录。"""
    started = client.post(f"/api/attempts/{attempt['id']}/start", headers=auth(token))
    assert started.status_code == 200, started.text
    payload = [{"question_id": qid, "answer": text} for qid, text in answers.items()]
    result = client.post(
        f"/api/attempts/{attempt['id']}/submit",
        headers=auth(token),
        json={"answers": payload},
    )
    assert result.status_code == 200, result.text
    return result.json()["data"]


def wrong_questions(client, token):
    r = client.get("/api/wrong-questions", headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()["data"]["items"]
