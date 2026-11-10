"""设备绑定（SPEC 3.5 / 8.2 / 10.1）。

邀请码校验（未用 + 未过期，一次性）→ 创建或复用员工（closed 模式 D7
自动激活，role/team 来自邀请码）→ 签发设备令牌：`token_urlsafe(32)`，
库内仅存 SHA-256（devices.token_hash UNIQUE），明文仅绑定响应返回一次。

限速：IP 维度 10 次/分钟（8.2/10.1，防邀请码枚举）——成功与失败都
计数；进程内存实现（阶段取舍同 core.auth：单进程部署形态，重启即清零）。
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from ..core.utc import utc_now_iso
from ..storage.database import Database
from .errors import ApiError
from .security import hash_password

# 拍板 D2（2026-11-10）：用量 / 台账 / 心跳 = 5 / 15 / 5 min（下发客户端可覆盖本地默认）
SERVER_REPORT_INTERVALS_SEC = {"usage": 300, "agents": 900, "heartbeat": 300}


@dataclass(frozen=True)
class BindInput:
    invite_code: str
    employee_no: str
    name: str | None = None  # 缺省 = 工号（SPEC 8.2 v0.7）
    password: str | None = None
    device_name: str | None = None
    os: str | None = None
    client_version: str | None = None


@dataclass(frozen=True)
class BindResult:
    device_token: str
    server_config: dict


class BindRateLimiter:
    """绑定请求 IP 滑动窗口限速（SPEC 8.2：10 次/分钟）。"""

    def __init__(self, max_requests: int = 10, window_seconds: int = 60) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> float:
        """超限返回需等待秒数（>0，本次不受理不计数）；未超限记录并返回 0。"""
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] >= self._window:
            hits.popleft()
        if len(hits) >= self._max:
            return self._window - (now - hits[0])
        hits.append(now)
        return 0.0


def issue_device_token() -> str:
    """设备令牌（SPEC 10.1）：43 字符 URL-safe，明文仅绑定响应返回一次。"""
    return secrets.token_urlsafe(32)


def token_sha256(token: str) -> str:
    """库内存储形态：SHA-256 hex（devices.token_hash，UNIQUE 支撑令牌反查设备）。"""
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _unusable_password_hash() -> str:
    """未设密码账号的占位哈希：随机值无对应明文，任何登录尝试必然失败。"""
    return hash_password(secrets.token_urlsafe(16))


def bind_device(db: Database, body: BindInput) -> BindResult:
    """校验邀请码并完成绑定（一次性、一人多机、明文令牌仅返回一次）。"""
    invite = db.query_one(
        "SELECT * FROM invitations WHERE code = ?", (body.invite_code,)
    )
    if invite is None or invite["used_by"] is not None:
        raise ApiError(400, "invite_invalid", "邀请码无效或已被使用")
    if invite["expires_at"] is not None and invite["expires_at"] <= utc_now_iso():
        raise ApiError(400, "invite_expired", "邀请码已过期")

    user = db.query_one(
        "SELECT * FROM users WHERE employee_no = ?", (body.employee_no,)
    )
    if user is not None and user["status"] != "active":
        # 停用账号不可再绑新设备（5.2 离职停用语义）
        raise ApiError(400, "invite_invalid", "账号已停用，无法绑定")

    token = issue_device_token()
    now = utc_now_iso()
    with db.write_transaction() as conn:
        if user is None:
            # closed 模式（D7）自动激活；role/team 来自邀请码（5.2：admin+ 不经邀请码产生）
            password_hash = (
                hash_password(body.password)
                if body.password
                else _unusable_password_hash()
            )
            cursor = conn.execute(
                """
                INSERT INTO users
                    (employee_no, name, role, team, status, password_hash, created_at, invited_by)
                VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (
                    body.employee_no,
                    body.name or body.employee_no,
                    invite["role"] or "member",
                    invite["team"],
                    password_hash,
                    now,
                    invite["code"],
                ),
            )
            user_id = cursor.lastrowid
        else:
            # 已有员工绑新设备（一人多机）；传入密码忽略（初始密码仅创建时生效）
            user_id = user["id"]

        conn.execute(
            """
            INSERT INTO devices
                (user_id, device_name, os, client_version, status, token_hash, created_at)
            VALUES (?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                user_id,
                body.device_name,
                body.os,
                body.client_version,
                token_sha256(token),
                now,
            ),
        )
        # 一次性最终防线：并发抢用同一邀请码时 rowcount=0 → 回滚整包
        claimed = conn.execute(
            "UPDATE invitations SET used_by = ?, used_at = ? WHERE code = ? AND used_by IS NULL",
            (user_id, now, body.invite_code),
        )
        if claimed.rowcount != 1:
            raise ApiError(400, "invite_invalid", "邀请码已被使用")

    return BindResult(
        device_token=token,
        server_config={"report_intervals_sec": SERVER_REPORT_INTERVALS_SEC},
    )


def verify_device_token(db: Database, token: str) -> sqlite3.Row:
    """设备令牌 → devices 行（T1.4 上报鉴权复用）；吊销/无效统一 401 token_invalid。

    已吊销令牌的语义细分（token_revoked）由调用方按 devices.status 判定。
    """
    row = db.query_one(
        "SELECT * FROM devices WHERE token_hash = ?", (token_sha256(token),)
    )
    if row is None or row["status"] != "active":
        raise ApiError(401, "token_invalid", "设备令牌无效或已吊销")
    return row
