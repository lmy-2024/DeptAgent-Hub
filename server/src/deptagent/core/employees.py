"""员工与设备管理服务（SPEC 4.2 / 5.2：T1.9）。

- 邀请码生成：DA-XXXXXXXX（8 位大写十六进制），可指定科室 /
  角色（仅 member / lead——admin 及以上不经邀请码产生，5.2）/
  有效期（缺省 72h）；生成与审计同事务（action=invitation.create）；
- 员工列表：users + devices 聚合（设备数 / 活跃设备数 / 最近心跳 /
  任一设备暂停）；在线灯 = 任一设备 15 分钟内有心跳
  （3 × 5min 心跳周期，D2 / 3.4）；
- 设备吊销：status → revoked（幂等），此后设备令牌上报即
  401 token_revoked（3.7 / 8.5 吊销链路），审计 action=device.revoke。
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from ..core.utc import utc_now_iso
from ..storage.database import Database
from .errors import ApiError

INVITE_ROLES = ("member", "lead")
DEFAULT_INVITE_HOURS = 72
MAX_INVITE_HOURS = 24 * 30
# 在线阈值：3 × 5min 心跳周期（D2 heartbeat=300s；3.4 台账在线状态推导）
ONLINE_WITHIN_SECONDS = 15 * 60

# 员工列表排序白名单（8.5：可排序字段由端点定义）
EMPLOYEE_SORTS = {
    "created_at": "u.created_at ASC, u.id ASC",
    "-created_at": "u.created_at DESC, u.id DESC",
    "employee_no": "u.employee_no ASC, u.id ASC",
    "-employee_no": "u.employee_no DESC, u.id DESC",
}

# 邀请码形态：DA- + 8 位大写十六进制（员工在插件端手工输入）
_INVITE_PREFIX = "DA-"
_INVITE_HEX_LEN = 8


def _audit(
    db: Database, actor_id: int, action: str, target: str, detail: dict[str, Any] | None = None
) -> None:
    """写审计行（SPEC 7 章 audit_log；同 core/accounts._audit 模式）。"""
    db.execute(
        "INSERT INTO audit_log (actor_id, action, target, detail, at) VALUES (?, ?, ?, ?, ?)",
        (
            actor_id,
            action,
            target,
            json.dumps(detail, ensure_ascii=False) if detail else None,
            utc_now_iso(),
        ),
    )


def is_online(last_heartbeat: str | None, *, now: datetime | None = None) -> bool:
    """在线判定：last_heartbeat 距今 ≤ 15 分钟（3 × 心跳周期）。

    时间口径：last_heartbeat 由服务端写入（10.1 UTC ISO 8601 秒级），
    解析失败 / 缺失视为离线（宽松容错，不抛错）。
    """
    if not last_heartbeat:
        return False
    try:
        hb = datetime.fromisoformat(last_heartbeat)
    except ValueError:
        return False
    if hb.tzinfo is None:  # 防御：naive 补 UTC（服务端写入总带 tz）
        hb = hb.replace(tzinfo=UTC)
    now = now or datetime.now(UTC)
    return (now - hb) <= timedelta(seconds=ONLINE_WITHIN_SECONDS)


def create_invitation(
    db: Database,
    *,
    actor: sqlite3.Row,
    team: str | None,
    role: str,
    expires_hours: int,
) -> dict:
    """生成邀请码（SPEC 5.2：科室 / 角色 / 有效期 / 一次性）。

    role 仅 member / lead；expires_hours 缺省 72、上限 30 天。
    返回邀请码行（code 明文入库——列表端点同样返回，admin JWT 保护）。
    """
    if role not in INVITE_ROLES:
        raise ApiError(
            422,
            "validation_error",
            "邀请码角色仅可为 member / lead（admin 及以上由 super 在账号管理页创建）",
            {"role": role},
        )
    if not 1 <= expires_hours <= MAX_INVITE_HOURS:
        raise ApiError(
            422,
            "validation_error",
            f"有效期须为 1–{MAX_INVITE_HOURS} 小时",
            {"expires_hours": expires_hours},
        )

    expires_at = (datetime.now(UTC) + timedelta(hours=expires_hours)).isoformat(timespec="seconds")

    code = ""
    with db.write_transaction() as conn:
        # PRIMARY KEY 碰撞重试（8 位十六进制碰撞概率 2^-32，兜底 5 次）
        for _ in range(5):
            candidate = _INVITE_PREFIX + secrets.token_hex(_INVITE_HEX_LEN // 2).upper()
            try:
                conn.execute(
                    "INSERT INTO invitations (code, team, role, expires_at) VALUES (?, ?, ?, ?)",
                    (candidate, team, role, expires_at),
                )
            except sqlite3.IntegrityError:
                continue
            code = candidate
            break
        if not code:
            raise ApiError(500, "error", "邀请码生成失败，请重试")
        conn.execute(
            "INSERT INTO audit_log (actor_id, action, target, detail, at) VALUES (?, ?, ?, ?, ?)",
            (
                actor["id"],
                "invitation.create",
                f"invitations/{code}",
                json.dumps({"team": team, "role": role, "expires_hours": expires_hours}),
                utc_now_iso(),
            ),
        )
    return {
        "code": code,
        "team": team,
        "role": role,
        "expires_at": expires_at,
        "used_by": None,
        "used_at": None,
    }


def list_invitations(db: Database) -> list[dict]:
    """邀请码全量列表（量小不分页；按过期时间倒序，未过期在前）。"""
    rows = db.query_all(
        "SELECT code, team, role, expires_at, used_by, used_at FROM invitations"
        " ORDER BY (used_by IS NOT NULL), expires_at DESC"
    )
    return [dict(row) for row in rows]


def list_employees(
    db: Database,
    *,
    page: int,
    page_size: int,
    sort: str,
    team: str | None,
    q: str | None,
) -> dict:
    """员工列表（SPEC 4.2：角色 / 科室 / 心跳灯 / 已暂停状态 + 设备聚合）。

      8.5 分页响应 {items, total, page, page_size}；q 匹配工号 / 姓名 /
    显示名（前缀 LIKE，无索引扫描可接受——部门规模 < 千人）。
    """
    if sort not in EMPLOYEE_SORTS:
        raise ApiError(
            422,
            "validation_error",
            "不支持的排序字段",
            {"sort": sort, "allowed": sorted(EMPLOYEE_SORTS)},
        )

    where: list[str] = []
    params: list[object] = []
    if team:
        where.append("u.team = ?")
        params.append(team)
    if q:
        where.append(
            "(u.employee_no LIKE ? OR u.name LIKE ? OR COALESCE(u.display_name, '') LIKE ?)"
        )
        like = f"%{q}%"
        params.extend([like, like, like])
    cond = f"WHERE {' AND '.join(where)}" if where else ""

    total = db.query_one(f"SELECT COUNT(*) AS n FROM users u {cond}", params)["n"]
    rows = db.query_all(
        f"""
        SELECT u.id, u.employee_no, u.name, u.display_name, u.role, u.team,
               u.status, u.created_at,
               COUNT(d.id) AS device_count,
               COALESCE(SUM(CASE WHEN d.status = 'active' THEN 1 ELSE 0 END), 0)
                   AS device_active_count,
               MAX(d.last_heartbeat) AS last_heartbeat,
               COALESCE(MAX(CASE WHEN d.reporting_paused = 1 THEN 1 ELSE 0 END), 0)
                   AS reporting_paused_any
        FROM users u
        LEFT JOIN devices d ON d.user_id = u.id
        {cond}
        GROUP BY u.id
        ORDER BY {EMPLOYEE_SORTS[sort]}
        LIMIT ? OFFSET ?
        """,
        [*params, page_size, (page - 1) * page_size],
    )
    items = [dict(row) | {"online": is_online(row["last_heartbeat"])} for row in rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def list_devices(db: Database, *, user_id: int) -> list[dict]:
    """员工设备子表（SPEC 5.2 一人多机；吊销设备不再判在线）。"""
    user = db.query_one("SELECT id FROM users WHERE id = ?", (user_id,))
    if user is None:
        raise ApiError(404, "not_found", "员工不存在", {"user_id": user_id})
    rows = db.query_all(
        "SELECT id, device_name, os, client_version, plugin_version, status,"
        " reporting_paused, last_seq, last_format_probe, last_heartbeat, created_at"
        " FROM devices WHERE user_id = ? ORDER BY id",
        (user_id,),
    )
    return [
        dict(row)
        | {
            "online": row["status"] == "active" and is_online(row["last_heartbeat"]),
        }
        for row in rows
    ]


def revoke_device(db: Database, *, actor: sqlite3.Row, device_id: int) -> dict:
    """吊销设备令牌（SPEC 5.2：每台独立吊销，笔记本丢失场景）。

    幂等：已吊销重复调用同样返回 200。生效后设备令牌上报即
    401 token_revoked（core/bind.verify_device_token）。
    """
    row = db.query_one(
        """
        SELECT d.id, d.status, d.device_name, d.user_id, u.employee_no
        FROM devices d LEFT JOIN users u ON u.id = d.user_id
        WHERE d.id = ?
        """,
        (device_id,),
    )
    if row is None:
        raise ApiError(404, "not_found", "设备不存在", {"device_id": device_id})
    if row["status"] != "revoked":
        with db.write_transaction() as conn:
            conn.execute("UPDATE devices SET status = 'revoked' WHERE id = ?", (device_id,))
            conn.execute(
                "INSERT INTO audit_log (actor_id, action, target, detail, at)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    actor["id"],
                    "device.revoke",
                    f"devices/{device_id}",
                    json.dumps(
                        {
                            "device_name": row["device_name"],
                            "user_id": row["user_id"],
                            "employee_no": row["employee_no"],
                        },
                        ensure_ascii=False,
                    ),
                    utc_now_iso(),
                ),
            )
    return {
        "device_id": device_id,
        "status": "revoked",
        "message": "设备令牌已吊销（该设备上报将立即被拒）",
    }
