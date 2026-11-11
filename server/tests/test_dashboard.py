"""驾驶舱端点（T1.12）——SPEC 4.2 / 3.4 验收。

数据形态：张三（财务科）四日 7200 + data-clean 无用量 + 李四（综合科）
一日 2000 + 王五（无用量，两台设备：A 从未上报、B 暂停上报）。
离线告警矩阵：张三设备 16 分钟前心跳（告警）/ 李四在线 / 王五 A 未上报
（告警）/ 王五 B reporting_paused=1（排除）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

TODAY = datetime.now().date()

# 造数日的相对偏移（原 T1.12 场景锚定 2026-11-10：10-15/11-02/11-09/11-10）。
# T1.15 回归实测发现写死日期会随真实日期腐化（30 天窗口滑动后窗口起点断言先坏），
# 改为相对 TODAY 生成，场景语义（含窗口内最近日 + 跨月日 + 无数据日）不变。
D1 = TODAY - timedelta(days=26)  # 窗口内最早数据日（原 10-15）
D2 = TODAY - timedelta(days=8)  # 跨月候选日（原 11-02）
D3 = TODAY - timedelta(days=1)  # 昨日（原 11-09）
ZHANG_DAILY_TOKENS = {D1: 1500, D2: 1200, D3: 3000, TODAY: 1500}  # 财务周报四日
LI_DAILY_TOKENS = {TODAY: 2000}  # 李四一日


def _month_tokens(daily: dict) -> int:
    """当月（TODAY 所在月）token 合计（month_tokens KPI 同口径）。"""
    month = TODAY.strftime("%Y-%m")
    return sum(t for d, t in daily.items() if d.strftime("%Y-%m") == month)


EXPECTED_MONTH_TOKENS = _month_tokens(ZHANG_DAILY_TOKENS) + _month_tokens(LI_DAILY_TOKENS)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _minutes_ago(n: int) -> str:
    return (datetime.now(UTC) - timedelta(minutes=n)).isoformat(timespec="seconds")


@pytest.fixture()
def member_with_password(client, super_token) -> str:
    client.post(
        "/api/v1/admin/accounts",
        json={
            "employee_no": "M904",
            "name": "员工丁",
            "role": "member",
            "password": "member-pass-123456",
        },
        headers=_auth(super_token),
    )
    resp = client.post(
        "/api/v1/auth/login",
        json={"employee_no": "M904", "password": "member-pass-123456"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def _bind(
    client,
    super_token: str,
    db,
    employee_no: str,
    name: str,
    team: str,
    device_name: str | None = None,
) -> dict:
    """邀请码绑定一台设备（一次性：每台设备一码），返回 bind 响应 + device_id。

    bind 响应不含 device_id（8.2 仅 device_token + server_config），
    按 user_id + device_name 从库里回查；一人多机时以 device_name 区分。
    """
    resolved_name = device_name or f"PC-{employee_no}"
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
            "device_info": {"name": resolved_name, "os": "Windows 11"},
        },
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()
    user_id = db.query_one("SELECT id FROM users WHERE employee_no = ?", (employee_no,))["id"]
    device_id = db.query_one(
        "SELECT id FROM devices WHERE user_id = ? AND device_name = ?",
        (user_id, resolved_name),
    )["id"]
    return {**result, "device_id": device_id}


@pytest.fixture()
def dashboard_world(client, super_token, db):
    """真实链路造数据：用量世界 + 离线设备矩阵。"""
    zhang = _bind(client, super_token, db, "M100", "张三", "财务科")
    resp = client.post(
        "/api/v1/telemetry/report",
        json={
            "seq": 1,
            "device": {},
            "agents": [
                {"agent_key": "finance-report", "name": "财务周报助手"},
                {"agent_key": "data-clean", "name": "数据清洗"},
            ],
            "usage": [
                {
                    "stat_date": D1.isoformat(),
                    "agent_key": "finance-report",
                    "provider_id": "dashscope",
                    "model": "qwen-max",
                    "prompt_tokens": 1000,
                    "completion_tokens": 500,
                    "call_count": 10,
                },
                {
                    "stat_date": D2.isoformat(),
                    "agent_key": "finance-report",
                    "provider_id": "dashscope",
                    "model": "qwen-max",
                    "prompt_tokens": 800,
                    "completion_tokens": 400,
                    "call_count": 8,
                },
                {
                    "stat_date": D3.isoformat(),
                    "agent_key": "finance-report",
                    "provider_id": "dashscope",
                    "model": "qwen-max",
                    "prompt_tokens": 2000,
                    "completion_tokens": 1000,
                    "call_count": 20,
                },
                {
                    "stat_date": TODAY.isoformat(),
                    "agent_key": "finance-report",
                    "provider_id": "dashscope",
                    "model": "qwen-max",
                    "prompt_tokens": 1000,
                    "completion_tokens": 500,
                    "call_count": 10,
                },
            ],
        },
        headers={"Authorization": f"Bearer {zhang['device_token']}"},
    )
    assert resp.status_code == 200, resp.text

    li = _bind(client, super_token, db, "M101", "李四", "综合科")
    resp = client.post(
        "/api/v1/telemetry/report",
        json={
            "seq": 1,
            "device": {},
            "agents": [{"agent_key": "hr-helper", "name": "人事问答助手"}],
            "usage": [
                {
                    "stat_date": TODAY.isoformat(),
                    "agent_key": "hr-helper",
                    "provider_id": "dashscope",
                    "model": "qwen-plus",
                    "prompt_tokens": 1200,
                    "completion_tokens": 800,
                    "call_count": 6,
                },
            ],
        },
        headers={"Authorization": f"Bearer {li['device_token']}"},
    )
    assert resp.status_code == 200, resp.text

    # 王五：两台设备均无上报（A：从未心跳 → 告警；B：暂停 → 排除）
    wang_a = _bind(client, super_token, db, "M102", "王五", "财务科", device_name="PC-M102-A")
    wang_b = _bind(client, super_token, db, "M102", "王五", "财务科", device_name="PC-M102-B")

    # 张三设备心跳拨到 16 分钟前（超 15 分钟在线阈值 → 告警）
    db.execute(
        "UPDATE devices SET last_heartbeat = ? WHERE id = ?",
        (_minutes_ago(16), zhang["device_id"]),
    )
    db.execute(
        "UPDATE devices SET reporting_paused = 1 WHERE id = ?",
        (wang_b["device_id"],),
    )
    return {"zhang": zhang, "li": li, "wang_a": wang_a, "wang_b": wang_b}


# ---- 角色门槛（4.2：驾驶舱可见角色 lead / admin / super）----


def test_member_cannot_access_dashboard(client, member_with_password):
    resp = client.get("/api/v1/admin/dashboard", headers=_auth(member_with_password))
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden_role"


def test_lead_can_access_dashboard(client, lead_token):
    assert client.get("/api/v1/admin/dashboard", headers=_auth(lead_token)).status_code == 200


# ---- KPI 四卡（4.2）----


def test_dashboard_empty_state(client, lead_token):
    body = client.get("/api/v1/admin/dashboard", headers=_auth(lead_token)).json()
    assert body["agents_total"] == 0
    assert body["agents_active_30d"] == 0
    assert body["month_tokens"] == 0
    assert body["employees_active_30d"] == 0
    assert body["offline_devices"] == []
    assert body["team_top"] == []
    # 趋势：30 个点全 0，日期连续
    assert len(body["trend"]) == 30
    assert all(p["total_tokens"] == 0 for p in body["trend"])
    dates = [p["date"] for p in body["trend"]]
    assert dates == sorted(dates)


def test_dashboard_kpis(client, lead_token, dashboard_world):
    body = client.get("/api/v1/admin/dashboard", headers=_auth(lead_token)).json()
    assert body["agents_total"] == 3  # finance-report / data-clean / hr-helper
    assert body["agents_active_30d"] == 2  # finance-report / hr-helper（近 30 天有用量）
    assert body["employees_active_30d"] == 2  # 张三 / 李四（王五无用量）
    # 本月 = TODAY 所在月（动态：跨月偏移日不计入）
    assert body["month_tokens"] == EXPECTED_MONTH_TOKENS


# ---- 离线设备告警（4.2 / 3.4：排除 reporting_paused=1）----


def test_dashboard_offline_devices(client, lead_token, dashboard_world):
    body = client.get("/api/v1/admin/dashboard", headers=_auth(lead_token)).json()
    offline = body["offline_devices"]
    ids = {item["device_id"] for item in offline}
    # 张三（16 分钟前心跳）+ 王五 A（从未上报 NULL 心跳）；
    # 李四在线、王五 B reporting_paused=1 均排除
    assert ids == {dashboard_world["zhang"]["device_id"], dashboard_world["wang_a"]["device_id"]}

    zhang_row = next(item for item in offline if "M100" in item["employee_no"])
    assert zhang_row["user_name"] == "张三"
    assert zhang_row["device_name"] == "PC-M100"
    assert zhang_row["team"] == "财务科"
    assert zhang_row["last_heartbeat"] is not None


# ---- 趋势 + 部门 Top（4.2）----


def test_dashboard_trend_and_team_top(client, lead_token, dashboard_world):
    body = client.get("/api/v1/admin/dashboard", headers=_auth(lead_token)).json()

    trend = body["trend"]
    assert len(trend) == 30
    dates = [p["date"] for p in trend]
    assert dates[0] == (TODAY - timedelta(days=29)).isoformat() and dates[-1] == TODAY.isoformat()
    assert dates == sorted(dates)  # 连续升序（补零后无缺口）
    by_date = {p["date"]: p["total_tokens"] for p in trend}
    assert by_date[D1.isoformat()] == 1500
    assert by_date[TODAY.isoformat()] == 3500  # 张三 1500 + 李四 2000（重叠日 = TODAY）
    assert by_date[(TODAY - timedelta(days=5)).isoformat()] == 0  # 无数据日补零
    assert sum(by_date.values()) == 9200  # 窗口内全量（30 天含 D1）

    assert body["team_top"] == [
        {"team": "财务科", "total_tokens": 7200},
        {"team": "综合科", "total_tokens": 2000},
    ]
