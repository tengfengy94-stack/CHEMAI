"""后端入口：uvicorn app.main:app（在 backend/ 下）。

create_app 接受数据库地址，测试用它换成临时库；开发时用项目根目录的 chemai.db。
表结构只由 Alembic 迁移建，这里不 create_all。
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import config
from app.auth import AccessDeniedError, AuthRequiredError
from app.db import make_engine, make_session_factory
from app.envelope import fail
from app.routes import router
from app.schemas import FIELD_LABELS
from app.seed import seed_if_empty


def create_app(database_url: str | None = None, seed: bool = True) -> FastAPI:
    engine = make_engine(database_url or config.database_url())
    session_factory = make_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if seed:
            with session_factory() as session:
                seed_if_empty(session)
        yield
        engine.dispose()

    app = FastAPI(title="ChemAI", lifespan=lifespan)
    app.state.session_factory = session_factory

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 框架自带的英文报错一律换成中文，不透出原文
    http_messages = {
        400: "请求格式不对",  # 请求体解析不了（不是 UTF-8、JSON 坏了等）
        404: "接口不存在",
        405: "不支持这种请求方式",
    }

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_req: Request, exc: StarletteHTTPException):
        return fail(http_messages.get(exc.status_code, "请求出错了，请稍后重试"), exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_req: Request, exc: RequestValidationError):
        first = exc.errors()[0]
        loc = [p for p in first.get("loc", ()) if p != "body"]
        field = loc[0] if loc else None
        if field in FIELD_LABELS:
            label = FIELD_LABELS[field]
            message = f"缺少{label}" if first.get("type") == "missing" else f"{label}格式不对"
        else:
            message = "请求格式不对"
        return fail(message, 422)

    @app.exception_handler(AuthRequiredError)
    async def auth_required(_req: Request, exc: AuthRequiredError):
        return fail(str(exc), 401)

    @app.exception_handler(AccessDeniedError)
    async def access_denied(_req: Request, exc: AccessDeniedError):
        return fail(str(exc), 403)

    @app.exception_handler(Exception)
    async def unexpected_error(_req: Request, _exc: Exception):
        return fail("服务器出错了，请稍后重试", 500)

    app.include_router(router)
    return app


app = create_app()
