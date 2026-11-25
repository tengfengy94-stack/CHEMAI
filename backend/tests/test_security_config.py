"""密钥与演示账号的环境闸：生产缺密钥失败，开发自动生成。"""
import pytest

from app import auth, config
from app.main import create_app


def test_prod_without_jwt_secret_fails(monkeypatch):
    monkeypatch.delenv("CHEMAI_JWT_SECRET", raising=False)
    monkeypatch.setenv("CHEMAI_ENV", "prod")
    with pytest.raises(RuntimeError):
        auth.jwt_secret()
    with pytest.raises(RuntimeError):
        create_app(database_url="sqlite://")


def test_dev_generates_and_persists_local_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("CHEMAI_ENV", "dev")
    monkeypatch.delenv("CHEMAI_JWT_SECRET", raising=False)
    secret_file = tmp_path / ".jwt-secret"
    monkeypatch.setattr(auth, "_DEV_SECRET_FILE", secret_file)
    monkeypatch.setattr(auth, "_dev_secret", None)

    secret = auth.jwt_secret()

    assert len(secret) >= 32
    assert secret_file.read_text(encoding="utf-8").strip() == secret
    # 第二次读取同一文件，不重新生成
    monkeypatch.setattr(auth, "_dev_secret", None)
    assert auth.jwt_secret() == secret


def test_seed_demo_is_off_in_prod_unless_explicit(monkeypatch):
    monkeypatch.delenv("CHEMAI_SEED_DEMO", raising=False)
    monkeypatch.setenv("CHEMAI_ENV", "prod")
    assert config.seed_demo_enabled() is False

    monkeypatch.setenv("CHEMAI_SEED_DEMO", "1")
    assert config.seed_demo_enabled() is True

    monkeypatch.setenv("CHEMAI_ENV", "dev")
    monkeypatch.setenv("CHEMAI_SEED_DEMO", "0")
    assert config.seed_demo_enabled() is False
