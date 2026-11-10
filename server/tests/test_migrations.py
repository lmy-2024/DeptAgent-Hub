"""迁移框架（T0.3）：幂等、表结构对齐 SPEC 7 章。"""

from __future__ import annotations

from deptagent.storage.database import Database
from deptagent.storage.migrations import MIGRATIONS, migrate


def _table_columns(db: Database, table: str) -> list[str]:
    return [row["name"] for row in db.query_all(f"PRAGMA table_info({table})")]


def test_migrate_idempotent(tmp_path):
    db = Database.open(tmp_path / "m.db")
    first = migrate(db)
    assert first == len(MIGRATIONS)
    second = migrate(db)  # 重复执行：零变更
    assert second == 0
    rows = db.query_all("SELECT version FROM schema_version")
    assert [r["version"] for r in rows] == [m[0] for m in MIGRATIONS]
    db.close()


def test_tables_match_spec(db):
    # users（SPEC 7 章阶段一 DDL 逐列核对）
    assert set(_table_columns(db, "users")) == {
        "id",
        "employee_no",
        "name",
        "display_name",
        "role",
        "team",
        "status",
        "password_hash",
        "created_at",
        "invited_by",
    }
    # devices（v0.5 重写版：status / reporting_paused / last_seq / token_hash UNIQUE）
    assert set(_table_columns(db, "devices")) == {
        "id",
        "user_id",
        "device_name",
        "os",
        "client_version",
        "plugin_version",
        "status",
        "reporting_paused",
        "last_seq",
        "last_format_probe",
        "last_heartbeat",
        "token_hash",
        "created_at",
    }
    devices_sql = db.query_one(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='devices'"
    )["sql"].upper()
    assert "TOKEN_HASH TEXT UNIQUE NOT NULL" in devices_sql
    # audit_log（无主键，照抄 SPEC 7 章）
    assert set(_table_columns(db, "audit_log")) == {
        "actor_id",
        "action",
        "target",
        "detail",
        "at",
    }
    # agents（T1.6 台账通道，SPEC 7 章逐列核对）
    assert set(_table_columns(db, "agents")) == {
        "id",
        "agent_key",
        "owner_user_id",
        "maintainer_user_id",
        "definition_key",
        "name",
        "description",
        "category",
        "tags",
        "status",
        "shared",
        "first_seen_at",
        "last_seen_at",
    }
    agents_sql = db.query_one(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='agents'"
    )["sql"].upper()
    assert "UNIQUE(OWNER_USER_ID, AGENT_KEY)" in agents_sql
    # usage_daily（T1.7 用量通道，SPEC 7 章逐列核对）
    assert set(_table_columns(db, "usage_daily")) == {
        "id",
        "stat_date",
        "user_id",
        "agent_id",
        "team",
        "provider_id",
        "model",
        "prompt_tokens",
        "completion_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "call_count",
        "source",
    }
    usage_sql = db.query_one(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='usage_daily'"
    )["sql"].upper()
    assert "UNIQUE(STAT_DATE, USER_ID, AGENT_ID, PROVIDER_ID, MODEL, SOURCE)" in usage_sql


def test_usage_report_view_exists(db):
    """T1.7：usage_report VIEW（7.2 双 source 合并口径）已建且可查。"""
    view = db.query_one(
        "SELECT sql FROM sqlite_master WHERE type='view' AND name='usage_report'"
    )
    assert view is not None
    assert "SOURCE = 'GATEWAY'" in view["sql"].upper()
    # 空表可查（报表一律走 VIEW，禁止直查 usage_daily）
    assert db.query_all("SELECT * FROM usage_report") == []


def test_indexes_exist(db):
    names = {
        row["name"] for row in db.query_all("SELECT name FROM sqlite_master WHERE type='index'")
    }
    assert {
        "idx_devices_user",
        "idx_audit_log_actor",
        "idx_agents_owner",
        "idx_agents_def",
        "idx_usage_daily_rpt",
        "idx_usage_daily_team",
    } <= names


def test_wal_mode(db):
    row = db.query_one("PRAGMA journal_mode")
    assert row[0].lower() == "wal"


def test_foreign_keys_on(db):
    row = db.query_one("PRAGMA foreign_keys")
    assert row[0] == 1
