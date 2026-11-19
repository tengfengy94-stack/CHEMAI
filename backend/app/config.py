"""路径与配置。数据库路径按代码所在位置算，不依赖从哪个目录启动。"""
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "chemai.db"


def database_url() -> str:
    """开发库地址；设置环境变量 CHEMAI_DATABASE_URL 可覆盖。"""
    return os.environ.get("CHEMAI_DATABASE_URL") or f"sqlite:///{DEFAULT_DATABASE_PATH.as_posix()}"


# 前端开发服务器默认走 Vite 代理，同源不需要跨域；这里留作直连时的兜底
CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

# 第 03 章接入登录前，建题的人先写死
PLACEHOLDER_CREATOR = "演示老师"
