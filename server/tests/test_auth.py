"""登录端点（T0.5）：成功/失败/锁定/token 校验/停用即失效。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt as pyjwt

from deptagent.core.security import ALGORITHM


def test_login_success_returns_token_and_role(client, super_account):
    resp = client.post("/api/v1/auth/login", json=super_account)
    assert resp.status_code == 200
    body = resp.json()
    assert body["token"]
    assert body["role"] == "super"
    assert "T" in body["expires_at"]  # UTC ISO 8601（8.5 时间口径）


def test_login_wrong_password_unified_401(client, super_account):
    resp = client.post(
        "/api/v1/auth/login",
        json={"employee_no": super_account["employee_no"], "password": "wrong-password"},
    )
    assert resp.status_code == 401
    err = resp.json()["error"]
    assert err["code"] == "auth_failed"  # 8.5 枚举
    assert err["message"]
    assert err["detail"] == {}


def test_login_unknown_employee_no_same_error(client):
    # 工号不存在与密码错误不可区分（不泄露账号存在性）
    resp = client.post("/api/v1/auth/login", json={"employee_no": "NOPE", "password": "x" * 10})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "auth_failed"


def test_login_lockout_after_max_failures(client, super_account):
    for _ in range(5):
        resp = client.post(
            "/api/v1/auth/login",
            json={"employee_no": super_account["employee_no"], "password": "bad-password-1"},
        )
        assert resp.status_code == 401
    # 第 6 次：即使密码正确也被锁定（SPEC 12 章失败锁定）
    resp = client.post("/api/v1/auth/login", json=super_account)
    assert resp.status_code == 401
    err = resp.json()["error"]
    assert err["code"] == "auth_failed"
    assert err["detail"]["retry_after_seconds"] > 0


def test_login_lockout_is_per_employee_no(client, super_account):
    for _ in range(5):
        client.post(
            "/api/v1/auth/login",
            json={"employee_no": super_account["employee_no"], "password": "bad-password-1"},
        )
    # 其他工号的登录不受牵连（不存在也不报锁定，仍是普通 auth_failed）
    resp = client.post("/api/v1/auth/login", json={"employee_no": "OTHER", "password": "x" * 10})
    assert resp.status_code == 401
    assert resp.json()["error"]["detail"] == {}


def test_protected_endpoint_requires_token(client, super_token):
    resp = client.post("/api/v1/admin/accounts", json={})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "token_invalid"


def test_protected_endpoint_rejects_forged_token(client, super_token):
    resp = client.post(
        "/api/v1/admin/accounts",
        json={},
        headers={"Authorization": "Bearer not-a-jwt-at-all"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "token_invalid"


def test_protected_endpoint_rejects_expired_token(client, app, super_account):
    # 手工签发已过期 token（SPEC 10.1：12h 有效期；过期即失效）
    now = datetime.now(UTC)
    payload = {
        "sub": super_account["employee_no"],
        "iat": now - timedelta(hours=13),
        "exp": now - timedelta(hours=1),
    }
    expired = pyjwt.encode(payload, app.state.settings.jwt_secret, algorithm=ALGORITHM)
    resp = client.post(
        "/api/v1/admin/accounts", json={}, headers={"Authorization": f"Bearer {expired}"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "token_invalid"


def test_login_success_clears_failure_counter(client, super_account):
    for _ in range(4):  # 未达锁定阈值
        client.post(
            "/api/v1/auth/login",
            json={"employee_no": super_account["employee_no"], "password": "bad-password-1"},
        )
    resp = client.post("/api/v1/auth/login", json=super_account)
    assert resp.status_code == 200  # 成功登录清零计数
    resp = client.post(
        "/api/v1/auth/login",
        json={"employee_no": super_account["employee_no"], "password": "bad-password-1"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["detail"] == {}  # 计数已重置，未进入锁定
