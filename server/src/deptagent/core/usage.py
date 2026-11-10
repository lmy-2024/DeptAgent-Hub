"""用量聚合服务（SPEC 4.2 / 7.2 / 8.5：T1.11，报表一律走 usage_report VIEW）。

四维（人/智能体/模型/科室）× 日/周/月聚合：返回按成员合计降序的多序列
（每成员含稀疏桶序列，前端补零画图，排行榜即 series 本身）；
CSV 导出宽表（成员 × 桶列 + 合计两列，UTF-8 BOM + CRLF，SPEC 8.5）。
成本折算列留阶段 2（4.2"成本折算 2"）。
"""

from __future__ import annotations

import csv
import io
from datetime import date

from ..storage.database import Database

DIMENSIONS = ("employee", "agent", "model", "team")
GRANULARITIES = ("day", "week", "month")
DEFAULT_WINDOW_DAYS = 30

# 时间桶表达式（granularity → SQL；week 归一到周一日期，Excel/前端可直接当轴）
_BUCKET_EXPRS = {
    "day": "ur.stat_date",
    "week": "date(ur.stat_date, '-' || ((strftime('%w', ur.stat_date) + 6) % 7) || ' days')",
    "month": "strftime('%Y-%m', ur.stat_date)",
}

# 维度 SQL 片段（dimension → 维度键 / JOIN / label / GROUP BY 列）。
# 仅白名单取值（API 层 Literal 422 兜底），无拼接注入面。
_DIMENSION_SQL = {
    "employee": {
        "key": "ur.user_id",
        "label": "u.name || '（' || u.employee_no || '）'",
        "join": "JOIN users u ON u.id = ur.user_id",
        "group": "ur.user_id, u.name, u.employee_no",
    },
    "agent": {
        "key": "ur.agent_id",
        # agent_id=0 哨兵 / NULL（未归属用量，8.1）→ 统一 label
        "label": (
            "CASE WHEN a.id IS NULL THEN '未归属智能体' "
            "ELSE a.name || '（' || a.agent_key || '）' END"
        ),
        "join": "LEFT JOIN agents a ON a.id = ur.agent_id",
        "group": "ur.agent_id, a.name, a.agent_key",
    },
    "model": {
        "key": "COALESCE(ur.provider_id, '') || ':' || COALESCE(ur.model, '')",
        "label": (
            "COALESCE(NULLIF(ur.provider_id, ''), '?') || '/' "
            "|| COALESCE(NULLIF(ur.model, ''), '?')"
        ),
        "join": "",
        "group": "ur.provider_id, ur.model",
    },
    "team": {
        "key": "COALESCE(ur.team, '')",
        "label": "COALESCE(NULLIF(ur.team, ''), '未指定科室')",
        "join": "",
        "group": "ur.team",
    },
}


def aggregate_usage(
    db: Database,
    *,
    dimension: str,
    granularity: str,
    from_date: date,
    to_date: date,
) -> dict:
    """四维 × 粒度聚合（stat_date 闭区间 [from_date, to_date]）。

    返回 {"dimension", "granularity", "from_date", "to_date", "series"}；
    series 按成员 total_tokens 降序（排行榜），每成员 buckets 按桶升序。
    """
    bucket_expr = _BUCKET_EXPRS[granularity]
    dim = _DIMENSION_SQL[dimension]
    join = f"\n         {dim['join']}" if dim["join"] else ""
    sql = f"""
        SELECT {dim["key"]} AS dim_key, {dim["label"]} AS label,
               {bucket_expr} AS bucket,
               COALESCE(SUM(ur.prompt_tokens + ur.completion_tokens
                            + ur.cache_read_tokens + ur.cache_write_tokens), 0)
                   AS total_tokens,
               COALESCE(SUM(ur.call_count), 0) AS call_count
        FROM usage_report ur{join}
        WHERE ur.stat_date >= ? AND ur.stat_date <= ?
        GROUP BY {dim["group"]}, bucket
        ORDER BY dim_key, bucket
    """
    rows = db.query_all(sql, (from_date.isoformat(), to_date.isoformat()))

    members: dict[str, dict] = {}
    for row in rows:
        key = str(row["dim_key"]) if row["dim_key"] is not None else ""
        member = members.get(key)
        if member is None:
            member = {
                "key": key,
                "label": row["label"],
                "total_tokens": 0,
                "call_count": 0,
                "buckets": [],
            }
            members[key] = member
        member["buckets"].append(
            {
                "bucket": row["bucket"],
                "total_tokens": row["total_tokens"],
                "call_count": row["call_count"],
            }
        )
        member["total_tokens"] += row["total_tokens"]
        member["call_count"] += row["call_count"]

    series = sorted(members.values(), key=lambda m: (-m["total_tokens"], m["key"]))
    for member in series:
        member["buckets"].sort(key=lambda b: b["bucket"])

    return {
        "dimension": dimension,
        "granularity": granularity,
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "series": series,
    }


def build_usage_csv(aggregate: dict) -> tuple[str, str]:
    """聚合结果 → 宽表 CSV（成员 × 桶列 + 合计两列）。

    UTF-8 with BOM + CRLF（SPEC 8.5：Excel 中文兼容）；返回 (文件名, 内容)。
    """
    series = aggregate["series"]
    buckets = sorted({b["bucket"] for member in series for b in member["buckets"]})
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(["成员", *buckets, "合计Token", "调用次数"])
    for member in series:
        by_bucket = {b["bucket"]: b["total_tokens"] for b in member["buckets"]}
        writer.writerow(
            [
                member["label"],
                *[by_bucket.get(bucket, "") for bucket in buckets],
                member["total_tokens"],
                member["call_count"],
            ]
        )
    filename = (
        f"usage-{aggregate['dimension']}-{aggregate['granularity']}"
        f"_{aggregate['from_date']}_{aggregate['to_date']}.csv"
    )
    return filename, "\ufeff" + buf.getvalue()
