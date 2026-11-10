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


def test_report_requires_token(client):
    resp = client.post("/api/v1/telemetry/report", json=_report(1))
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "token_invalid"


def test_report_rejects_unknown_token(client):
    resp = client.post(
        "/api/v1/telemetry/report", json=_report(1), headers=_auth("no-such-token")
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "token_invalid"


def test_report_seq_advances_and_replays_rejected(client, db, device_token):
    first = client.post(
        "/api/v1/telemetry/report", json=_report(1), headers=_auth(device_token)
    )
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
    replay = client.post(
        "/api/v1/telemetry/report", json=_report(1), headers=_auth(device_token)
    )
    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == "seq_conflict"

    # 倒退 seq 同样拒绝
    rollback = client.post(
        "/api/v1/telemetry/report", json=_report(0), headers=_auth(device_token)
    )
    assert rollback.status_code == 409

    # 递增 seq 受理
    nxt = client.post(
        "/api/v1/telemetry/report", json=_report(2), headers=_auth(device_token)
    )
    assert nxt.status_code == 200


def test_report_revoked_token_rejected(client, db, device_token):
    db.execute(
        "UPDATE devices SET status = 'revoked' WHERE token_hash IS NOT NULL AND user_id = ("
        "SELECT id FROM users WHERE employee_no = 'T001')"
    )
    resp = client.post(
        "/api/v1/telemetry/report", json=_report(1), headers=_auth(device_token)
    )
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
    resp = client.post(
        "/api/v1/telemetry/report", json=body, headers=_auth(device_token)
    )
    assert resp.status_code == 200, resp.text


def test_report_invalid_body_returns_validation_error(client, device_token):
    # 结构性错误走 422 validation_error（8.5 统一格式由 app 异常处理器保证）
    bad = _report(6)
    bad["agents"] = [{"name": "missing-agent-key"}]
    resp = client.post(
        "/api/v1/telemetry/report", json=bad, headers=_auth(device_token)
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"
