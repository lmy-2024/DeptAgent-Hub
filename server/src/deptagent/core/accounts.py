"""账号治理服务（SPEC 8.3 四端点 + 权限约束 + 审计留痕）。

权限模型（SPEC 1.3 / 8.3）：
- admin 仅由 super 创建（本模块全部函数仅被 super 专属路由调用）；
- 改角色即改权限：role 变更写库即生效（JWT 不携带 role，每请求查库）；
- super 全部治理操作写入 audit_log（SPEC 14.1 第 8 条验收项）。
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..storage.database import Database
from .errors import ApiError
from .security import generate_password, hash_password
from .utc import utc_now_iso

ROLES = ("member", "lead", "admin", "super")
MIN_PASSWORD_LEN = 8


def _audit(
    db: Database, actor_id: int, action: str, target: str, detail: dict[str, Any] | None = None
) -> None:
    """写审计行（SPEC 7 章 audit_log：actor/action/target/detail/at）。"""
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


def _get_account(db: Database, user_id: int) -> sqlite3.Row:
    row = db.query_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if row is None:
        raise ApiError(404, "not_found", "账号不存在", {"user_id": user_id})
    return row


def _check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LEN:
        raise ApiError(
            422,
            "validation_error",
            f"密码长度不得少于 {MIN_PASSWORD_LEN} 位",
            {"min_length": MIN_PASSWORD_LEN},
        )


def init_super(db: Database, employee_no: str, password: str | None = None) -> tuple[bool, str]:
    """创建或重置 super 账号（SPEC 1.3 --init-super；10.1：与重置密码同一路径）。

    - 幂等：工号已存在且为 super → 仅更新密码哈希并重新启用；
    - 密码缺省 → 随机生成，明文仅本次返回（调用方负责展示一次）。
    返回 (是否新建, 最终密码明文)。
    """
    final_password = password or generate_password()
    _check_password(final_password)
    password_hash = hash_password(final_password)
    row = db.query_one("SELECT id, role FROM users WHERE employee_no = ?", (employee_no,))
    if row is None:
        db.execute(
            """
            INSERT INTO users
                (employee_no, name, display_name, role, status, password_hash, created_at)
            VALUES (?, ?, ?, 'super', 'active', ?, ?)
            """,
            (employee_no, "超级管理员", "Super", password_hash, utc_now_iso()),
        )
        return True, final_password
    if row["role"] != "super":
        raise ApiError(
            409,
            "account_exists",
            "该工号已存在且不是 super，不能通过 --init-super 覆盖",
            {"employee_no": employee_no, "role": row["role"]},
        )
    db.execute(
        "UPDATE users SET password_hash = ?, status = 'active' WHERE id = ?",
        (password_hash, row["id"]),
    )
    return False, final_password


def create_account(
    db: Database,
    *,
    actor: sqlite3.Row,
    employee_no: str,
    name: str,
    display_name: str | None,
    role: str,
    team: str | None,
    password: str | None,
) -> tuple[int, str]:
    """创建账号（SPEC 8.3：可指定为 admin；super 专属入口）。

    password 缺省 → 随机生成并在响应返回一次。返回 (user_id, 密码明文)。
    """
    if role not in ROLES:
        raise ApiError(422, "validation_error", f"角色必须是 {ROLES} 之一", {"role": role})
    final_password = password or generate_password()
    _check_password(final_password)
    if db.query_one("SELECT id FROM users WHERE employee_no = ?", (employee_no,)) is not None:
        raise ApiError(409, "account_exists", "工号已存在", {"employee_no": employee_no})

    user_id = db.execute(
        """
        INSERT INTO users
            (employee_no, name, display_name, role, team, status, password_hash, created_at)
        VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
        """,
        (employee_no, name, display_name, role, team, hash_password(final_password), utc_now_iso()),
    )
    _audit(
        db,
        actor["id"],
        "account.create",
        f"users/{user_id}",
        {
            "employee_no": employee_no,
            "role": role,
            "team": team,
            "password_generated": password is None,
        },
    )
    return user_id, final_password


def change_role(db: Database, *, actor: sqlite3.Row, user_id: int, new_role: str) -> str:
    """调整角色（SPEC 1.3"改角色即改权限"——写库即生效，无需失效 token）。"""
    if new_role not in ROLES:
        raise ApiError(422, "validation_error", f"角色必须是 {ROLES} 之一", {"role": new_role})
    row = _get_account(db, user_id)
    old_role = row["role"]
    if old_role == new_role:
        return old_role
    db.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
    _audit(
        db,
        actor["id"],
        "account.role_change",
        f"users/{user_id}",
        {"employee_no": row["employee_no"], "from": old_role, "to": new_role},
    )
    return old_role


def reset_password(
    db: Database, *, actor: sqlite3.Row, user_id: int, password: str | None
) -> tuple[str, str]:
    """重置密码（SPEC 8.3：账号恢复 break-glass 入口；旧密码立即失效）。

    password 缺省 → 随机生成。返回 (employee_no, 新密码明文——仅本次返回)。
    """
    row = _get_account(db, user_id)
    final_password = password or generate_password()
    _check_password(final_password)
    db.execute(
        "UPDATE users SET password_hash = ?, status = 'active' WHERE id = ?",
        (hash_password(final_password), user_id),
    )
    _audit(
        db,
        actor["id"],
        "account.reset_password",
        f"users/{user_id}",
        {"employee_no": row["employee_no"], "password_generated": password is None},
    )
    return row["employee_no"], final_password


def disable_account(db: Database, *, actor: sqlite3.Row, user_id: int) -> str:
    """停用账号（SPEC 8.3：可停用 super 以外的任何账号；幂等）。

    停用即失效：该账号持有中的 JWT 在下一次请求即被拒（deps 查库校验 status）。
    返回 employee_no。
    """
    row = _get_account(db, user_id)
    if row["role"] == "super":
        raise ApiError(
            400,
            "target_protected",
            "不能停用 super 账号（防系统失去治理入口）",
            {"user_id": user_id},
        )
    if row["status"] != "disabled":
        db.execute("UPDATE users SET status = 'disabled' WHERE id = ?", (user_id,))
        _audit(
            db,
            actor["id"],
            "account.disable",
            f"users/{user_id}",
            {"employee_no": row["employee_no"]},
        )
    return row["employee_no"]
