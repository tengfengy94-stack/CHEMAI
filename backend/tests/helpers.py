"""测试共用的登录辅助。"""
from fastapi.testclient import TestClient

DEMO_PASSWORD = "chem2026"


def login(client: TestClient, username: str, password: str = DEMO_PASSWORD) -> str:
    """登录并返回 access token；登录失败直接让测试红掉。"""
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, f"登录失败：{r.status_code} {r.text}"
    return r.json()["data"]["access_token"]


def auth(token: str) -> dict:
    """带凭证的请求头。"""
    return {"Authorization": f"Bearer {token}"}
