"""账号治理四端点（T0.6/T0.7）——SPEC 14.1 第 8 条验收闭环。"""

from __future__ import annotations

import json


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---- super 正常路径 ----


def test_super_creates_admin_and_login_works(client, super_token):
    resp = client.post(
        "/api/v1/admin/accounts",
        json={
            "employee_no": "A100",
            "name": "管理员乙",
            "role": "admin",
            "password": "admin-pass-123456",
        },
        headers=_auth(super_token),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["employee_no"] == "A100"
    assert body["user_id"] > 0
    # 创建的 admin 可登录
    login = client.post(
        "/api/v1/auth/login", json={"employee_no": "A100", "password": "admin-pass-123456"}
    )
    assert login.status_code == 200
    assert login.json()["role"] == "admin"


def test_create_account_generates_password_when_missing(client, super_token):
    resp = client.post(
        "/api/v1/admin/accounts",
        json={"employee_no": "M100", "name": "员工甲", "role": "member"},
        headers=_auth(super_token),
    )
    assert resp.status_code == 201
    generated = resp.json()["password"]
    assert len(generated) >= 8  # 随机密码仅本次返回，且可直接登录
    login = client.post("/api/v1/auth/login", json={"employee_no": "M100", "password": generated})
    assert login.status_code == 200


def test_create_duplicate_employee_no_rejected(client, super_token, admin_account):
    resp = client.post(
        "/api/v1/admin/accounts",
        json={"employee_no": admin_account["employee_no"], "name": "重复", "role": "member"},
        headers=_auth(super_token),
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "account_exists"


# ---- 403 权限矩阵（14.1 第 8 条核心）----


def test_admin_cannot_call_any_governance_endpoint(client, admin_token):
    endpoints = [
        ("post", "/api/v1/admin/accounts", {"employee_no": "X1", "name": "x", "role": "member"}),
        ("patch", "/api/v1/admin/accounts/1/role", {"role": "member"}),
        ("post", "/api/v1/admin/accounts/1/reset-password", {}),
        ("post", "/api/v1/admin/accounts/1/disable", None),
    ]
    for method, path, payload in endpoints:
        call = getattr(client, method)
        resp = call(path, json=payload, headers=_auth(admin_token))
        assert resp.status_code == 403, f"{method.upper()} {path} 应拒绝 admin"
        assert resp.json()["error"]["code"] == "forbidden_role"


def test_admin_self_promotion_attempt_rejected(client, admin_token, db):
    admin_row = db.query_one("SELECT id FROM users WHERE employee_no = 'A001'")
    resp = client.patch(
        f"/api/v1/admin/accounts/{admin_row['id']}/role",
        json={"role": "super"},
        headers=_auth(admin_token),
    )
    # admin 调用任何治理端点均为 403——自我提权不例外（SPEC 8.3）
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden_role"
    assert (
        db.query_one("SELECT role FROM users WHERE id = ?", (admin_row["id"],))["role"] == "admin"
    )


def test_lead_cannot_call_any_governance_endpoint(client, lead_token):
    # 14.1 第 8 条：lead 无任何写操作入口（阶段 0 为 API 层验证；
    # console 登录页入口 T1.8 交付后由前端路由守卫 + 后端兑底复验）
    endpoints = [
        ("post", "/api/v1/admin/accounts", {"employee_no": "X2", "name": "x", "role": "member"}),
        ("patch", "/api/v1/admin/accounts/1/role", {"role": "member"}),
        ("post", "/api/v1/admin/accounts/1/reset-password", {}),
        ("post", "/api/v1/admin/accounts/1/disable", None),
    ]
    for method, path, payload in endpoints:
        call = getattr(client, method)
        resp = call(path, json=payload, headers=_auth(lead_token))
        assert resp.status_code == 403, f"{method.upper()} {path} 应拒绝 lead"
        assert resp.json()["error"]["code"] == "forbidden_role"


# ---- 角色即时生效（14.1 第 8 条：改角色即改权限）----


def test_role_change_takes_effect_immediately(client, super_token, db):
    created = client.post(
        "/api/v1/admin/accounts",
        json={
            "employee_no": "M200",
            "name": "员工乙",
            "role": "member",
            "password": "member-pass-123456",
        },
        headers=_auth(super_token),
    ).json()
    # member 登录 → 治理端点 403
    token = client.post(
        "/api/v1/auth/login", json={"employee_no": "M200", "password": "member-pass-123456"}
    ).json()["token"]
    assert client.post("/api/v1/admin/accounts", json={}, headers=_auth(token)).status_code == 403
    # super 提权为 super → 同一 token 立即可用（无需重新登录）
    resp = client.patch(
        f"/api/v1/admin/accounts/{created['user_id']}/role",
        json={"role": "super"},
        headers=_auth(super_token),
    )
    assert resp.status_code == 200
    assert (
        client.post(
            "/api/v1/admin/accounts",
            json={"employee_no": "M201", "name": "员工丙", "role": "member"},
            headers=_auth(token),
        ).status_code
        == 201
    )


# ---- 重置密码（14.1 第 8 条：旧密码立即失效）----


def test_reset_password_invalidates_old_immediately(client, super_token, db):
    created = client.post(
        "/api/v1/admin/accounts",
        json={
            "employee_no": "M300",
            "name": "员工丁",
            "role": "member",
            "password": "old-pass-123456",
        },
        headers=_auth(super_token),
    ).json()
    resp = client.post(
        f"/api/v1/admin/accounts/{created['user_id']}/reset-password",
        json={"password": "new-pass-654321"},
        headers=_auth(super_token),
    )
    assert resp.status_code == 200
    # 旧密码立即失效
    assert (
        client.post(
            "/api/v1/auth/login", json={"employee_no": "M300", "password": "old-pass-123456"}
        ).status_code
        == 401
    )
    # 新密码可登录
    assert (
        client.post(
            "/api/v1/auth/login", json={"employee_no": "M300", "password": "new-pass-654321"}
        ).status_code
        == 200
    )


def test_reset_password_generates_when_missing(client, super_token):
    created = client.post(
        "/api/v1/admin/accounts",
        json={
            "employee_no": "M310",
            "name": "员工戊",
            "role": "member",
            "password": "old-pass-123456",
        },
        headers=_auth(super_token),
    ).json()
    # 两种“未指定密码”形态：空对象 body 与完全不发 body（curl 原生场景）
    for payload in ({}, None):
        resp = client.post(
            f"/api/v1/admin/accounts/{created['user_id']}/reset-password",
            json=payload,
            headers=_auth(super_token),
        )
        assert resp.status_code == 200, f"payload={payload}"
        new_password = resp.json()["password"]
        assert new_password
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"employee_no": "M310", "password": new_password},
            ).status_code
            == 200
        )


