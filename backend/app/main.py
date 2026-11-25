"""后端入口：uvicorn app.main:app（在 backend/ 下）。

create_app 接受数据库地址，测试用它换成临时库；开发时用项目根目录的 chemai.db。
表结构只由 Alembic 迁移建，这里不 create_all。
"""
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy.engine import make_url
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import config, review  # review 导入即注册判分事件订阅
from app.agent import build_chat_model
from app.agent_routes import router as agent_router
from app.agent_runtime import build_agents
from app.auth import AccessDeniedError, AuthRequiredError, jwt_secret
from app.class_reporting import ClassExamNotFound
from app.config import ModelConfigError
from app.db import make_engine, make_session_factory
from app.envelope import fail
from app.eval_routes import router as eval_router
from app.eval_trace import EvalTraceStore
from app.knowledge import KnowledgePointNotFound
from app.knowledge_routes import router as knowledge_router
from app.practice_routes import router as practice_router
from app.reporting_routes import router as reporting_router
from app.review import ReviewTaskNotFound
from app.review_routes import router as review_router
from app.routes import (
    AttemptNotFound,
    ClassNotFound,
    PaperNotFound,
    QuestionNotFound,
    router as exam_router,
)
from app.schemas import FIELD_LABELS
from app.seed import seed_if_empty

logger = logging.getLogger("chemai")


def _checkpoint_path(database_url: str) -> str | None:
    """SQLite 文件库返回路径；内存库交给 InMemorySaver。"""
    url = make_url(database_url)
    if url.drivername.startswith("sqlite") and url.database and url.database != ":memory:":
        return url.database
    return None


def create_app(
    database_url: str | None = None,
    seed: bool = True,
    eval_mode: bool | None = None,
) -> FastAPI:
    # 生产环境缺少 JWT 密钥时在启动阶段失败，不要等到第一次登录。
    jwt_secret()
    url = database_url or config.database_url()
    engine = make_engine(url)
    session_factory = make_session_factory(engine)
    checkpoint_path = _checkpoint_path(url)
    eval_enabled = config.eval_mode() if eval_mode is None else eval_mode

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if seed and config.seed_demo_enabled():
            with session_factory() as session:
                seed_if_empty(session)

        app.state.agents = None
        app.state.use_agent_graph = True
        app.state.agent_error = None
        try:
            model = build_chat_model()
        except ModelConfigError as exc:
            # 配置不完整时保留第 11 章的每轮 500 信封行为，不让应用起不来。
            app.state.agent_error = exc
            logger.error("模型配置错误：%s", exc)
            yield
            engine.dispose()
            return

        if checkpoint_path:
            async with AsyncSqliteSaver.from_conn_string(checkpoint_path) as saver:
                app.state.agents = build_agents(model, saver)
                yield
        else:
            app.state.agents = build_agents(model, InMemorySaver())
            yield
        engine.dispose()

    app = FastAPI(title="ChemAI", lifespan=lifespan)
    app.state.session_factory = session_factory
    app.state.eval_mode = eval_enabled
    app.state.eval_trace = EvalTraceStore() if eval_enabled else None
    # 测试可以换成返回失败/记录型模型的工厂
    app.state.chat_model_factory = build_chat_model

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
        # 嵌套字段（如 answers[0].question_id）取最深的已知字段名，提示才具体
        fields = [p for p in loc if isinstance(p, str)]
        field = next(
            (name for name in reversed(fields) if name in FIELD_LABELS),
            fields[-1] if fields else None,
        )
        if field in FIELD_LABELS:
            label = FIELD_LABELS[field]
            message = f"缺少{label}" if first.get("type") == "missing" else f"{label}格式不对"
        else:
            message = "请求格式不对"
        return fail(message, 422)

    @app.exception_handler(QuestionNotFound)
    async def question_not_found(_req: Request, _exc: QuestionNotFound):
        return fail("题目不存在", 404)

    @app.exception_handler(PaperNotFound)
    async def paper_not_found(_req: Request, _exc: PaperNotFound):
        return fail("卷子不存在", 404)

    @app.exception_handler(AttemptNotFound)
    async def attempt_not_found(_req: Request, _exc: AttemptNotFound):
        return fail("作答记录不存在", 404)

    @app.exception_handler(ClassNotFound)
    async def class_not_found(_req: Request, _exc: ClassNotFound):
        return fail("班级不存在", 404)

    @app.exception_handler(ClassExamNotFound)
    async def class_exam_not_found(_req: Request, _exc: ClassExamNotFound):
        return fail("这次考试不存在", 404)

    @app.exception_handler(ReviewTaskNotFound)
    async def review_task_not_found(_req: Request, _exc: ReviewTaskNotFound):
        return fail("复习任务不存在", 404)

    @app.exception_handler(KnowledgePointNotFound)
    async def knowledge_point_not_found(_req: Request, _exc: KnowledgePointNotFound):
        return fail("知识点不存在", 404)

    @app.exception_handler(AuthRequiredError)
    async def auth_required(_req: Request, exc: AuthRequiredError):
        return fail(str(exc), 401)

    @app.exception_handler(AccessDeniedError)
    async def access_denied(_req: Request, exc: AccessDeniedError):
        return fail(str(exc), 403)

    @app.exception_handler(Exception)
    async def unexpected_error(_req: Request, _exc: Exception):
        return fail("服务器出错了，请稍后重试", 500)

    app.include_router(exam_router)
    app.include_router(review_router)
    app.include_router(knowledge_router)
    app.include_router(reporting_router)
    app.include_router(practice_router)
    app.include_router(agent_router)
    if eval_enabled:
        app.include_router(eval_router)
    return app


app = create_app()
