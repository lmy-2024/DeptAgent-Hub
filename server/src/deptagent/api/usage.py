"""用量分析端点（SPEC 4.2 / 7.2 / 8.5：T1.11，lead 门槛）。

四维（人/智能体/模型/科室）× 日/周/月聚合 + CSV 导出（BOM + CRLF）；
数据源一律 usage_report VIEW（7.2，禁止直查 usage_daily）。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel

from ..core import usage as service
from ..core.errors import ApiError
from .deps import DbDep, LeadUser

router = APIRouter(prefix="/api/v1/admin/usage", tags=["usage"])


class UsageBucket(BaseModel):
    bucket: str
    total_tokens: int
    call_count: int


class UsageSeriesItem(BaseModel):
    """聚合成员（key=维度键，label=展示名）；series 本身即排行榜。"""

    key: str
    label: str
    total_tokens: int
    call_count: int
    buckets: list[UsageBucket]


class UsageAggregateResponse(BaseModel):
    dimension: str
    granularity: str
    from_date: str
    to_date: str
    series: list[UsageSeriesItem]


def _resolve_range(from_date: date | None, to_date: date | None) -> tuple[date, date]:
    """日期窗口解析：缺省最近 30 天（to=今天）；from > to 拒绝。"""
    end = to_date or date.today()
    start = from_date or end - timedelta(days=service.DEFAULT_WINDOW_DAYS - 1)
    if start > end:
        raise ApiError(422, "validation_error", "开始日期不能晚于结束日期")
    return start, end


@router.get("/aggregate", response_model=UsageAggregateResponse)
def get_usage_aggregate(
    user: LeadUser,
    db: DbDep,
    # 内联 Literal：B008 豁免（ruff 对 Query 调用的豁免不解析模块级别名，T1.10 坑）
    dimension: Literal["employee", "agent", "model", "team"] = Query(default="employee"),
    granularity: Literal["day", "week", "month"] = Query(default="day"),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
) -> UsageAggregateResponse:
    start, end = _resolve_range(from_date, to_date)
    return UsageAggregateResponse(
        **service.aggregate_usage(
            db, dimension=dimension, granularity=granularity, from_date=start, to_date=end
        )
    )


@router.get("/export")
def export_usage_csv(
    user: LeadUser,
    db: DbDep,
    dimension: Literal["employee", "agent", "model", "team"] = Query(default="employee"),
    granularity: Literal["day", "week", "month"] = Query(default="day"),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
) -> Response:
    """CSV 导出（SPEC 8.5：UTF-8 with BOM + CRLF；宽表 = 聚合同口径）。"""
    start, end = _resolve_range(from_date, to_date)
    aggregate = service.aggregate_usage(
        db, dimension=dimension, granularity=granularity, from_date=start, to_date=end
    )
    filename, content = service.build_usage_csv(aggregate)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
