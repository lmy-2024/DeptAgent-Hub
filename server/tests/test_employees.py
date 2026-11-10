"""员工与设备管理端点（T1.9）——SPEC 4.2 / 5.2 / 8.5 验收。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from deptagent.core.employees import ONLINE_WITHIN_SECONDS


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _bind(client, invite_code: str, employee_no: str, name: str = "员工", device: str = "PC-TEST"):
    resp = client.post(
        "/api/v1/bind",
        json={
            "invite_code": invite_code,
            "employee_no": employee_no,
            "name": name,
            "device_info": {"name": device, "os": "Windows 11", "client_version": "2.3.0b3"},
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["device_token"]


def _report(client, device_token: str, seq: int = 1):
    return client.post(
        "/api/v1/telemetry/report",
        json={"seq": seq, "device": {}},
        headers={"Authorization": f"Bearer {device_token}"},
    )


def _minutes_ago(n: int) -> str:
    return (datetime.now(UTC) - timedelta(minutes=n)).isoformat(timespec="seconds")


def _create_member(client, super_token: str, employee_no: str, team: str | None = None) -> int:
    resp = client.post(
        "/api/v1/admin/accounts",
        json={
            "employee_no": employee_no,
            "name": f"员工{employee_no}",
            "role": "member",
            "team": team,
        },
        headers=_auth(super_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["user_id"]


# ---- 角色门槛（SPEC 4.2：员工与设备页可见角色 admin / super）----


def test_lead_cannot_access_employee_endpoints(client, lead_token):
    endpoints = [
        ("get", "/api/v1/admin/employees", None),
        ("post", "/api/v1/admin/invitations", {"role": "member"}),
        ("get", "/api/v1/admin/invitations", None),
        ("get", "/api/v1/admin/employees/1/devices", None),
        ("post", "/api/v1/admin/devices/1/revoke", None),
    ]
    for method, path, payload in endpoints:
        kwargs = {"json": payload} if payload is not None else {}
        resp = getattr(client, method)(path, headers=_auth(lead_token), **kwargs)
        assert resp.status_code == 403, f"{method.upper()} {path} 应拒绝 lead"
        assert resp.json()["error"]["code"] == "forbidden_role"


def test_admin_can_access_employee_endpoints(client, admin_token):
    # admin 门槛（super ≥ admin 向下兼容）：列表类端点 200
    assert client.get("/api/v1/admin/employees", headers=_auth(admin_token)).status_code == 200
    assert client.get("/api/v1/admin/invitations", headers=_auth(admin_token)).status_code == 200


# ---- 员工列表（4.2：角色 / 科室 / 心跳灯 / 已暂停状态；8.5 分页）----


def test_employee_list_aggregates_and_online(client, super_token, db, member_single_device):
    member_id, device_id = member_single_device
    # 绑定后立即上报一次心跳 → 在线
    resp = client.get("/api/v1/admin/employees", headers=_auth(super_token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 2  # super + member（本用例不引入 admin fixture）
    row = next(item for item in body["items"] if item["id"] == member_id)
    assert row["role"] == "member"
    assert row["team"] == "财务科"
    assert row["device_count"] == 1
    assert row["device_active_count"] == 1
    assert row["online"] is True
    assert row["last_heartbeat"]

    # 心跳拨回 16 分钟前（> 15min 阈值）→ 离线；员工级灯 = 任一设备在线
    db.execute("UPDATE devices SET last_heartbeat = ? WHERE id = ?", (_minutes_ago(16), device_id))
    row = next(
        item
        for item in client.get("/api/v1/admin/employees", headers=_auth(super_token)).json()[
            "items"
        ]
        if item["id"] == member_id
    )
    assert row["online"] is False

    # 阈值边界内（14 分钟前）→ 在线；暂停上报任何一台 → reporting_paused_any
    db.execute(
        "UPDATE devices SET last_heartbeat = ?, reporting_paused = 1 WHERE id = ?",
        (_minutes_ago(ONLINE_WITHIN_SECONDS // 60 - 1), device_id),
    )
    row = next(
        item
        for item in client.get("/api/v1/admin/employees", headers=_auth(super_token)).json()[
            "items"
        ]
        if item["id"] == member_id
    )
    assert row["online"] is True
    assert row["reporting_paused_any"] == 1


def test_employee_list_filters_and_pagination(client, super_token):
    for no, team in [("B001", "财务科"), ("B002", "人事科"), ("B003", "财务科")]:
        _create_member(client, super_token, no, team=team)

    base = {"headers": _auth(super_token)}
    body = client.get("/api/v1/admin/employees?team=财务科", **base).json()
    assert {item["employee_no"] for item in body["items"]} >= {"B001", "B003"}
    assert all(item["team"] == "财务科" for item in body["items"])

    body = client.get("/api/v1/admin/employees?q=B002", **base).json()
    assert [item["employee_no"] for item in body["items"]] == ["B002"]

    body = client.get("/api/v1/admin/employees?page=1&page_size=2", **base).json()
    assert body["page"] == 1 and body["page_size"] == 2
    assert len(body["items"]) == 2
    assert body["total"] >= 4  # super + admin + B001~B003

    body = client.get("/api/v1/admin/employees?page=999&page_size=2", **base).json()
    assert body["items"] == []

    # 排序白名单：非法值 422
    resp = client.get("/api/v1/admin/employees?sort=role", **base)
    assert resp.status_code == 422


# ---- 邀请码（5.2：科室 / 角色 member|lead / 有效期 / 一次性）----


def test_create_invitation_fields_and_audit(client, admin_token, db):
    resp = client.post(
        "/api/v1/admin/invitations",
        json={"team": "财务科", "role": "lead", "expires_hours": 48},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["code"].startswith("DA-") and len(body["code"]) == 11  # DA- + 8 位
    assert body["team"] == "财务科"
    assert body["role"] == "lead"
    assert body["used_by"] is None
    expires = datetime.fromisoformat(body["expires_at"])
    delta_hours = (expires - datetime.now(UTC)).total_seconds() / 3600
    assert 47.9 < delta_hours < 48.1

    # 审计留痕（action=invitation.create；admin 也可开码，同留痕）
    rows = db.query_all(
        "SELECT * FROM audit_log WHERE action = 'invitation.create' AND target = ?",
        (f"invitations/{body['code']}",),
    )
    assert len(rows) == 1
    assert json.loads(rows[0]["detail"])["team"] == "财务科"


def test_create_invitation_defaults_and_role_guard(client, admin_token, db):
    body = client.post(
        "/api/v1/admin/invitations", json={"role": "member"}, headers=_auth(admin_token)
    ).json()
    assert body["team"] is None
    expires = datetime.fromisoformat(body["expires_at"])
    assert 71.9 < (expires - datetime.now(UTC)).total_seconds() / 3600 < 72.1  # 缺省 72h

    # admin/super 不可经邀请码签发（5.2 层级保护）——Literal 直接 422
    for role in ("admin", "super", "boss"):
        resp = client.post(
            "/api/v1/admin/invitations", json={"role": role}, headers=_auth(admin_token)
        )
        assert resp.status_code == 422, role
    assert db.query_one("SELECT COUNT(*) AS n FROM invitations WHERE role != 'member'")["n"] == 0


def test_invitation_list_marks_used_after_bind(client, admin_token, super_token, db):
    code = client.post(
        "/api/v1/admin/invitations", json={"role": "member"}, headers=_auth(admin_token)
    ).json()["code"]
    _bind(client, code, "M100")

    items = client.get("/api/v1/admin/invitations", headers=_auth(admin_token)).json()["items"]
    row = next(item for item in items if item["code"] == code)
    assert row["used_by"] is not None
    assert row["used_at"]

    # 一次性：已被使用的邀请码不能再绑（5.2）
    resp = client.post("/api/v1/bind", json={"invite_code": code, "employee_no": "M101"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invite_invalid"


# ---- 设备子表与吊销（5.2 一人多机独立吊销；3.7/8.5 吊销链路）----


def test_list_devices_hides_token_hash(client, super_token, member_dual_devices):
    member_id, device_ids, _tokens = member_dual_devices
    resp = client.get(f"/api/v1/admin/employees/{member_id}/devices", headers=_auth(super_token))
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2  # 一人多机：两台设备独立令牌
    assert all("token_hash" not in item for item in items)
    assert [item["device_name"] for item in items] == ["PC-WORK", "NB-LOST"]
    assert all(item["online"] is True for item in items)  # 两台都刚心跳过

    # 员工不存在 → 404
    resp = client.get("/api/v1/admin/employees/999999/devices", headers=_auth(super_token))
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_revoke_device_blocks_reporting_and_audited(client, super_token, db, member_dual_devices):
    member_id, device_ids, tokens = member_dual_devices
    lost_id = device_ids[1]  # NB-LOST（笔记本丢失场景）

    # 吊销前正常上报（fixture 已消费 seq=1，每台设备水位独立递增）
    assert _report(client, tokens[1], seq=2).status_code == 200

    resp = client.post(f"/api/v1/admin/devices/{lost_id}/revoke", headers=_auth(super_token))
    assert resp.status_code == 200
    assert resp.json()["status"] == "revoked"

    # 吊销后同令牌上报 → 401 token_revoked（8.5 吊销链路：鉴权先于 seq 水位）
    resp = _report(client, tokens[1], seq=3)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "token_revoked"

    # 另一台设备不受影响（独立吊销）
    assert _report(client, tokens[0], seq=2).status_code == 200

    # 员工聚合：active 设备数下降
    row = next(
        item
        for item in client.get("/api/v1/admin/employees", headers=_auth(super_token)).json()[
            "items"
        ]
        if item["id"] == member_id
    )
    assert row["device_count"] == 2 and row["device_active_count"] == 1

    # 幂等：重复吊销 200，不重复写审计
    resp = client.post(f"/api/v1/admin/devices/{lost_id}/revoke", headers=_auth(super_token))
    assert resp.status_code == 200
    rows = db.query_all(
        "SELECT * FROM audit_log WHERE action = 'device.revoke' AND target = ?",
        (f"devices/{lost_id}",),
    )
    assert len(rows) == 1
    detail = json.loads(rows[0]["detail"])
    assert detail["device_name"] == "NB-LOST"
    assert detail["employee_no"] == "M100"


def test_revoke_missing_device_returns_404(client, super_token):
    resp = client.post("/api/v1/admin/devices/999999/revoke", headers=_auth(super_token))
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


# ---- 夹具：真实链路造数据（邀请码 → 绑定 → 心跳上报）----


@pytest.fixture()
def member_single_device(client, super_token, db):
    """单设备员工：返回 (member_id, device_id)。"""
    code = client.post(
        "/api/v1/admin/invitations",
        json={"team": "财务科", "role": "member"},
        headers=_auth(super_token),
    ).json()["code"]
    token = _bind(client, code, "M100")
    assert _report(client, token, seq=1).status_code == 200
    member_id = db.query_one("SELECT id FROM users WHERE employee_no = 'M100'")["id"]
    device_id = db.query_one("SELECT id FROM devices WHERE user_id = ?", (member_id,))["id"]
    return member_id, device_id


@pytest.fixture()
def member_dual_devices(client, super_token, db):
    """双设备员工（一人多机：邀请码一次性 5.2，两码各绑一机）：
    返回 (member_id, device_ids, tokens)。"""
    tokens = []
    for name in ("PC-WORK", "NB-LOST"):
        # 邀请码一次性：每绑一台设备需新码（旧码 used_by 非空即作废）
        code = client.post(
            "/api/v1/admin/invitations",
            json={"team": "财务科", "role": "member"},
            headers=_auth(super_token),
        ).json()["code"]
        tokens.append(_bind(client, code, "M100", device=name))
    for token in tokens:
        assert _report(client, token, seq=1).status_code == 200
    member_id = db.query_one("SELECT id FROM users WHERE employee_no = 'M100'")["id"]
    rows = db.query_all("SELECT id FROM devices WHERE user_id = ? ORDER BY id", (member_id,))
    return member_id, [row["id"] for row in rows], tokens
