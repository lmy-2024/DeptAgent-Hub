"""T1.3 绑定链路单测：错码/过期码/一次性/枚举限速/一人多机/停用员工/可登录密码。"""

from __future__ import annotations

import time

import pytest

from deptagent.core.bind import token_sha256


@pytest.fixture()
def invite(db) -> dict:
    """未过期、未使用的 member 邀请码（role/team 由码指定，SPEC 5.2）。"""
    db.execute(
        "INSERT INTO invitations (code, team, role, expires_at) VALUES (?, ?, ?, ?)",
        ("INV-TEST-001", "财务科", "member", "2099-01-01T00:00:00+00:00"),
    )
    return {"code": "INV-TEST-001", "team": "财务科", "role": "member"}


def _bind_body(invite_code: str, employee_no: str = "E001", **extra) -> dict:
    body = {
        "invite_code": invite_code,
        "employee_no": employee_no,
        "device_info": {"name": "PC-E001", "os": "Windows 11", "client_version": "2.3.0b3"},
    }
    body.update(extra)
    return body


def test_bind_creates_user_and_device_with_token_hash(client, db, invite):
    resp = client.post("/api/v1/bind", json=_bind_body(invite["code"], name="员工甲"))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    token = data["device_token"]

    # 明文令牌仅响应出现一次；库内只存 SHA-256（SPEC 10.1）
    user = db.query_one("SELECT * FROM users WHERE employee_no = 'E001'")
    assert user is not None
    assert (user["name"], user["role"], user["team"], user["status"]) == (
        "员工甲",
        "member",
        "财务科",
        "active",
    )
    device = db.query_one("SELECT * FROM devices WHERE user_id = ?", (user["id"],))
    assert device is not None
    assert device["token_hash"] == token_sha256(token)
    assert device["token_hash"] != token
    assert device["status"] == "active"

    # 邀请码一次性：used_by/used_at 置位
    used = db.query_one("SELECT * FROM invitations WHERE code = ?", (invite["code"],))
    assert used["used_by"] == user["id"]

    # 响应携带服务器参数（D2 拍板频率下发）
    assert data["server_config"]["report_intervals_sec"] == {
        "usage": 300,
        "agents": 900,
        "heartbeat": 300,
    }


def test_bind_wrong_code_rejected(client, invite):
    resp = client.post("/api/v1/bind", json=_bind_body("INV-NOT-EXIST"))
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invite_invalid"


def test_bind_expired_code_rejected(client, db):
    db.execute(
        "INSERT INTO invitations (code, team, role, expires_at) VALUES (?, ?, ?, ?)",
        ("INV-EXPIRED", "财务科", "member", "2000-01-01T00:00:00+00:00"),
    )
    resp = client.post("/api/v1/bind", json=_bind_body("INV-EXPIRED"))
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invite_expired"


def test_invite_single_use_second_bind_rejected(client, db, invite):
    first = client.post("/api/v1/bind", json=_bind_body(invite["code"]))
    assert first.status_code == 200
    second = client.post("/api/v1/bind", json=_bind_body(invite["code"], employee_no="E002"))
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "invite_invalid"
    # 第二次失败不产生新用户（一次性原子性）
    assert db.query_one("SELECT * FROM users WHERE employee_no = 'E002'") is None


def test_bind_rate_limit_blocks_enumeration(client):
    # 连续 10 次失败（错码）后第 11 次被 429 拒绝——失败请求同样计数（防枚举）
    for i in range(10):
        resp = client.post("/api/v1/bind", json=_bind_body(f"INV-GUESS-{i}"))
        assert resp.status_code == 400
    blocked = client.post("/api/v1/bind", json=_bind_body("INV-GUESS-10"))
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert blocked.json()["error"]["detail"]["retry_after_seconds"] > 0


def test_bind_rate_limit_window_slides(client):
    for i in range(10):
        client.post("/api/v1/bind", json=_bind_body(f"INV-W-{i}"))
    assert client.post("/api/v1/bind", json=_bind_body("INV-W-11")).status_code == 429
    # 最早一次滑出 60s 窗口后恢复受理（直接改时间戳模拟等待）
    limiter = client.app.state.bind_limiter
    hits = limiter._hits["testclient"]
    hits[0] = time.monotonic() - limiter._window - 1
    resp = client.post("/api/v1/bind", json=_bind_body("INV-W-12"))
    assert resp.status_code == 400  # 错码而非 429：限速已解除


def test_same_employee_binds_second_device(client, db, invite):
    t1 = client.post("/api/v1/bind", json=_bind_body(invite["code"])).json()["device_token"]
    # 一人多机：第二台设备需要另一张邀请码（一码一用）
    db.execute(
        "INSERT INTO invitations (code, team, role, expires_at) VALUES (?, ?, ?, ?)",
        ("INV-SECOND", "财务科", "member", "2099-01-01T00:00:00+00:00"),
    )
    t2 = client.post("/api/v1/bind", json=_bind_body("INV-SECOND", employee_no="E001")).json()[
        "device_token"
    ]
    # 两台设备、两个独立令牌、同一 user_id（可单独吊销，SPEC 5.2）
    assert t1 != t2
    user = db.query_one("SELECT * FROM users WHERE employee_no = 'E001'")
    devices = db.query_all("SELECT * FROM devices WHERE user_id = ? ORDER BY id", (user["id"],))
    assert len(devices) == 2
    assert {d["token_hash"] for d in devices} == {token_sha256(t1), token_sha256(t2)}


def test_disabled_employee_cannot_bind(client, db, super_token, invite):
    from tests.conftest import _create_account  # noqa: PLC0415 - 测试内复用造号工具

    account = _create_account(
        client,
        super_token,
        employee_no="E100",
        name="停用者",
        role="member",
        password="member-pass-123456",
    )
    client.post(
        f"/api/v1/admin/accounts/{account['user_id']}/disable",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    db.execute(
        "INSERT INTO invitations (code, team, role, expires_at) VALUES (?, ?, ?, ?)",
        ("INV-DISABLED", "财务科", "member", "2099-01-01T00:00:00+00:00"),
    )
    resp = client.post("/api/v1/bind", json=_bind_body("INV-DISABLED", employee_no="E100"))
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invite_invalid"


def test_bind_with_password_creates_loginable_account(client, invite):
    body = _bind_body(invite["code"], password="self-pass-123456")
    resp = client.post("/api/v1/bind", json=body)
    assert resp.status_code == 200
    login = client.post(
        "/api/v1/auth/login",
        json={"employee_no": "E001", "password": "self-pass-123456"},
    )
    assert login.status_code == 200, login.text
    assert login.json()["role"] == "member"


def test_bind_without_password_cannot_login(client, invite):
    resp = client.post("/api/v1/bind", json=_bind_body(invite["code"]))
    assert resp.status_code == 200
    login = client.post(
        "/api/v1/auth/login",
        json={"employee_no": "E001", "password": "whatever-pass-123456"},
    )
    # 占位哈希不可登录（admin 之后经 reset-password 设定，SPEC 8.2）
    assert login.status_code == 401
    assert login.json()["error"]["code"] == "auth_failed"
