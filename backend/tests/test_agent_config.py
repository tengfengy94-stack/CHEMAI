"""模型配置四分支：显式假模型、无密钥回退、真模型、配置不完整。"""
import pytest

from app import config

ENV_NAMES = (
    "CHEMAI_FAKE_MODEL",
    "CHEMAI_MODEL_API_KEY",
    "CHEMAI_MODEL_BASE_URL",
    "CHEMAI_MODEL_NAME",
)


@pytest.fixture
def clean_model_env(monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    yield monkeypatch
    # monkeypatch 自动还原，这里只提供清晰的名字


def test_explicit_fake_wins_over_complete_real_config(clean_model_env):
    clean_model_env.setenv("CHEMAI_FAKE_MODEL", "1")
    clean_model_env.setenv("CHEMAI_MODEL_API_KEY", "key")
    clean_model_env.setenv("CHEMAI_MODEL_BASE_URL", "https://example.test/v1")
    clean_model_env.setenv("CHEMAI_MODEL_NAME", "model-x")

    assert config.fake_model_enabled() is True
    assert config.should_use_fake_model() is True


def test_no_key_falls_back_to_fake(clean_model_env):
    clean_model_env.setenv("CHEMAI_FAKE_MODEL", "0")
    clean_model_env.setenv("CHEMAI_MODEL_BASE_URL", "https://example.test/v1")
    clean_model_env.setenv("CHEMAI_MODEL_NAME", "model-x")

    assert config.fake_model_enabled() is False
    assert config.should_use_fake_model() is True


def test_complete_config_uses_real_model(clean_model_env):
    clean_model_env.setenv("CHEMAI_FAKE_MODEL", "0")
    clean_model_env.setenv("CHEMAI_MODEL_API_KEY", "key")
    clean_model_env.setenv("CHEMAI_MODEL_BASE_URL", "https://example.test/v1")
    clean_model_env.setenv("CHEMAI_MODEL_NAME", "model-x")

    assert config.should_use_fake_model() is False
    cfg = config.model_config()
    assert cfg == config.ModelConfig(
        base_url="https://example.test/v1",
        api_key="key",
        model_name="model-x",
    )


def test_key_without_address_or_model_reports_incomplete(clean_model_env):
    clean_model_env.setenv("CHEMAI_FAKE_MODEL", "0")
    clean_model_env.setenv("CHEMAI_MODEL_API_KEY", "key")

    assert config.should_use_fake_model() is False
    with pytest.raises(config.ModelConfigError) as exc:
        config.model_config()
    message = str(exc.value)
    assert "CHEMAI_MODEL_BASE_URL" in message
    assert "CHEMAI_MODEL_NAME" in message
