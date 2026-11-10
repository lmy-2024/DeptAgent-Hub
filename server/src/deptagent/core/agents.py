"""智能体台账查询服务（SPEC 4.2 / 5.3：T1.10，只读视角）。

- 列表六列（4.2：名称/功能描述/创建人/维护人/状态/所属科室）+ 筛选
  （状态 / 创建人科室 / 关键词）+ 8.5 分页排序白名单；附加累计
  Token（5.3 台账口径，usage_report 汇总）；
- 详情抽屉数据源：全字段 + 用量按日序列（usage_report，最近 90 天，
  4.2 抽屉"用量曲线"）+ 变更时间线节点（4.2 抽屉"变更时间线"——
  阶段 1 无独立历史表，取首次发现 / 最近上报 / 状态与用量首末节点）；
- 管理治理动作（确认/补录/归并/改派/归档/封停，5.3）留后续任务
  交付——阶段 1 台账页为只读，new 标记提醒确认即可。
"""

from __future__ import annotations

from ..storage.database import Database
from .errors import ApiError

AGENT_STATUSES = ("new", "active", "archived", "blocked")

# 排序白名单（8.5）：默认 -last_seen_at（最近上报在前）
AGENT_SORTS = {
    "last_seen_at": "a.last_seen_at ASC, a.id ASC",
    "-last_seen_at": "a.last_seen_at DESC, a.id DESC",
    "name": "a.name ASC, a.id ASC",
    "-name": "a.name DESC, a.id DESC",
    "status": "a.status ASC, a.id ASC",
    "-status": "a.status DESC, a.id DESC",
    "first_seen_at": "a.first_seen_at ASC, a.id ASC",
    "-first_seen_at": "a.first_seen_at DESC, a.id DESC",
}

USAGE_WINDOW_DAYS = 90


def list_agents(
    db: Database,
    *,
    page: int,
    page_size: int,
    sort: str,
    status: str | None,
    team: str | None,
    q: str | None,
) -> dict:
    """台账列表（4.2 六列 + 5.3 累计 Token；归属信息经 owner JOIN 取出）。"""
    if sort not in AGENT_SORTS:
        raise ApiError(
            422,
            "validation_error",
            "不支持的排序字段",
            {"sort": sort, "allowed": sorted(AGENT_SORTS)},
        )

    where: list[str] = []
    params: list[object] = []
    if status:
        where.append("a.status = ?")
        params.append(status)
    if team:
        where.append("ou.team = ?")
        params.append(team)
    if q:
        where.append("(a.name LIKE ? OR COALESCE(a.description, '') LIKE ? OR a.agent_key LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])
    cond = f"WHERE {' AND '.join(where)}" if where else ""

    total = db.query_one(
        f"""
        SELECT COUNT(*) AS n
        FROM agents a JOIN users ou ON ou.id = a.owner_user_id
        {cond}
        """,
        params,
    )["n"]
    rows = db.query_all(
        f"""
        SELECT a.id, a.agent_key, a.name, a.description, a.status, a.shared,
               a.category, a.tags, a.definition_key,
               a.first_seen_at, a.last_seen_at,
               ou.id AS owner_user_id, ou.name AS owner_name,
               ou.employee_no AS owner_employee_no, ou.team AS team,
               mu.id AS maintainer_user_id, mu.name AS maintainer_name,
               mu.employee_no AS maintainer_employee_no,
               (SELECT COALESCE(SUM(prompt_tokens + completion_tokens
                        + cache_read_tokens + cache_write_tokens), 0)
                FROM usage_report WHERE agent_id = a.id) AS total_tokens
        FROM agents a
        JOIN users ou ON ou.id = a.owner_user_id
        LEFT JOIN users mu ON mu.id = a.maintainer_user_id
        {cond}
        ORDER BY {AGENT_SORTS[sort]}
        LIMIT ? OFFSET ?
        """,
        [*params, page_size, (page - 1) * page_size],
    )
    return {
        "items": [dict(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_agent_detail(db: Database, agent_id: int) -> dict:
    """详情抽屉数据：全字段 + 按日用量序列（最近 90 天）+ 时间线节点。

    用量一律查 usage_report VIEW（7.2：报表禁直查 usage_daily）。
    """
    row = db.query_one(
        """
        SELECT a.id, a.agent_key, a.name, a.description, a.status, a.shared,
               a.category, a.tags, a.definition_key,
               a.first_seen_at, a.last_seen_at,
               ou.id AS owner_user_id, ou.name AS owner_name,
               ou.employee_no AS owner_employee_no, ou.team AS team,
               mu.id AS maintainer_user_id, mu.name AS maintainer_name,
               mu.employee_no AS maintainer_employee_no
        FROM agents a
        JOIN users ou ON ou.id = a.owner_user_id
        LEFT JOIN users mu ON mu.id = a.maintainer_user_id
        WHERE a.id = ?
        """,
        (agent_id,),
    )
    if row is None:
        raise ApiError(404, "not_found", "智能体不存在", {"agent_id": agent_id})

    usage = db.query_all(
        """
        SELECT stat_date,
               SUM(prompt_tokens) AS prompt_tokens,
               SUM(completion_tokens) AS completion_tokens,
               SUM(cache_read_tokens) AS cache_read_tokens,
               SUM(cache_write_tokens) AS cache_write_tokens,
               SUM(call_count) AS call_count
        FROM usage_report
        WHERE agent_id = ? AND stat_date >= DATE('now', ?)
        GROUP BY stat_date
        ORDER BY stat_date
        """,
        (agent_id, f"-{USAGE_WINDOW_DAYS} days"),
    )
    usage_series = [{**dict(u), "total_tokens": _sum_tokens(u)} for u in usage]
    lifetime = db.query_one(
        """
        SELECT COALESCE(SUM(prompt_tokens + completion_tokens
                 + cache_read_tokens + cache_write_tokens), 0) AS total_tokens,
               COALESCE(SUM(call_count), 0) AS call_count,
               COUNT(*) AS days
        FROM usage_report WHERE agent_id = ?
        """,
        (agent_id,),
    )

    detail = dict(row)
    detail["usage_series"] = usage_series
    detail["usage_summary"] = dict(lifetime)
    detail["timeline"] = _timeline(row, usage_series)
    return detail


def _sum_tokens(usage_row: dict) -> int:
    return (
        (usage_row["prompt_tokens"] or 0)
        + (usage_row["completion_tokens"] or 0)
        + (usage_row["cache_read_tokens"] or 0)
        + (usage_row["cache_write_tokens"] or 0)
    )


def _timeline(row, usage_series: list[dict]) -> list[dict]:
    """变更时间线节点（阶段 1 快照口径；独立历史表留后续）。"""
    events: list[dict] = []
    if row["first_seen_at"]:
        events.append(
            {
                "at": row["first_seen_at"],
                "event": "discovered",
                "label": f"首次发现（登记为 {row['status']}）",
            }
        )
    if usage_series:
        events.append(
            {
                "at": usage_series[0]["stat_date"],
                "event": "first_usage",
                "label": "首笔用量上报",
            }
        )
        events.append(
            {
                "at": usage_series[-1]["stat_date"],
                "event": "last_usage",
                "label": "最近用量上报",
            }
        )
    if row["last_seen_at"]:
        events.append({"at": row["last_seen_at"], "event": "last_seen", "label": "最近上报心跳"})
    events.sort(key=lambda e: e["at"] or "")
    return events
