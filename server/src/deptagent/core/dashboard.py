"""驾驶舱服务（SPEC 4.2：T1.12 总览页，lead 门槛）。

KPI 四卡（智能体总数 / 近 30 天活跃智能体 / 本月 Token / 近 30 天活跃员工）+
离线设备告警（排除 reporting_paused=1，3.4：主动暂停 ≠ 离线）+
近 30 天逐日 Token 趋势（补零）+ 部门（科室）Top 榜。
成本折算留阶段 2（4.2"成本折算 2"，无单价表宁缺毋滥）；
活跃口径 = 近 30 天 usage_report 出现（与台账 status 解耦，统计不等 5.3）。
"""

from __future__ import annotations

from datetime import date, timedelta

from ..storage.database import Database
from .employees import is_online

TREND_WINDOW_DAYS = 30
TEAM_TOP_LIMIT = 10


def get_dashboard(db: Database) -> dict:
    today = date.today()
    window_start = (today - timedelta(days=TREND_WINDOW_DAYS - 1)).isoformat()
    month = today.strftime("%Y-%m")

    agents_total = db.query_one("SELECT COUNT(*) AS c FROM agents")["c"]

    active = db.query_one(
        """
        SELECT COUNT(DISTINCT ur.agent_id) AS agents, COUNT(DISTINCT ur.user_id) AS employees
        FROM usage_report ur
        WHERE ur.stat_date >= ? AND ur.agent_id > 0
        """,
        (window_start,),
    )
    agents_active_30d = active["agents"] or 0
    employees_active_30d = active["employees"] or 0

    month_tokens = db.query_one(
        """
        SELECT COALESCE(SUM(ur.prompt_tokens + ur.completion_tokens
                            + ur.cache_read_tokens + ur.cache_write_tokens), 0) AS t
        FROM usage_report ur
        WHERE strftime('%Y-%m', ur.stat_date) = ?
        """,
        (month,),
    )["t"]

    # 离线设备告警：status=active 且未主动暂停且超 15 分钟无心跳。
    # 时间阈值在 Python 端判定（is_online 与员工页同口径；ISO 带时区偏移
    # 的 last_heartbeat 与 sqlite datetime() 字符串比较不可靠）
    devices = db.query_all(
        """
        SELECT d.id, d.device_name, d.last_heartbeat,
               u.id AS user_id, u.name AS user_name, u.employee_no, u.team
        FROM devices d
        JOIN users u ON u.id = d.user_id
        WHERE d.status = 'active' AND COALESCE(d.reporting_paused, 0) = 0
        ORDER BY d.last_heartbeat
        """
    )
    offline_devices = [
        {
            "device_id": row["id"],
            "device_name": row["device_name"],
            "user_id": row["user_id"],
            "user_name": row["user_name"],
            "employee_no": row["employee_no"],
            "team": row["team"],
            "last_heartbeat": row["last_heartbeat"],
        }
        for row in devices
        if not is_online(row["last_heartbeat"])
    ]

    # 趋势：近 30 天逐日补零（驾驶舱时间轴连续）
    trend_rows = db.query_all(
        """
        SELECT ur.stat_date AS d,
               COALESCE(SUM(ur.prompt_tokens + ur.completion_tokens
                            + ur.cache_read_tokens + ur.cache_write_tokens), 0) AS t
        FROM usage_report ur
        WHERE ur.stat_date >= ?
        GROUP BY ur.stat_date
        """,
        (window_start,),
    )
    by_day = {row["d"]: row["t"] for row in trend_rows}
    trend = [
        {"date": day, "total_tokens": by_day.get(day, 0)}
        for day in (
            (today - timedelta(days=TREND_WINDOW_DAYS - 1) + timedelta(days=i)).isoformat()
            for i in range(TREND_WINDOW_DAYS)
        )
    ]

    # 部门 Top 榜：近 30 天按科室快照聚合
    team_rows = db.query_all(
        f"""
        SELECT COALESCE(NULLIF(ur.team, ''), '未指定科室') AS team,
               COALESCE(SUM(ur.prompt_tokens + ur.completion_tokens
                            + ur.cache_read_tokens + ur.cache_write_tokens), 0) AS total_tokens
        FROM usage_report ur
        WHERE ur.stat_date >= ?
        GROUP BY ur.team
        ORDER BY total_tokens DESC
        LIMIT {TEAM_TOP_LIMIT}
        """,
        (window_start,),
    )

    return {
        "agents_total": agents_total,
        "agents_active_30d": agents_active_30d,
        "month_tokens": month_tokens,
        "employees_active_30d": employees_active_30d,
        "offline_devices": offline_devices,
        "trend": trend,
        "team_top": [dict(row) for row in team_rows],
    }
