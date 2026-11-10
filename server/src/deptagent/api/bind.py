"""绑定端点（SPEC 8.2：/api/v1/bind，IP 限速 10 次/分钟）。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..core.bind import BindInput, bind_device
from ..core.errors import ApiError
from .deps import DbDep

router = APIRouter(prefix="/api/v1", tags=["bind"])


class DeviceInfo(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    os: str | None = Field(default=None, max_length=128)
    client_version: str | None = Field(default=None, max_length=64)


class BindRequest(BaseModel):
    invite_code: str = Field(min_length=1, max_length=128)
    employee_no: str = Field(min_length=1, max_length=64)
    name: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    device_info: DeviceInfo = Field(default_factory=DeviceInfo)


class BindResponse(BaseModel):
    device_token: str  # 明文仅此一次（SPEC 10.1）
    server_config: dict


@router.post("/bind", response_model=BindResponse)
def bind(body: BindRequest, request: Request, db: DbDep) -> BindResponse:
    limiter = request.app.state.bind_limiter
    client_ip = request.client.host if request.client else "unknown"
    # 成功与失败都计数（防枚举：失败请求同样占窗口，SPEC 10.1）
    wait = limiter.check(client_ip)
    if wait > 0:
        # 8.5 枚举为"常用"非穷尽：限速补充 rate_limited（429）
        raise ApiError(
            429,
            "rate_limited",
            "绑定请求过于频繁，请稍后再试",
            {"retry_after_seconds": int(wait) + 1},
        )

    result = bind_device(
        db,
        BindInput(
            invite_code=body.invite_code,
            employee_no=body.employee_no,
            name=body.name,
            password=body.password,
            device_name=body.device_info.name,
            os=body.device_info.os,
            client_version=body.device_info.client_version,
        ),
    )
    return BindResponse(
        device_token=result.device_token, server_config=result.server_config
    )
