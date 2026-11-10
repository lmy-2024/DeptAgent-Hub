"""密码哈希与 JWT（SPEC 10.1：Argon2id；JWT HS256、12h、无 refresh）。"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error

ALGORITHM = "HS256"
TOKEN_TTL_HOURS = 12

# argon2-cffi 缺省算法即 Argon2id（SPEC 10.1 / 决策点 D11 倾向值）
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """校验密码；哈希损坏等异常一律按不匹配处理（登录路径不向上抛异常）。"""
    try:
        return _hasher.verify(password_hash, password)
    except Argon2Error:
        return False


def generate_password() -> str:
    """生成随机初始/重置密码（明文仅返回一次，与设备令牌同风格，SPEC 10.1）。"""
    return secrets.token_urlsafe(12)


def create_access_token(
    secret: str, employee_no: str, ttl_hours: int = TOKEN_TTL_HOURS
) -> tuple[str, str]:
    """签发管理端 JWT；返回 (token, expires_at ISO 8601)。

    token 仅携带 sub=employee_no——角色与状态每次请求查库取最新值
    （SPEC 1.3"改角色即改权限"要求角色调整即时生效，故不把 role 固化进 token）。
    """
    now = datetime.now(UTC)
    expires_at = now + timedelta(hours=ttl_hours)
    payload: dict[str, Any] = {"sub": employee_no, "iat": now, "exp": expires_at}
    token = jwt.encode(payload, secret, algorithm=ALGORITHM)
    return token, expires_at.isoformat(timespec="seconds")


def decode_access_token(secret: str, token: str) -> dict[str, Any]:
    """校验并解码；签名错误/过期抛 jwt.InvalidTokenError（含子类）。"""
    return jwt.decode(token, secret, algorithms=[ALGORITHM])
