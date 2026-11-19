"""在代码里执行 Alembic 迁移，供测试夹具用。

dev.sh 走的是命令行等价写法（在 backend/ 下）：../.venv/Scripts/python.exe -m alembic upgrade head
"""
from alembic import command
from alembic.config import Config

from app.config import BACKEND_DIR


def alembic_config(database_url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def upgrade_to_head(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "head")
