"""管理端登录端点（SPEC 8.3 仿 Hub control_app 风格 / 8.5 错误格式）。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..core.auth import LoginRateLimiter, authenticate
from ..core.security import create_access_token
from .deps import DbDep

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    employee_no: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class LoginResponse(BaseModel):
    token: str
    expires_at: str  # UTC ISO 8601（SPEC 8.5 时间口径）
    role: str
    display_name: str | None = None


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, db: DbDep) -> LoginResponse:
    settings = request.app.state.settings
    limiter: LoginRateLimiter = request.app.state.login_limiter
    user = authenticate(db, limiter, body.employee_no, body.password)
    token, expires_at = create_access_token(
        settings.jwt_secret, user.employee_no, settings.jwt_ttl_hours
    )
    return LoginResponse(
        token=token, expires_at=expires_at, role=user.role, display_name=user.display_name
    )
