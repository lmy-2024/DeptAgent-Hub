"""用量分析端点（T1.11）——SPEC 4.2 / 7.2 / 8.5 验收。

数据形态：张三（M100 财务科）finance-report@qwen-max 四日
（10-15 / 11-02 / 11-09 / 11-10，合计 7200）+ 李四（M101 综合科）
hr-helper@qwen-plus 一日（11-10，2000）；覆盖跨周（归一周一）与跨月桶。
"""

from __future__ import annotations

import pytest

TODAY = "2026-11-10"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def member_with_password(client, super_token) -> str:
    """带密码的 member（唯一能登录的形态，用于验证 403 兑底）。"""
    client.post(
        "/api/v1/admin/accounts",
        json={
            "employee_no": "M903",
            "name": "员工丙",
            "role": "member",
            "password": "member-pass-123456",
        },
        headers=_auth(super_token),
    )
    resp = client.post(
        "/api/v1/auth/login",
        json={"employee_no": "M903", "password": "member-pass-123456"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


@pytest.fixture()
def usage_world(client, super_token):
    """真实链路造用量世界：两员工（不同科室/模型）跨周跨月多日。"""

    def _bind_and_report(employee_no: str, name: str, team: str, agents: list, usage: list):
        code = client.post(
            "/api/v1/admin/invitations",
            json={"team": team, "role": "member"},
            headers=_auth(super_token),
        ).json()["code"]
        resp = client.post(
            "/api/v1/bind",
            json={
                "invite_code": code,
                "employee_no": employee_no,
                "name": name,
                "device_info": {"name": f"PC-{employee_no}", "os": "Windows 11"},
            },
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["device_token"]

    token1 = _bind_and_report("M100", "张三", "财务科", [], [])
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
            ],
            "usage": [
                {  # 2026-10-15 周四 → 归一 10-12 周一；跨月桶 2026-10
                    "stat_date": "2026-10-15",
                    "agent_key": "finance-report",
                    "provider_id": "dashscope",
                    "model": "qwen-max",
                    "prompt_tokens": 1000,
                    "completion_tokens": 500,
                    "call_count": 10,
                },
                {
                    "stat_date": "2026-11-02",
                    "agent_key": "finance-report",
                    "provider_id": "dashscope",
                    "model": "qwen-max",
                    "prompt_tokens": 800,
                    "completion_tokens": 400,
                    "call_count": 8,
                },
                {
                    "stat_date": "2026-11-09",
                    "agent_key": "finance-report",
                    "provider_id": "dashscope",
                    "model": "qwen-max",
                    "prompt_tokens": 2000,
                    "completion_tokens": 1000,
                    "call_count": 20,
                },
                {
                    "stat_date": "2026-11-10",
                    "agent_key": "finance-report",
                    "provider_id": "dashscope",
                    "model": "qwen-max",
                    "prompt_tokens": 1000,
                    "completion_tokens": 500,
                    "call_count": 10,
                },
            ],
        },
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert resp.status_code == 200, resp.text

    token2 = _bind_and_report("M101", "李四", "综合科", [], [])
    resp = client.post(
        "/api/v1/telemetry/report",
        json={
            "seq": 1,
            "device": {},
            "agents": [
                {"agent_key": "hr-helper", "name": "人事问答助手"},
            ],
            "usage": [
                {
                    "stat_date": "2026-11-10",
                    "agent_key": "hr-helper",
                    "provider_id": "dashscope",
                    "model": "qwen-plus",
                    "prompt_tokens": 1200,
                    "completion_tokens": 800,
                    "call_count": 6,
                },
            ],
        },
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert resp.status_code == 200, resp.text
    return {"zhang": "M100", "li": "M101"}


# ---- 角色门槛（4.2：用量分析页可见角色 lead / admin / super）----


def test_member_cannot_access_usage(client, member_with_password):
    for path in ("/api/v1/admin/usage/aggregate", "/api/v1/admin/usage/export"):
        resp = client.get(path, headers=_auth(member_with_password))
        assert resp.status_code == 403, path
        assert resp.json()["error"]["code"] == "forbidden_role"


def test_lead_can_access_usage(client, lead_token):
    assert client.get("/api/v1/admin/usage/aggregate", headers=_auth(lead_token)).status_code == 200
    assert client.get("/api/v1/admin/usage/export", headers=_auth(lead_token)).status_code == 200


# ---- 四维聚合（4.2：人/智能体/模型/科室）----


def test_aggregate_by_employee(client, super_token, usage_world):
    body = client.get(
        f"/api/v1/admin/usage/aggregate?dimension=employee&to_date={TODAY}",
        headers=_auth(super_token),
    ).json()
    assert body["dimension"] == "employee" and body["granularity"] == "day"
    assert [m["label"] for m in body["series"]] == ["张三（M100）", "李四（M101）"]

    zhang = body["series"][0]
    assert zhang["total_tokens"] == 7200  # 1500+1200+3000+1500
    assert [b["bucket"] for b in zhang["buckets"]] == [
        "2026-10-15",
        "2026-11-02",
        "2026-11-09",
        "2026-11-10",
    ]
    assert body["series"][1]["total_tokens"] == 2000


def test_aggregate_by_agent(client, super_token, usage_world):
    body = client.get(
        f"/api/v1/admin/usage/aggregate?dimension=agent&to_date={TODAY}",
        headers=_auth(super_token),
    ).json()
    labels = {m["label"]: m["total_tokens"] for m in body["series"]}
    assert labels["财务周报助手（finance-report）"] == 7200
    assert labels["人事问答助手（hr-helper）"] == 2000


def test_aggregate_by_model(client, super_token, usage_world):
    body = client.get(
        f"/api/v1/admin/usage/aggregate?dimension=model&to_date={TODAY}",
        headers=_auth(super_token),
    ).json()
    labels = {m["label"]: m["total_tokens"] for m in body["series"]}
    assert labels["dashscope/qwen-max"] == 7200
    assert labels["dashscope/qwen-plus"] == 2000


def test_aggregate_by_team(client, super_token, usage_world):
    body = client.get(
        f"/api/v1/admin/usage/aggregate?dimension=team&to_date={TODAY}",
        headers=_auth(super_token),
    ).json()
    labels = {m["label"]: m["total_tokens"] for m in body["series"]}
    assert labels["财务科"] == 7200
    assert labels["综合科"] == 2000


# ---- 粒度（4.2：日/周/月）----


def test_aggregate_week_granularity(client, super_token, usage_world):
    """周桶归一到周一：10-15（周四）→ 10-12；11-09+11-10 同周合并。"""
    body = client.get(
        f"/api/v1/admin/usage/aggregate?dimension=employee&granularity=week&to_date={TODAY}",
        headers=_auth(super_token),
    ).json()
    zhang = next(m for m in body["series"] if "M100" in m["label"])
    buckets = {b["bucket"]: b["total_tokens"] for b in zhang["buckets"]}
    assert buckets == {"2026-10-12": 1500, "2026-11-02": 1200, "2026-11-09": 4500}


def test_aggregate_month_granularity(client, super_token, usage_world):
    body = client.get(
        f"/api/v1/admin/usage/aggregate?dimension=employee&granularity=month&to_date={TODAY}",
        headers=_auth(super_token),
    ).json()
    zhang = next(m for m in body["series"] if "M100" in m["label"])
    buckets = {b["bucket"]: b["total_tokens"] for b in zhang["buckets"]}
    assert buckets == {"2026-10": 1500, "2026-11": 5700}


# ---- 日期窗口与参数校验 ----


def test_aggregate_date_range_filters(client, super_token, usage_world):
    body = client.get(
        "/api/v1/admin/usage/aggregate?dimension=employee&from_date=2026-11-01&to_date=2026-11-10",
        headers=_auth(super_token),
    ).json()
    zhang = next(m for m in body["series"] if "M100" in m["label"])
    assert zhang["total_tokens"] == 5700  # 10-15 被窗口滤除
    assert all(b["bucket"] >= "2026-11-01" for b in zhang["buckets"])


def test_aggregate_rejects_bad_params(client, super_token):
    base = {"headers": _auth(super_token)}
    assert client.get("/api/v1/admin/usage/aggregate?dimension=bogus", **base).status_code == 422
    assert client.get("/api/v1/admin/usage/aggregate?granularity=year", **base).status_code == 422
    assert (
        client.get("/api/v1/admin/usage/aggregate?from_date=not-a-date", **base).status_code == 422
    )
    # from > to：业务校验（8.5 统一错误体）
    resp = client.get(
        "/api/v1/admin/usage/aggregate?from_date=2026-11-10&to_date=2026-11-01", **base
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


# ---- CSV 导出（8.5：UTF-8 BOM + CRLF）----


def test_export_csv(client, super_token, usage_world):
    resp = client.get(
        "/api/v1/admin/usage/export?dimension=employee&from_date=2026-10-01&to_date=2026-11-10",
        headers=_auth(super_token),
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "usage-employee-day_2026-10-01_2026-11-10.csv" in resp.headers["content-disposition"]

    # BOM + CRLF（SPEC 8.5）
    assert resp.content[:3] == b"\xef\xbb\xbf"
    lines = resp.content[3:].decode("utf-8").split("\r\n")
    assert lines[0] == "成员,2026-10-15,2026-11-02,2026-11-09,2026-11-10,合计Token,调用次数"
    assert lines[1] == "张三（M100）,1500,1200,3000,1500,7200,48"
    assert lines[2] == "李四（M101）,,,,2000,2000,6"


def test_export_csv_week_buckets(client, super_token, usage_world):
    """导出与聚合同口径：周桶列。"""
    resp = client.get(
        "/api/v1/admin/usage/export?dimension=employee&granularity=week"
        "&from_date=2026-10-01&to_date=2026-11-10",
        headers=_auth(super_token),
    )
    assert resp.status_code == 200
    lines = resp.content[3:].decode("utf-8").split("\r\n")
    assert lines[0] == "成员,2026-10-12,2026-11-02,2026-11-09,合计Token,调用次数"
    assert lines[1] == "张三（M100）,1500,1200,4500,7200,48"
