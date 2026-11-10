"""驾驶舱端点（SPEC 4.2：T1.12 总览页，lead 门槛）。"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..core import dashboard as service
from .deps import DbDep, LeadUser

router = APIRouter(prefix="/api/v1/admin/dashboard", tags=["dashboard"])


class OfflineDevice(BaseModel):
    """离线设备告警条目（4.2：排除 reporting_paused=1，主动暂停 ≠ 离线）。"""

    device_id: int
    device_name: str | None
    user_id: int
    user_name: str
    employee_no: str
    team: str | None
    last_heartbeat: str | None


class TrendPoint(BaseModel):
    date: str
    total_tokens: int


class TeamTopItem(BaseModel):
    team: str
    total_tokens: int


class DashboardResponse(BaseModel):
    """KPI 四卡 + 离线告警 + 趋势 + 部门 Top（4.2；成本折算留阶段 2）。"""

    agents_total: int
    agents_active_30d: int
    month_tokens: int
    employees_active_30d: int
    offline_devices: list[OfflineDevice]
    trend: list[TrendPoint]
    team_top: list[TeamTopItem]


@router.get("", response_model=DashboardResponse)
def get_dashboard(user: LeadUser, db: DbDep) -> DashboardResponse:
    return DashboardResponse(**service.get_dashboard(db))
