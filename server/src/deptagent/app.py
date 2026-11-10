"""FastAPI 应用工厂（SPEC 13.1：api / core / storage 三层组装）。

- /health 存活检查；
- 全部错误出口统一为 8.5 格式 {"error": {code, message, detail}}；
- 启动即执行迁移（lifespan），DB/Settings/登录限速器挂 app.state；
- console/dist 存在时挂为静态站点（T0.8，路由先注册、mount 最后兜底）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .api import accounts, auth, bind
from .config import Settings, load_settings
from .core.auth import LoginRateLimiter
from .core.bind import BindRateLimiter
from .core.errors import ApiError, error_response
from .storage.database import Database
from .storage.migrations import migrate

# 仓库内缺省位置：<repo>/console/dist（server/src/deptagent/app.py 向上三级）
_DEFAULT_CONSOLE_DIST = Path(__file__).resolve().parents[3] / "console" / "dist"

_HTTP_CODE_FALLBACK = {401: ("token_invalid", "未认证"), 403: ("forbidden_role", "无权限")}


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database.open(s.db_path)
        migrate(db)  # 幂等：每次启动应用未执行的迁移
        app.state.db = db
        app.state.settings = s
        app.state.login_limiter = LoginRateLimiter(
            max_failures=s.login_max_failures,
            lock_seconds=s.login_lock_minutes * 60,
        )
        app.state.bind_limiter = BindRateLimiter(
            max_requests=s.bind_rate_limit_per_minute,
        )
        yield
        db.close()

    app = FastAPI(title="DeptAgent Server", version=__version__, lifespan=lifespan)

    # ---- 统一错误出口（SPEC 8.5）----

    @app.exception_handler(ApiError)
    async def on_api_error(_: Request, exc: ApiError):
        return error_response(exc)

    @app.exception_handler(RequestValidationError)
    async def on_validation_error(_: Request, exc: RequestValidationError):
        return error_response(
            ApiError(422, "validation_error", "请求参数不合法", jsonable_encoder(exc.errors()))
        )

    @app.exception_handler(StarletteHTTPException)
    async def on_http_exception(_: Request, exc: StarletteHTTPException):
        code, message = _HTTP_CODE_FALLBACK.get(exc.status_code, ("error", str(exc.detail)))
        return error_response(ApiError(exc.status_code, code, message))

    # ---- 路由 ----

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    app.include_router(auth.router)
    app.include_router(accounts.router)
    app.include_router(bind.router)

    # ---- 管理控制台静态站点（T0.8：构建产物存在才挂载）----

    dist = Path(s.console_dist) if s.console_dist else _DEFAULT_CONSOLE_DIST
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="console")

    return app
