"""公共依赖：DB、当前用户、super 门槛。

关键设计（SPEC 1.3"改角色即改权限"）：JWT 仅携带 sub=employee_no，
角色与状态每次请求查库取最新值——角色调整/停用对已签发 token 即时生效，
这是 14.1 第 8 条"角色调整即时生效/旧密码立即失效"验收的实现基础。
"""

from __future__ import annotations

import sqlite3
from typing import Annotated

import jwt
from fastapi import Depends, Request

from ..core.errors import ApiError
from ..core.security import decode_access_token
from ..storage.database import Database


def get_db(request: Request) -> Database:
    return request.app.state.db


DbDep = Annotated[Database, Depends(get_db)]


def get_current_user(request: Request, db: DbDep) -> sqlite3.Row:
    """解析 Authorization: Bearer <JWT> → 校验并加载当前用户（状态实时）。"""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise ApiError(401, "token_invalid", "缺少访问令牌")
    token = auth.removeprefix("Bearer ").strip()
    settings = request.app.state.settings
    try:
        payload = decode_access_token(settings.jwt_secret, token)
    except jwt.InvalidTokenError:
        raise ApiError(401, "token_invalid", "访问令牌无效或已过期") from None

    employee_no = payload.get("sub")
    user = (
        db.query_one("SELECT * FROM users WHERE employee_no = ?", (employee_no,))
        if isinstance(employee_no, str)
        else None
    )
    if user is None or user["status"] != "active":
        # 账号已停用/删除：token 即时失效（与 8.3 disable 语义闭环）
        raise ApiError(401, "token_invalid", "账号不存在或已停用")
    return user


CurrentUser = Annotated[sqlite3.Row, Depends(get_current_user)]


def require_super(user: CurrentUser) -> sqlite3.Row:
    """super 门槛（SPEC 8.3：账号治理端点逐端点强制）。"""
    if user["role"] != "super":
        raise ApiError(403, "forbidden_role", "仅超级管理员可执行账号治理")
    return user


SuperUser = Annotated[sqlite3.Row, Depends(require_super)]
