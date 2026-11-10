"""编号迁移框架（SPEC 13.1：storage 层 = SQLite + 迁移）。

- 迁移 = (版本号, 描述, SQL 语句列表)，按版本号升序应用，原子事务；
- 幂等：重复调用按 schema_version 跳过已应用版本（T0.3 单测验证）；
- DDL 严格照抄 SPEC 第 7 章：阶段 0 仅建 users / devices / audit_log 首批三表
  （含索引）；002 = invitations（绑定链路 T1.3 提前建表，审批流/批量开码
  留阶段 2）；003 = agents（台账通道 T1.6）；004 = usage_daily +
  usage_report VIEW（用量通道 T1.7，双 source 合并口径 7.2；model_prices /
  gateway_usage 等留阶段三随网关竖切加入）。
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
    (
        2,
        "阶段1绑定链路：invitations（SPEC 7 章，审批流/批量开码留阶段2）",
        [
            """
            CREATE TABLE invitations (
                code TEXT PRIMARY KEY, team TEXT, role TEXT,
                expires_at TEXT, used_by INTEGER, used_at TEXT
            )
            """,
        ],
    ),
    (
        3,
        "阶段1台账通道：agents（SPEC 7 章）",
        [
            """
            CREATE TABLE agents (
                id INTEGER PRIMARY KEY,
                agent_key TEXT NOT NULL,              -- 客户端本地标识, 仅在单一员工内唯一
                owner_user_id INTEGER REFERENCES users(id),  -- 服务端按上报设备归属登记
                maintainer_user_id INTEGER,           -- 默认=创建人, 管理员可改派
                definition_key TEXT,                  -- 同模板/同源聚合键(可空): 全部门聚合统计用
                name TEXT NOT NULL, description TEXT,
                category TEXT, tags TEXT,
                status TEXT DEFAULT 'new',             -- new / active / archived / blocked
                shared INTEGER DEFAULT 0,
                first_seen_at TEXT, last_seen_at TEXT,
                UNIQUE(owner_user_id, agent_key)      -- 同名 agent_key 可在不同员工机器上出现
            )
            """,
            "CREATE INDEX idx_agents_owner ON agents(owner_user_id, status)",
            "CREATE INDEX idx_agents_def ON agents(definition_key)",
        ],
    ),
    (
        4,
        "阶段1用量通道：usage_daily + usage_report VIEW（SPEC 7 章/7.2）",
        [
            """
            CREATE TABLE usage_daily (
                id INTEGER PRIMARY KEY,
                stat_date TEXT NOT NULL, user_id INTEGER, agent_id INTEGER,
                -- agent_id=0 哨兵=未归属用量(8.1); UNIQUE 不判 NULL 故不可用 NULL
                team TEXT,                            -- 入库时点科室快照: 调岗不重算历史
                provider_id TEXT, model TEXT,
                prompt_tokens INTEGER DEFAULT 0, completion_tokens INTEGER DEFAULT 0,
                cache_read_tokens INTEGER DEFAULT 0, cache_write_tokens INTEGER DEFAULT 0,
                call_count INTEGER DEFAULT 0,
                source TEXT DEFAULT 'client',          -- client 上报 / gateway 计量
                UNIQUE(stat_date, user_id, agent_id, provider_id, model, source)
            )
            """,
            "CREATE INDEX idx_usage_daily_rpt ON usage_daily(stat_date, user_id, agent_id)",
            "CREATE INDEX idx_usage_daily_team ON usage_daily(stat_date, team)",
            """
            CREATE VIEW usage_report AS
            SELECT stat_date, user_id, agent_id, team, provider_id, model,
                   prompt_tokens, completion_tokens, cache_read_tokens,
                   cache_write_tokens, call_count, source
            FROM usage_daily u
            WHERE u.source = 'gateway'
               OR NOT EXISTS (
                   SELECT 1 FROM usage_daily g
                   WHERE g.stat_date = u.stat_date AND g.user_id = u.user_id
                     AND g.agent_id IS u.agent_id   -- IS: NULL 安全比较(PG 同义)
                     AND g.provider_id = u.provider_id AND g.model = u.model
                     AND g.source = 'gateway'
               )
            """,
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
