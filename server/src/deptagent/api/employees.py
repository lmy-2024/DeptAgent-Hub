"""员工与设备管理端点（SPEC 4.2 / 5.2 / 8.5：T1.9，admin 门槛）。

阶段 1 交付：员工列表（聚合 + 心跳灯）、邀请码生成与列表、
设备子表查询、设备令牌吊销；批量开码 / 审批队列留阶段 2（4.2）。
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from ..core import employees as service
from .deps import AdminUser, DbDep

router = APIRouter(prefix="/api/v1/admin", tags=["employees"])


class CreateInvitationRequest(BaseModel):
    team: str | None = Field(default=None, max_length=64)
    role: Literal["member", "lead"]  # admin+ 不经邀请码（SPEC 5.2）
    expires_hours: int = Field(default=service.DEFAULT_INVITE_HOURS, ge=1, le=720)


class InvitationItem(BaseModel):
    code: str
    team: str | None
    role: str | None
    expires_at: str | None
    used_by: int | None
    used_at: str | None


class InvitationListResponse(BaseModel):
    items: list[InvitationItem]


class RevokeResultResponse(BaseModel):
    device_id: int
    status: str
    message: str


class EmployeeItem(BaseModel):
    id: int
    employee_no: str
    name: str
    display_name: str | None
    role: str
    team: str | None
    status: str
    created_at: str | None
    device_count: int
    device_active_count: int
    last_heartbeat: str | None
    online: bool
    reporting_paused_any: int


class EmployeeListResponse(BaseModel):
    """8.5 分页响应：{items, total, page, page_size}。"""

    items: list[EmployeeItem]
    total: int
    page: int
    page_size: int


class DeviceItem(BaseModel):
    id: int
    device_name: str | None
    os: str | None
    client_version: str | None
    plugin_version: str | None
    status: str
    reporting_paused: int | None
    last_seq: int
    last_format_probe: str | None
    last_heartbeat: str | None
    created_at: str | None
    online: bool


class DeviceListResponse(BaseModel):
    items: list[DeviceItem]


@router.get("/employees", response_model=EmployeeListResponse)
def list_employees(
    user: AdminUser,
    db: DbDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    sort: str = Query(default="-created_at"),
    team: str | None = Query(default=None, max_length=64),
    q: str | None = Query(default=None, max_length=64),
) -> EmployeeListResponse:
    return EmployeeListResponse(
        **service.list_employees(db, page=page, page_size=page_size, sort=sort, team=team, q=q)
    )


@router.post(
    "/invitations",
    response_model=InvitationItem,
    status_code=status.HTTP_201_CREATED,
)
def create_invitation(body: CreateInvitationRequest, user: AdminUser, db: DbDep) -> InvitationItem:
    return InvitationItem(
        **service.create_invitation(
            db,
            actor=user,
            team=body.team,
            role=body.role,
            expires_hours=body.expires_hours,
        )
    )


@router.get("/invitations", response_model=InvitationListResponse)
def list_invitations(user: AdminUser, db: DbDep) -> InvitationListResponse:
    return InvitationListResponse(items=service.list_invitations(db))


@router.get("/employees/{user_id}/devices", response_model=DeviceListResponse)
def list_devices(user_id: int, user: AdminUser, db: DbDep) -> DeviceListResponse:
    return DeviceListResponse(items=service.list_devices(db, user_id=user_id))


@router.post("/devices/{device_id}/revoke", response_model=RevokeResultResponse)
def revoke_device(device_id: int, user: AdminUser, db: DbDep) -> RevokeResultResponse:
    return RevokeResultResponse(**service.revoke_device(db, actor=user, device_id=device_id))
