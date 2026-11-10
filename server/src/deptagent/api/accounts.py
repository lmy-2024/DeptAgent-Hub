"""账号治理端点（SPEC 8.3：super 专属四端点，全部留痕）。"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from ..core import accounts as service
from .deps import DbDep, SuperUser

router = APIRouter(prefix="/api/v1/admin/accounts", tags=["accounts"])

RoleName = Literal["member", "lead", "admin", "super"]


class CreateAccountRequest(BaseModel):
    employee_no: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    display_name: str | None = Field(default=None, max_length=64)
    role: RoleName
    team: str | None = Field(default=None, max_length=64)
    password: str | None = Field(default=None, min_length=8, max_length=128)


class PasswordOnceResponse(BaseModel):
    """密码明文仅本响应返回一次（SPEC 10.1 一次性凭据风格）。"""

    user_id: int
    employee_no: str
    password: str


class RoleChangeRequest(BaseModel):
    role: RoleName


class ResetPasswordRequest(BaseModel):
    password: str | None = Field(default=None, min_length=8, max_length=128)


class SimpleResultResponse(BaseModel):
    user_id: int
    employee_no: str
    message: str


@router.post("", response_model=PasswordOnceResponse, status_code=status.HTTP_201_CREATED)
def create_account(body: CreateAccountRequest, user: SuperUser, db: DbDep) -> PasswordOnceResponse:
    user_id, password = service.create_account(
        db,
        actor=user,
        employee_no=body.employee_no,
        name=body.name,
        display_name=body.display_name,
        role=body.role,
        team=body.team,
        password=body.password,
    )
    return PasswordOnceResponse(user_id=user_id, employee_no=body.employee_no, password=password)


@router.patch("/{user_id}/role", response_model=SimpleResultResponse)
def change_role(
    user_id: int, body: RoleChangeRequest, user: SuperUser, db: DbDep
) -> SimpleResultResponse:
    service.change_role(db, actor=user, user_id=user_id, new_role=body.role)
    row = db.query_one("SELECT employee_no FROM users WHERE id = ?", (user_id,))
    return SimpleResultResponse(
        user_id=user_id,
        employee_no=row["employee_no"] if row else "",
        message=f"角色已调整为 {body.role}（即时生效）",
    )


@router.post("/{user_id}/reset-password", response_model=PasswordOnceResponse)
def reset_password(
    user_id: int, user: SuperUser, db: DbDep, body: ResetPasswordRequest | None = None
) -> PasswordOnceResponse:
    """空 body 合法：服务端生成随机密码（SPEC 10.1 一次性凭据）。"""
    employee_no, password = service.reset_password(
        db, actor=user, user_id=user_id, password=body.password if body else None
    )
    return PasswordOnceResponse(user_id=user_id, employee_no=employee_no, password=password)


@router.post("/{user_id}/disable", response_model=SimpleResultResponse)
def disable_account(user_id: int, user: SuperUser, db: DbDep) -> SimpleResultResponse:
    employee_no = service.disable_account(db, actor=user, user_id=user_id)
    return SimpleResultResponse(
        user_id=user_id, employee_no=employee_no, message="账号已停用（持有的访问令牌即时失效）"
    )
