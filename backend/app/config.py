"""路径与配置。数据库路径按代码所在位置算，不依赖从哪个目录启动。

模型配置从环境变量读；开发时 backend/.env 由 python-dotenv 加载，已有环境变量优先。
"""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "chemai.db"

load_dotenv(BACKEND_DIR / ".env")


def database_url() -> str:
    """开发库地址；设置环境变量 CHEMAI_DATABASE_URL 可覆盖。"""
    return os.environ.get("CHEMAI_DATABASE_URL") or f"sqlite:///{DEFAULT_DATABASE_PATH.as_posix()}"


class ModelConfigError(Exception):
    """真模型配置不完整；这条消息会原样回给前端，不抛原始堆栈。"""


@dataclass(frozen=True)
class ModelConfig:
    base_url: str
    api_key: str
    model_name: str


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def is_prod() -> bool:
    """生产环境开关：CHEMAI_ENV=prod；默认按本地开发处理。"""
    return _env("CHEMAI_ENV").lower() in {"prod", "production"}


def seed_demo_enabled() -> bool:
    """演示账号只在开发环境默认插入；生产必须显式打开。"""
    if _env("CHEMAI_SEED_DEMO").lower() in {"1", "true", "yes", "on"}:
        return True
    if _env("CHEMAI_SEED_DEMO").lower() in {"0", "false", "no", "off"}:
        return False
    return not is_prod()


def fake_model_enabled() -> bool:
    """显式假模型开关：1/true/yes/on 都算开启。"""
    return _env("CHEMAI_FAKE_MODEL").lower() in {"1", "true", "yes", "on"}


def eval_mode() -> bool:
    """评测模式开关：只在评测脚本启动的服务里打开，生产默认关闭。"""
    return _env("CHEMAI_EVAL_MODE").lower() in {"1", "true", "yes", "on"}


def should_use_fake_model() -> bool:
    """显式开关优先；没有真模型密钥时自动回退到假模型。"""
    return fake_model_enabled() or not _env("CHEMAI_MODEL_API_KEY")


def model_config() -> ModelConfig:
    """读取真模型配置；有密钥但缺地址或模型名时报配置错误，不静默降级。"""
    base_url = _env("CHEMAI_MODEL_BASE_URL")
    api_key = _env("CHEMAI_MODEL_API_KEY")
    model_name = _env("CHEMAI_MODEL_NAME")
    missing = [
        label
        for label, value in (
            ("CHEMAI_MODEL_BASE_URL", base_url),
            ("CHEMAI_MODEL_API_KEY", api_key),
            ("CHEMAI_MODEL_NAME", model_name),
        )
        if not value
    ]
    if missing:
        raise ModelConfigError(f"模型配置不完整：缺少 {'、'.join(missing)}")
    return ModelConfig(base_url=base_url, api_key=api_key, model_name=model_name)


# 前端开发服务器默认走 Vite 代理，同源不需要跨域；这里留作直连时的兜底
CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
