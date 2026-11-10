"""SPA 静态站点深链接 fallback（T1.9 补）——/login 等客户端路由整页
导航不再 404，API 路径 404 保持 8.5 JSON。"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from deptagent.app import create_app
from deptagent.config import Settings


@pytest.fixture()
def client_with_dist(tmp_path) -> Iterator[TestClient]:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><body>CONSOLE-SPA</body></html>", encoding="utf-8")
    settings = Settings(
        db_path=str(tmp_path / "spa.db"),
        jwt_secret="unit-test-secret-0123456789abcdef",
        console_dist=str(dist),
    )
    with TestClient(create_app(settings)) as c:
        yield c


def test_spa_deep_link_serves_index(client_with_dist):
    # 整页导航 /login、/employees：回 index.html（React Router 接管）
    for path in ("/login", "/employees", "/"):
        resp = client_with_dist.get(path)
        assert resp.status_code == 200, path
        assert "CONSOLE-SPA" in resp.text, path


def test_api_404_keeps_json_error(client_with_dist):
    # API 未知路径：8.5 JSON（不被 SPA fallback 吞掉）
    resp = client_with_dist.get("/api/v1/nonexistent")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "error"


def test_health_still_json(client_with_dist):
    resp = client_with_dist.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
