"""测试夹具：每个测试一份独立的临时库，结构用迁移建，永远不碰开发库 chemai.db。"""
import pytest
from fastapi.testclient import TestClient

from app.config import DEFAULT_DATABASE_PATH
from app.main import create_app
from app.migrations import upgrade_to_head


@pytest.fixture
def database_url(tmp_path):
    path = tmp_path / "test.db"
    assert path.resolve() != DEFAULT_DATABASE_PATH.resolve()
    url = f"sqlite:///{path.as_posix()}"
    upgrade_to_head(url)
    return url


@pytest.fixture
def client(database_url):
    """不插种子题的应用：测试结果只取决于测试自己建的数据。"""
    app = create_app(database_url=database_url, seed=False)
    with TestClient(app) as c:
        yield c
