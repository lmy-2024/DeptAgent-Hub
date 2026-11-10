"""T1.4 上报端点骨架单测：鉴权/seq 防重放/吊销/宽松校验/响应结构。"""

from __future__ import annotations

import pytest


@pytest.fixture()
def device_token(client, db) -> str:
    """绑定一台设备并返回其令牌（经 8.2 正式链路签发）。"""
    db.execute(
        "INSERT INTO invitations (code, team, role, expires_at) VALUES (?, ?, ?, ?)",
        ("INV-TELEMETRY", "财务科", "member", "2099-01-01T00:00:00+00:00"),
    )
    resp = client.post(
        "/api/v1/bind",
        json={
            "invite_code": "INV-TELEMETRY",
            "employee_no": "T001",
            "device_info": {"name": "PC-T001", "os": "Windows 11"},
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["device_token"]


def _report(seq: int, **extra) -> dict:
    body = {
        "device": {
            "name": "PC-T001",
            "os": "Windows 11",
            "client_version": "2.3.0b3",
            "plugin_version": "0.1.0",
            "uptime_hours": 6.5,
            "binding_status": "ok",
            "format_probe": "qwenpaw-2.3",
            "reporting_paused": False,
        },
        "seq": seq,
        "agents": [],
        "usage": [],
    }
    body.update(extra)
    return body


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _device_row(db, employee_no: str = "T001"):
    return db.query_one(
        "SELECT * FROM devices WHERE token_hash IS NOT NULL AND user_id = ("
        f"SELECT id FROM users WHERE employee_no = '{employee_no}')"
    )


def test_report_heartbeat_stored(client, db, device_token):
    """T1.5：心跳 8 字段落 7.1 白名单列（last_seq 由 CAS 负责）。"""
    resp = client.post("/api/v1/telemetry/report", json=_report(1), headers=_auth(device_token))
    assert resp.status_code == 200, resp.text
    row = _device_row(db)
    assert row["device_name"] == "PC-T001"
    assert row["os"] == "Windows 11"
    assert row["client_version"] == "2.3.0b3"
    assert row["plugin_version"] == "0.1.0"
    assert row["last_format_probe"] == "qwenpaw-2.3"
    assert row["reporting_paused"] == 0
    assert row["last_heartbeat"]  # 服务器时刻（10.1 UTC ISO，不由客户端自报）


def test_report_heartbeat_none_keeps_previous(client, db, device_token):
    """T1.5：宽松校验语义——device 段缺省时 None 字段不覆盖已有值。"""
    first = client.post("/api/v1/telemetry/report", json=_report(1), headers=_auth(device_token))
    assert first.status_code == 200

    body = _report(2)
    body["device"] = {}  # 全字段 None
    second = client.post("/api/v1/telemetry/report", json=body, headers=_auth(device_token))
    assert second.status_code == 200
    row = _device_row(db)
    assert row["device_name"] == "PC-T001"  # 未被 None 覆盖
    assert row["os"] == "Windows 11"
    assert row["last_heartbeat"]  # 每次心跳都刷新

    # reporting_paused 布尔整型化：True → 1
    body3 = _report(3)
    body3["device"]["reporting_paused"] = True
    third = client.post("/api/v1/telemetry/report", json=body3, headers=_auth(device_token))
    assert third.status_code == 200
    assert _device_row(db)["reporting_paused"] == 1


def test_report_requires_token(client):
    resp = client.post("/api/v1/telemetry/report", json=_report(1))
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "token_invalid"


def test_report_rejects_unknown_token(client):
    resp = client.post("/api/v1/telemetry/report", json=_report(1), headers=_auth("no-such-token"))
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "token_invalid"


def test_report_seq_advances_and_replays_rejected(client, db, device_token):
    first = client.post("/api/v1/telemetry/report", json=_report(1), headers=_auth(device_token))
    assert first.status_code == 200, first.text
    data = first.json()
    assert data["plugin_latest"]
    assert data["server_config"]["report_intervals_sec"]["usage"] == 300

    # 水位已推进（devices.last_seq=1）
    device = db.query_one(
        "SELECT * FROM devices WHERE token_hash IS NOT NULL AND user_id = ("
        "SELECT id FROM users WHERE employee_no = 'T001')"
    )
    assert device["last_seq"] == 1

    # 同 seq 重放 → 409 seq_conflict（整包拒绝，SPEC 8.1/8.5）
    replay = client.post("/api/v1/telemetry/report", json=_report(1), headers=_auth(device_token))
    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == "seq_conflict"

    # 倒退 seq 同样拒绝
    rollback = client.post("/api/v1/telemetry/report", json=_report(0), headers=_auth(device_token))
    assert rollback.status_code == 409

    # 递增 seq 受理
    nxt = client.post("/api/v1/telemetry/report", json=_report(2), headers=_auth(device_token))
    assert nxt.status_code == 200


def test_report_agents_upsert_semantics(client, db, device_token):
    """T1.6：台账 UPSERT 归属语义 + 7.1 白名单。"""
    owner_id = db.query_one("SELECT id FROM users WHERE employee_no = 'T001'")["id"]

    body = _report(1)
    body["agents"] = [
        {"agent_key": "default", "name": "Default", "description": "主智能体", "status": "active"},
        {"agent_key": "helper-1"},  # name/description 缺省（宽松校验）
    ]
    resp = client.post("/api/v1/telemetry/report", json=body, headers=_auth(device_token))
    assert resp.status_code == 200, resp.text

    rows = db.query_all(
        "SELECT * FROM agents WHERE owner_user_id = ? ORDER BY agent_key", (owner_id,)
    )
    assert len(rows) == 2
    r0, r1 = rows
    # 归属：owner=令牌对应员工；维护人默认同创建人（8.1/5.3）
    assert r0["agent_key"] == "default"
    assert r0["owner_user_id"] == owner_id
    assert r0["maintainer_user_id"] == owner_id
    assert r0["name"] == "Default"
    assert r0["description"] == "主智能体"
    assert r0["status"] == "new"  # INSERT 首写 new；客户端 status 不落库
    assert r0["first_seen_at"] and r0["last_seen_at"]
    assert r1["name"] == "helper-1"  # name None 时 agent_key 兜底（NOT NULL）

    # 重报：白名单内更新生效；description None 不清空；blocked 不被覆盖
    db.execute(
        "UPDATE agents SET status = 'blocked' WHERE agent_key = 'default' AND owner_user_id = ?",
        (owner_id,),
    )
    body2 = _report(2)
    body2["agents"] = [
        {"agent_key": "default", "name": "Default v2", "description": None, "status": "active"},
    ]
    resp2 = client.post("/api/v1/telemetry/report", json=body2, headers=_auth(device_token))
    assert resp2.status_code == 200
    rows2 = db.query_all(
        "SELECT * FROM agents WHERE owner_user_id = ? ORDER BY agent_key", (owner_id,)
    )
    assert len(rows2) == 2  # 幂等不新增
    d = rows2[0]
    assert d["name"] == "Default v2"  # 白名单内字段更新
    assert d["description"] == "主智能体"  # None 不覆盖旧值
    assert d["status"] == "blocked"  # 服务端治理状态不被客户端覆盖（7.1）


def test_report_agents_same_key_two_employees(client, db, device_token):
    """T1.6：同名 agent_key 不同员工 → 两行（UNIQUE(owner, agent_key)）。"""
    db.execute(
        "INSERT INTO invitations (code, team, role, expires_at) VALUES (?, ?, ?, ?)",
        ("INV-T2", "财务科", "member", "2099-01-01T00:00:00+00:00"),
    )
    resp = client.post(
        "/api/v1/bind",
        json={
            "invite_code": "INV-T2",
            "employee_no": "T002",
            "device_info": {"name": "PC-T002"},
        },
    )
    assert resp.status_code == 200, resp.text
    token2 = resp.json()["device_token"]

    body1 = _report(1)
    body1["agents"] = [{"agent_key": "shared-key", "name": "A"}]
    first = client.post("/api/v1/telemetry/report", json=body1, headers=_auth(device_token))
    assert first.status_code == 200

    body2 = {
        "device": {},
        "seq": 1,
        "agents": [{"agent_key": "shared-key", "name": "B"}],
        "usage": [],
    }
    second = client.post("/api/v1/telemetry/report", json=body2, headers=_auth(token2))
    assert second.status_code == 200

    rows = db.query_all(
        "SELECT owner_user_id, name FROM agents "
        "WHERE agent_key = 'shared-key' ORDER BY owner_user_id"
    )
    assert len(rows) == 2  # 同名 key 在不同员工机器上各自成行
    assert {r["name"] for r in rows} == {"A", "B"}


def test_report_revoked_token_rejected(client, db, device_token):
    db.execute(
        "UPDATE devices SET status = 'revoked' WHERE token_hash IS NOT NULL AND user_id = ("
        "SELECT id FROM users WHERE employee_no = 'T001')"
    )
    resp = client.post("/api/v1/telemetry/report", json=_report(1), headers=_auth(device_token))
    # 吊销链路（3.7/8.5）：401 + token_revoked → 插件红灯停报
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "token_revoked"


def test_report_lenient_payload_validation(client, device_token):
    # 宽松校验（8.1）：未知字段忽略、段可缺省、计数缺省 0
    body = _report(5, unknown_top_field="x")
    body["device"]["unexpected"] = "y"
    body["usage"] = [
        {
            "stat_date": "2026-11-10",
            "provider_id": "dashscope",
            "model": "qwen-max",
        }
    ]
    resp = client.post("/api/v1/telemetry/report", json=body, headers=_auth(device_token))
    assert resp.status_code == 200, resp.text


def test_report_invalid_body_returns_validation_error(client, device_token):
    # 结构性错误走 422 validation_error（8.5 统一格式由 app 异常处理器保证）
    bad = _report(6)
    bad["agents"] = [{"name": "missing-agent-key"}]
    resp = client.post("/api/v1/telemetry/report", json=bad, headers=_auth(device_token))
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_report_usage_upsert_semantics(client, db, device_token):
    """T1.7：用量 UPSERT 归属解析 + 7.1 白名单（全量覆盖）+ team 快照。"""
    owner_id = db.query_one("SELECT id FROM users WHERE employee_no = 'T001'")["id"]

    body = _report(1)
    body["agents"] = [{"agent_key": "default", "name": "Default"}]
    body["usage"] = [
        {
            "stat_date": "2026-11-10",
            "agent_key": "default",
            "provider_id": "dashscope",
            "model": "qwen-max",
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "cache_read_tokens": 10,
            "cache_write_tokens": 5,
            "call_count": 2,
        },
        {
            "stat_date": "2026-11-10",
            "agent_key": None,  # 无归属 → 哨兵 0（8.1）
            "provider_id": "deepseek",
            "model": "deepseek-v4",
            "prompt_tokens": 7,
        },
    ]
    resp = client.post("/api/v1/telemetry/report", json=body, headers=_auth(device_token))
    assert resp.status_code == 200, resp.text

    agent_db_id = db.query_one(
        "SELECT id FROM agents WHERE agent_key = 'default' AND owner_user_id = ?",
        (owner_id,),
    )["id"]
    rows = db.query_all(
        "SELECT * FROM usage_daily WHERE user_id = ? ORDER BY agent_id", (owner_id,)
    )
    assert len(rows) == 2
    r_unowned, r_owned = rows  # ORDER BY agent_id：哨兵 0 排前
    # 归属解析：同包 agents 段先行入库，usage 按本人台账解析 agents.id
    assert r_owned["agent_id"] == agent_db_id
    assert r_owned["team"] == "财务科"  # INSERT 首写科室快照（7.1）
    assert r_owned["source"] == "client"  # source 由服务端固定
    assert r_owned["prompt_tokens"] == 100
    assert r_owned["completion_tokens"] == 50
    assert r_owned["cache_read_tokens"] == 10
    assert r_owned["cache_write_tokens"] == 5
    assert r_owned["call_count"] == 2
    assert r_unowned["agent_id"] == 0  # agent_key=None → 哨兵
    assert r_unowned["prompt_tokens"] == 7
    assert r_unowned["completion_tokens"] == 0  # 计数缺省 0（宽松校验）

    # 当日全量重传（3.6）：五计数全量覆盖；调岗后 team 不重算（7.1 快照）
    db.execute("UPDATE users SET team = '市场科' WHERE id = ?", (owner_id,))
    body2 = _report(2)
    body2["usage"] = [
        {
            "stat_date": "2026-11-10",
            "agent_key": "default",
            "provider_id": "dashscope",
            "model": "qwen-max",
            "prompt_tokens": 200,
            "call_count": 3,
        },
    ]
    resp2 = client.post("/api/v1/telemetry/report", json=body2, headers=_auth(device_token))
    assert resp2.status_code == 200
    rows2 = db.query_all(
        "SELECT * FROM usage_daily WHERE user_id = ? ORDER BY agent_id", (owner_id,)
    )
    assert len(rows2) == 2  # 幂等不新增
    d = rows2[1]
    assert d["prompt_tokens"] == 200  # 全量覆盖（非累加/非 COALESCE）
    assert d["call_count"] == 3
    assert d["completion_tokens"] == 0  # 重传缺省计数覆盖旧值（客户端负责报全量）
    assert d["team"] == "财务科"  # team 不在 UPDATE 白名单：调岗不重算历史


def test_report_usage_owner_scoped_resolution(client, db, device_token):
    """T1.7：归属解析仅限本人台账——他人 key 不解析（同名 key 不跨员工混）。"""
    db.execute(
        "INSERT INTO invitations (code, team, role, expires_at) VALUES (?, ?, ?, ?)",
        ("INV-UT2", "财务科", "member", "2099-01-01T00:00:00+00:00"),
    )
    resp = client.post(
        "/api/v1/bind",
        json={
            "invite_code": "INV-UT2",
            "employee_no": "T002",
            "device_info": {"name": "PC-T002"},
        },
    )
    assert resp.status_code == 200, resp.text
    # T001 台账里有 default；T002 未登记任何 key

    body = _report(1)
    body["agents"] = [{"agent_key": "default", "name": "Default"}]
    client.post("/api/v1/telemetry/report", json=body, headers=_auth(device_token))

    body2 = {
        "device": {},
        "seq": 1,
        "agents": [],
        "usage": [
            {
                "stat_date": "2026-11-10",
                "agent_key": "default",  # 他人台账的 key → 不解析
                "provider_id": "dashscope",
                "model": "qwen-max",
                "prompt_tokens": 1,
            }
        ],
    }
    second = client.post(
        "/api/v1/telemetry/report", json=body2, headers=_auth(resp.json()["device_token"])
    )
    assert second.status_code == 200, second.text

    t002_id = db.query_one("SELECT id FROM users WHERE employee_no = 'T002'")["id"]
    row = db.query_one("SELECT agent_id FROM usage_daily WHERE user_id = ?", (t002_id,))
    assert row["agent_id"] == 0  # 未归属哨兵：T001 的 default 不被 T002 解析


def test_usage_report_view_prefers_gateway(db):
    """T1.7：7.2 双 source 合并——网关行优先、无网关回退 client。"""
    _insert = (
        "INSERT INTO usage_daily (stat_date, user_id, agent_id, team, provider_id,"
        " model, prompt_tokens, completion_tokens, cache_read_tokens,"
        " cache_write_tokens, call_count, source)"
        " VALUES ('2026-11-10', 999, 0, NULL, ?, ?, ?, 0, 0, 0, 1, ?)"
    )
    db.execute(_insert, ("dashscope", "qwen-max", 100, "client"))
    # 同维度 gateway 行：client 行被 VIEW 排除
    db.execute(_insert, ("dashscope", "qwen-max", 300, "gateway"))
    # 仅有 client 的维度：入选（阶段一常态，VIEW 退化为全量 client）
    db.execute(_insert, ("deepseek", "deepseek-v4", 7, "client"))

    rows = db.query_all(
        "SELECT provider_id, source, prompt_tokens FROM usage_report ORDER BY provider_id"
    )
    assert [(r["provider_id"], r["source"], r["prompt_tokens"]) for r in rows] == [
        ("dashscope", "gateway", 300),  # gateway 优先，同维度 client 行排除
        ("deepseek", "client", 7),  # 无 gateway → client 回退入选
    ]
