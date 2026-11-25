"""测试夹具：每个测试一份独立的临时库，结构用迁移建，永远不碰开发库 chemai.db。"""
import os

# 测试用固定密钥，避免在仓库里生成 .jwt-secret；生产缺密钥的行为单独测。
os.environ.setdefault("CHEMAI_JWT_SECRET", "chemai-test-secret")
os.environ.setdefault("CHEMAI_ENV", "dev")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import hash_password
from app.config import DEFAULT_DATABASE_PATH
from app.db import make_engine, make_session_factory
from app.main import create_app
from app.migrations import upgrade_to_head
from app.models import Class, User


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


@pytest.fixture
def make_user(database_url):
    """在临时库里建账号，返回 (username, password)。密码默认 chem2026。"""
    def _make(username, role="teacher", name=None, class_id=None, password="chem2026"):
        engine = make_engine(database_url)
        factory = make_session_factory(engine)
        with factory() as session:
            session.add(
                User(
                    username=username,
                    name=name or username,
                    role=role,
                    class_id=class_id,
                    password_hash=hash_password(password),
                )
            )
            session.commit()
        engine.dispose()
        return username, password

    return _make


@pytest.fixture
def make_class(database_url):
    """在临时库里建班级，teacher_username 必须是已建好的老师。返回班级 id。"""
    def _make(name, teacher_username):
        engine = make_engine(database_url)
        factory = make_session_factory(engine)
        with factory() as session:
            teacher = session.scalar(select(User).where(User.username == teacher_username))
            assert teacher is not None, f"老师 {teacher_username} 不存在，先 make_user"
            klass = Class(name=name, teacher_id=teacher.id)
            session.add(klass)
            session.commit()
            class_id = klass.id
        engine.dispose()
        return class_id

    return _make
