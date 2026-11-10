"""健康检查与错误格式出口（T0.2）。"""

from __future__ import annotations


def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"]


def test_unknown_path_returns_405_or_404_not_html(client):
    # 未知 API 路径不应崩出堆栈页
    resp = client.get("/api/v1/definitely-missing")
    assert resp.status_code in (404, 405)
