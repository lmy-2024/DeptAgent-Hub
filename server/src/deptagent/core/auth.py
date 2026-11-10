"""管理端登录（SPEC 8.3 管理端 REST / 8.5 auth_failed / 12 章失败锁定）。

失败锁定为进程内存实现：5 次失败锁 15 分钟（参数见 config.Settings）。
阶段 0 取舍：部署形态为单进程（SPEC 9.1），服务重启即解锁——不阻塞
super 重置密码的 break-glass 路径（SPEC 8.3）；阶段 2 如需跨重启持久再入库。
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

from ..storage.database import Database
from .errors import ApiError
from .security import verify_password


@dataclass(frozen=True)
class LoginUser:
    user_id: int
    employee_no: str
    name: str
    display_name: str | None
    role: str
    team: str | None


class LoginRateLimiter:
    """登录失败锁定（SPEC 12 章：密码策略 + 失败锁定）。"""

    def __init__(self, max_failures: int = 5, lock_seconds: int = 15 * 60) -> None:
        self._max_failures = max_failures
        self._lock_seconds = lock_seconds
        self._failures: dict[str, int] = {}
        self._locked_until: dict[str, float] = {}

    def remaining_lock(self, key: str) -> float:
        """锁定中返回剩余秒数（>0），未锁定返回 0；到期自动清除。"""
        until = self._locked_until.get(key)
        if until is None:
            return 0.0
        remaining = until - time.monotonic()
        if remaining <= 0:
            self._locked_until.pop(key, None)
            self._failures.pop(key, None)
            return 0.0
        return remaining

    def record_failure(self, key: str) -> None:
        count = self._failures.get(key, 0) + 1
        self._failures[key] = count
        if count >= self._max_failures:
            self._locked_until[key] = time.monotonic() + self._lock_seconds

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)
        self._locked_until.pop(key, None)


def _to_login_user(row: sqlite3.Row) -> LoginUser:
    return LoginUser(
        user_id=row["id"],
        employee_no=row["employee_no"],
        name=row["name"],
        display_name=row["display_name"],
        role=row["role"],
        team=row["team"],
    )


def authenticate(
    db: Database, limiter: LoginRateLimiter, employee_no: str, password: str
) -> LoginUser:
    """校验工号 + 密码；失败统一 401 auth_failed（不区分"工号不存在/密码错/已停用"）。"""
    remaining = limiter.remaining_lock(employee_no)
    if remaining > 0:
        raise ApiError(
            401,
            "auth_failed",
            "失败次数过多，账号已临时锁定，请稍后再试",
            {"retry_after_seconds": int(remaining) + 1},
        )

    row = db.query_one("SELECT * FROM users WHERE employee_no = ?", (employee_no,))
    ok = (
        row is not None
        and row["status"] == "active"
        and verify_password(row["password_hash"], password)
    )
    if not ok:
        limiter.record_failure(employee_no)
        raise ApiError(401, "auth_failed", "工号或密码不正确")
    limiter.reset(employee_no)
    assert row is not None  # ok 为 True 时 row 必非空（类型收窄）
    return _to_login_user(row)
