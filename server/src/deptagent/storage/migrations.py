"""编号迁移框架（SPEC 13.1：storage 层 = SQLite + 迁移）。

- 迁移 = (版本号, 描述, SQL 语句列表)，按版本号升序应用，原子事务；
- 幂等：重复调用按 schema_version 跳过已应用版本（T0.3 单测验证）；
- DDL 严格照抄 SPEC 第 7 章：阶段 0 仅建 users / devices / audit_log 首批三表
  （含索引）；agents / usage_daily 等随阶段 1 遥测竖切以迁移 002+ 增量加入。
"""

from __future__ import annotations

from ..core.utc import utc_now_iso
from .database import Database

MIGRATIONS: list[tuple[int, str, list[str]]] = [
    (
        1,
        "阶段0基线：users / devices / audit_log（SPEC 7 章）",
        [
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                employee_no TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL, display_name TEXT,
                role TEXT NOT NULL DEFAULT 'member',
                -- member / lead / admin / super（super 唯一或极少, --init-super 初始化, SPEC 1.3）
                team TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                password_hash TEXT NOT NULL,
                created_at TEXT, invited_by TEXT
            )
            """,
            """
            CREATE TABLE devices (
                id INTEGER PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                device_name TEXT, os TEXT,
                client_version TEXT,
                plugin_version TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                reporting_paused INTEGER DEFAULT 0,
                last_seq INTEGER NOT NULL DEFAULT 0,
                last_format_probe TEXT,
                last_heartbeat TEXT,
                token_hash TEXT UNIQUE NOT NULL,
                created_at TEXT
            )
            """,
            "CREATE INDEX idx_devices_user ON devices(user_id)",
            """
            CREATE TABLE audit_log (
                actor_id INTEGER, action TEXT, target TEXT, detail TEXT, at TEXT
            )
            """,
            "CREATE INDEX idx_audit_log_actor ON audit_log(actor_id, at)",
        ],
    ),
]


def migrate(db: Database) -> int:
    """应用未执行的迁移；返回本次新应用的迁移数（幂等：已应用则返回 0）。"""
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            description TEXT,
            applied_at TEXT
        )
        """
    )
    row = db.query_one("SELECT MAX(version) AS v FROM schema_version")
    applied = (row["v"] or 0) if row is not None else 0

    applied_now = 0
    for version, description, statements in MIGRATIONS:
        if version <= applied:
            continue
        with db.write_transaction() as conn:
            for stmt in statements:
                conn.execute(stmt)
            conn.execute(
                "INSERT INTO schema_version (version, description, applied_at) VALUES (?, ?, ?)",
                (version, description, utc_now_iso()),
            )
        applied_now += 1
    return applied_now