# ---- 停用（14.1 第 8 条：持有 token 即时失效；super 不可停用）----


def test_disable_invalidates_held_token(client, super_token, db):
    created = client.post(
        "/api/v1/admin/accounts",
        json={
            "employee_no": "M400",
            "name": "员工己",
            "role": "member",
            "password": "member-pass-123456",
        },
        headers=_auth(super_token),
    ).json()
    token = client.post(
        "/api/v1/auth/login", json={"employee_no": "M400", "password": "member-pass-123456"}
    ).json()["token"]
    assert (
        client.post("/api/v1/admin/accounts", json={}, headers=_auth(token)).status_code == 403
    )  # 停用前：角色拒绝（403）
    resp = client.post(
        f"/api/v1/admin/accounts/{created['user_id']}/disable", headers=_auth(super_token)
    )
    assert resp.status_code == 200
    # 停用后：同 token 变为 401（账号状态拒绝，非角色拒绝）
    assert client.post("/api/v1/admin/accounts", json={}, headers=_auth(token)).status_code == 401
    # 停用后不能再登录
    assert (
        client.post(
            "/api/v1/auth/login", json={"employee_no": "M400", "password": "member-pass-123456"}
        ).status_code
        == 401
    )


def test_cannot_disable_super_account(client, super_token, db):
    super_row = db.query_one("SELECT id FROM users WHERE employee_no = 'SUPER001'")
    resp = client.post(
        f"/api/v1/admin/accounts/{super_row['id']}/disable", headers=_auth(super_token)
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "target_protected"


def test_operations_on_missing_user_return_404(client, super_token):
    for method, path, payload in [
        ("patch", "/api/v1/admin/accounts/999999/role", {"role": "member"}),
        ("post", "/api/v1/admin/accounts/999999/reset-password", {}),
        ("post", "/api/v1/admin/accounts/999999/disable", None),
    ]:
        resp = getattr(client, method)(path, json=payload, headers=_auth(super_token))
        assert resp.status_code == 404, path
        assert resp.json()["error"]["code"] == "not_found"


def test_invalid_role_rejected_as_422(client, super_token):
    resp = client.post(
        "/api/v1/admin/accounts",
        json={"employee_no": "M500", "name": "x", "role": "boss"},
        headers=_auth(super_token),
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


# ---- 审计留痕（14.1 第 8 条：super 操作全部出现在审计日志）----


def test_every_governance_operation_is_audited(client, super_token, admin_token, db):
    before = len(db.query_all("SELECT * FROM audit_log"))

    created = client.post(  # create
        "/api/v1/admin/accounts",
        json={"employee_no": "M600", "name": "员工庚", "role": "lead"},
        headers=_auth(super_token),
    ).json()
    client.patch(  # role_change
        f"/api/v1/admin/accounts/{created['user_id']}/role",
        json={"role": "member"},
        headers=_auth(super_token),
    )
    client.post(  # reset_password
        f"/api/v1/admin/accounts/{created['user_id']}/reset-password",
        json={"password": "audit-pass-123456"},
        headers=_auth(super_token),
    )
    client.post(  # disable
        f"/api/v1/admin/accounts/{created['user_id']}/disable", headers=_auth(super_token)
    )

    super_id = db.query_one("SELECT id FROM users WHERE employee_no = 'SUPER001'")["id"]
    actions = ["account.create", "account.role_change", "account.reset_password", "account.disable"]
    for action in actions:
        # 按 target 过滤：admin_account 等 fixture 也会产生 account.create 审计行
        rows = db.query_all(
            "SELECT * FROM audit_log WHERE action = ? AND target = ?",
            (action, f"users/{created['user_id']}"),
        )
        assert len(rows) == 1, f"{action} 应恰有一行审计"
        row = rows[0]
        assert row["actor_id"] == super_id
        assert row["target"] == f"users/{created['user_id']}"
        assert row["at"]  # UTC ISO 8601
        if row["detail"]:
            json.loads(row["detail"])  # detail 为合法 JSON

    assert len(db.query_all("SELECT * FROM audit_log")) == before + 4
    # admin 的 403 尝试不留审计（未发生治理动作，本阶段口径）
