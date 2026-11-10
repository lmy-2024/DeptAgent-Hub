"""智能体台账端点（T1.10）——SPEC 4.2 / 5.3 / 8.5 验收。"""

from __future__ import annotations

import pytest


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def member_with_password(client, super_token) -> str:
    """带密码的 member（唯一能登录的形态，用于验证 403 兑底）。"""
    client.post(
        "/api/v1/admin/accounts",
        json={
            "employee_no": "M901",
            "name": "员工乙",
            "role": "member",
            "password": "member-pass-123456",
        },
        headers=_auth(super_token),
    )
    resp = client.post(
        "/api/v1/auth/login",
        json={"employee_no": "M901", "password": "member-pass-123456"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


@pytest.fixture()
def agent_with_usage(client, super_token, db):
    """真实链路造台账：邀请码 → 绑定 → 上报 agents + usage（两日）。"""
    code = client.post(
        "/api/v1/admin/invitations",
        json={"team": "财务科", "role": "member"},
        headers=_auth(super_token),
    ).json()["code"]
    resp = client.post(
        "/api/v1/bind",
        json={
            "invite_code": code,
            "employee_no": "M100",
            "name": "张三",
            "device_info": {"name": "PC-ZS001", "os": "Windows 11"},
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["device_token"]

    from datetime import date, timedelta

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    today = date.today().isoformat()
    resp = client.post(
        "/api/v1/telemetry/report",
        json={
            "seq": 1,
            "device": {},
            "agents": [
                {
                    "agent_key": "finance-report",
                    "name": "财务周报助手",
                    "description": "汇总各科室周报生成部门简报",
                },
                {"agent_key": "data-clean", "name": "数据清洗"},
            ],
            "usage": [
                {
                    "stat_date": today,
                    "agent_key": "finance-report",
                    "provider_id": "dashscope",
                    "model": "qwen-max",
                    "prompt_tokens": 1000,
                    "completion_tokens": 500,
                    "call_count": 10,
                },
                {
                    "stat_date": yesterday,
                    "agent_key": "finance-report",
                    "provider_id": "dashscope",
                    "model": "qwen-max",
                    "prompt_tokens": 2000,
                    "completion_tokens": 1000,
                    "call_count": 20,
                },
            ],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text

    rows = db.query_all("SELECT id, agent_key FROM agents ORDER BY id")
    return {row["agent_key"]: row["id"] for row in rows}


# ---- 角色门槛（4.2：台账页可见角色 lead / admin / super）----


def test_member_cannot_access_agents(client, member_with_password):
    for path in ("/api/v1/admin/agents", "/api/v1/admin/agents/1"):
        resp = client.get(path, headers=_auth(member_with_password))
        assert resp.status_code == 403, path
        assert resp.json()["error"]["code"] == "forbidden_role"


def test_lead_and_admin_can_list_agents(client, lead_token, admin_token):
    assert client.get("/api/v1/admin/agents", headers=_auth(lead_token)).status_code == 200
    assert client.get("/api/v1/admin/agents", headers=_auth(admin_token)).status_code == 200


# ---- 列表六列 + 筛选 + 分页（4.2 / 5.3 / 8.5）----


def test_list_agents_six_columns_and_owner_join(client, super_token, agent_with_usage):
    resp = client.get("/api/v1/admin/agents", headers=_auth(super_token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    row = next(item for item in body["items"] if item["agent_key"] == "finance-report")
    # 六列（4.2）：名称/功能描述/创建人/维护人/状态/所属科室
    assert row["name"] == "财务周报助手"
    assert row["description"] == "汇总各科室周报生成部门简报"
    assert row["owner_name"] == "张三"
    assert row["maintainer_name"] == "张三"  # 维护人默认=创建人（5.3）
    assert row["status"] == "new"  # 台账自动新增 new（5.3）
    assert row["team"] == "财务科"
    # 附加（5.3 Token 消耗）：两日 1000+500+2000+1000
    assert row["total_tokens"] == 4500


def test_list_agents_filters(client, super_token, agent_with_usage):
    base = {"headers": _auth(super_token)}

    body = client.get("/api/v1/admin/agents?status=active", **base).json()
    assert body["total"] == 0

    body = client.get("/api/v1/admin/agents?team=财务科", **base).json()
    assert body["total"] == 2

    body = client.get("/api/v1/admin/agents?q=周报", **base).json()
    assert [item["agent_key"] for item in body["items"]] == ["finance-report"]

    body = client.get("/api/v1/admin/agents?q=data-clean", **base).json()
    assert [item["agent_key"] for item in body["items"]] == ["data-clean"]

    # 状态筛选 Literal：非法值 422
    resp = client.get("/api/v1/admin/agents?status=unknown", **base)
    assert resp.status_code == 422


def test_list_agents_pagination_and_sort(client, super_token, agent_with_usage):
    base = {"headers": _auth(super_token)}

    body = client.get("/api/v1/admin/agents?page=1&page_size=1&sort=name", **base).json()
    assert len(body["items"]) == 1
    assert body["total"] == 2 and body["page"] == 1
    assert body["items"][0]["agent_key"] == "data-clean"  # name ASC: 数据清洗 < 财务周报助手

    body = client.get("/api/v1/admin/agents?page=2&page_size=1&sort=name", **base).json()
    assert body["items"][0]["agent_key"] == "finance-report"

    # 排序白名单：非法值 422
    resp = client.get("/api/v1/admin/agents?sort=total_tokens", **base)
    assert resp.status_code == 422


# ---- 详情抽屉（4.2：用量曲线 + 变更时间线）----


def test_agent_detail_series_summary_timeline(client, super_token, agent_with_usage):
    agent_id = agent_with_usage["finance-report"]
    resp = client.get(f"/api/v1/admin/agents/{agent_id}", headers=_auth(super_token))
    assert resp.status_code == 200
    body = resp.json()

    # 用量序列（按日升序，total_tokens 派生列）
    series = body["usage_series"]
    assert len(series) == 2
    assert [p["stat_date"] for p in series] == sorted(p["stat_date"] for p in series)
    totals = {p["stat_date"]: p["total_tokens"] for p in series}
    assert set(totals.values()) == {1500, 3000}

    # 汇总（全期）
    assert body["usage_summary"]["total_tokens"] == 4500
    assert body["usage_summary"]["call_count"] == 30
    assert body["usage_summary"]["days"] == 2

    # 时间线节点：首次发现 + 首末用量 + 最近上报
    kinds = {e["event"] for e in body["timeline"]}
    assert {"discovered", "first_usage", "last_usage", "last_seen"} <= kinds
    assert body["timeline"] == sorted(body["timeline"], key=lambda e: e["at"])

    # 基础字段与列表一致
    assert body["name"] == "财务周报助手"
    assert body["owner_employee_no"] == "M100"


def test_agent_detail_404(client, super_token):
    resp = client.get("/api/v1/admin/agents/999999", headers=_auth(super_token))
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_agent_without_usage_has_empty_series(client, super_token, agent_with_usage):
    """未上报用量的台账行（5.3：统计不等人，new 也立即纳入台账）。"""
    agent_id = agent_with_usage["data-clean"]
    body = client.get(f"/api/v1/admin/agents/{agent_id}", headers=_auth(super_token)).json()
    assert body["usage_series"] == []
    assert body["usage_summary"] == {"total_tokens": 0, "call_count": 0, "days": 0}
    assert {e["event"] for e in body["timeline"]} == {"discovered", "last_seen"}
    # 列表 total_tokens=0（5.3 Token 消耗列）
    row = next(
        item
        for item in client.get("/api/v1/admin/agents", headers=_auth(super_token)).json()["items"]
        if item["agent_key"] == "data-clean"
    )
    assert row["total_tokens"] == 0
