"""Alembic 运行入口。数据库地址优先用调用方传入的，否则用项目根目录的 chemai.db。"""
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import pool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config as app_config  # noqa: E402
from app.db import make_engine  # noqa: E402
from app.models import Base  # noqa: E402

config = context.config
target_metadata = Base.metadata

# LangGraph checkpointer 自己管理这两张表；Alembic 不能把它们当“业务表被删除”。
CHECKPOINTER_TABLES = {"checkpoints", "writes"}


def _include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table" and name in CHECKPOINTER_TABLES:
        return False
    return True


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or app_config.database_url()


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(_url())
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,
                include_object=_include_object,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
