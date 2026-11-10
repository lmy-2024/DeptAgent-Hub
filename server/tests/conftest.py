"""测试夹具：独立临时库 + 应用实例 + super/admin 账号链。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from deptagent.app import create_app
from deptagent.config import Settings
from deptagent.core.accounts import init_super
from deptagent.storage.database import Database
from deptagent.storage.migrations import migrate

SUPER_PASSWORD = "super-pass-123456"


@pytest.fixture()
def settings(tmp_path) -> Settings:
    return Settings(
        db_path=str(tmp_path / "test.db"),
        jwt_secret="unit-test-secret-0123456789abcdef",  # ≥32B，避免短密钥警告
    )


@pytest.fixture()
def app(settings):
    return create_app(settings)


@pytest.fixture()
def client(app):
    # with 语句触发 lifespan：打开 DB、执行迁移、挂 state
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db(settings) -> Database:
    # 独立连接（不经 lifespan）：迁移测试与直接查库场景自足；
    # 与 client 的连接同库并发读写——WAL 模式下已提交数据互相可见
    database = Database.open(settings.db_path)
    migrate(database)
    yield database
    database.close()


@pytest.fixture()
def super_account(db) -> dict[str, str]:
    init_super(db, "SUPER001", SUPER_PASSWORD)
    return {"employee_no": "SUPER001", "password": SUPER_PASSWORD}


@pytest.fixture()
def super_token(client, super_account) -> str:
    resp = client.post("/api/v1/auth/login", json=super_account)
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def _create_account(client, token: str, **fields) -> dict:
    resp = client.post("/api/v1/admin/accounts", json=fields, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def admin_account(client, super_token) -> dict[str, str]:
    _create_account(
        client,
        super_token,
        employee_no="A001",
        name="管理员甲",
        role="admin",
        password="admin-pass-123456",
    )
    return {"employee_no": "A001", "password": "admin-pass-123456"}


@pytest.fixture()
def admin_token(client, admin_account) -> str:
    resp = client.post("/api/v1/auth/login", json=admin_account)
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]
