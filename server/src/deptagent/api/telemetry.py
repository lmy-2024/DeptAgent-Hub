"""遥测上报端点（SPEC 8.1：/api/v1/telemetry/report）。

T1.4 骨架范围：Bearer 设备令牌鉴权 + seq 水位防重放（409 seq_conflict
整包拒绝）+ 8.5 统一错误格式；device/agents/usage 三段的入库随
T1.5–T1.7 逐链交付（竖切纪律：每条链 = 采集 → 端点 → UPSERT → 落库）。
报文校验宽松（8.1：版本独立演进、宽松校验——未知字段忽略、计数缺省 0）。
"""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field

from ..core.bind import SERVER_REPORT_INTERVALS_SEC, verify_device_token
from ..core.errors import ApiError
from ..core.utc import utc_now_iso
from .deps import DbDep

router = APIRouter(prefix="/api/v1/telemetry", tags=["telemetry"])

PLUGIN_LATEST = "0.1.0"  # 版本推送（8.1 plugin_latest；系统设置页阶段 2 可配）


class DevicePayload(BaseModel):
    """心跳载荷（3.4 ①字段；T1.5 接入库）。"""

    model_config = {"extra": "ignore"}

    name: str | None = None
    os: str | None = None
    client_version: str | None = None
    plugin_version: str | None = None
    uptime_hours: float | None = None
    binding_status: str | None = None
    format_probe: str | None = None
    reporting_paused: bool | None = None


class AgentPayload(BaseModel):
    model_config = {"extra": "ignore"}

    agent_key: str = Field(min_length=1, max_length=256)
    name: str | None = None
    description: str | None = None
    status: str | None = None


class UsagePayload(BaseModel):
    model_config = {"extra": "ignore"}

    stat_date: str = Field(min_length=10, max_length=10)  # 员工本地日期（1.5）
    agent_key: str | None = None  # 可空：无归属 → agent_id=0 哨兵（8.1）
    provider_id: str | None = None
    model: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    call_count: int = 0


class ReportRequest(BaseModel):
    model_config = {"extra": "ignore"}

    device: DevicePayload = Field(default_factory=DevicePayload)
    seq: int = Field(ge=0)
    agents: list[AgentPayload] = Field(default_factory=list)
    usage: list[UsagePayload] = Field(default_factory=list)


class ReportResponse(BaseModel):
    plugin_latest: str
    server_config: dict


def device_token_dep(
    db: DbDep,
    authorization: str | None = Header(default=None),
) -> sqlite3.Row:
    """Bearer 设备令牌鉴权（8.1）→ devices 行（含 user_id/last_seq 水位）。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise ApiError(401, "token_invalid", "缺少设备令牌")
    token = authorization.removeprefix("Bearer ").strip()
    return verify_device_token(db, token)


DeviceToken = Annotated[sqlite3.Row, Depends(device_token_dep)]


@router.post("/report", response_model=ReportResponse)
def report(
    body: ReportRequest,
    request: Request,
    db: DbDep,
    device: DeviceToken,
) -> ReportResponse:
    """遥测上报（8.1）：鉴权 → seq 防重放 → 三段入库（T1.5–T1.7 逐链）→ 响应。"""
    # seq 水位防重放：seq <= devices.last_seq 整包拒绝（409 seq_conflict）。
    # 水位推进与后续入库同事务（CAS：WHERE last_seq < ? 防并发重复受理）。
    with db.write_transaction() as conn:
        advanced = conn.execute(
            "UPDATE devices SET last_seq = ? WHERE id = ? AND last_seq < ?",
            (body.seq, device["id"], body.seq),
        )
        if advanced.rowcount != 1:
            raise ApiError(
                409,
                "seq_conflict",
                "上报序号重复或倒退，整包拒绝（防重放）",
                {"last_seq": device["last_seq"], "seq": body.seq},
            )

        # ---- 三通道入库（T1.5 heartbeat / T1.6 agents / T1.7 usage 逐链接入）----
        _store_heartbeat(conn, device, body.device)
        _store_agents(conn, device, body.agents)
        _store_usage(conn, device, body.usage)

    return ReportResponse(
        plugin_latest=PLUGIN_LATEST,
        server_config={"report_intervals_sec": SERVER_REPORT_INTERVALS_SEC},
    )


def _store_heartbeat(
    conn: sqlite3.Connection, device: sqlite3.Row, payload: DevicePayload
) -> None:
    """心跳入库（T1.5：7.1 devices 白名单 8 字段中的 7 列 + last_heartbeat）。

    宽松校验语义（8.1）：None 字段不覆盖已有值（COALESCE）——旧版插件
    缺字段时服务端数据不回退；last_seq 由端点主流程的 CAS 推进负责。
    uptime_hours / binding_status 为端点侧展示字段，7 章 devices 无对应列
    不落库（4.3 台账在线状态由 last_heartbeat 推导）。
    """
    conn.execute(
        """
        UPDATE devices SET
            device_name = COALESCE(?, device_name),
            os = COALESCE(?, os),
            client_version = COALESCE(?, client_version),
            plugin_version = COALESCE(?, plugin_version),
            last_format_probe = COALESCE(?, last_format_probe),
            reporting_paused = COALESCE(?, reporting_paused),
            last_heartbeat = ?
        WHERE id = ?
        """,
        (
            payload.name,
            payload.os,
            payload.client_version,
            payload.plugin_version,
            payload.format_probe,
            payload.reporting_paused,  # bool → SQLite INTEGER；None 保持原值
            utc_now_iso(),
            device["id"],
        ),
    )


def _store_agents(
    conn: sqlite3.Connection, device: sqlite3.Row, agents: list[AgentPayload]
) -> None:
    """台账入库（T1.6：8.1 归属语义 + 7.1 UPSERT 白名单）。

    - 归属：客户端不自报 owner/maintainer——owner_user_id 按上报设备令牌
      对应员工登记（首次上报该 agent_key 的用户，UNIQUE(owner, key)
      保证后续同设备/同人重报不迁移归属）；维护人默认同创建人（5.3）；
    - 白名单：客户端只可更新 name / description / last_seen_at；
      status 仅 INSERT 首写 'new'（确认/归档/封停全在管理端，blocked
      不被任何客户端上报覆盖）；definition_key / category / tags /
      shared / maintainer 不受客户端影响；payload.status 为客户端本地
      启停参考信息，不落库；
    - 宽松语义：name/description 为 None 时不覆盖旧值（name NOT NULL
      由 agent_key 兜底）；last_seen_at 取服务器时刻（10.1）。
    """
    owner_id = device["user_id"]
    if owner_id is None:
        return  # 绑定流程保证设备归属员工；防御分支（无归属不落台账）
    now = utc_now_iso()
    for agent in agents:
        conn.execute(
            """
            INSERT INTO agents (
                agent_key, owner_user_id, maintainer_user_id,
                name, description, status, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, COALESCE(?, ?), ?, 'new', ?, ?)
            ON CONFLICT(owner_user_id, agent_key) DO UPDATE SET
                name = COALESCE(excluded.name, agents.name),
                description = COALESCE(excluded.description, agents.description),
                last_seen_at = excluded.last_seen_at
            """,
            (
                agent.agent_key,
                owner_id,
                owner_id,
                agent.name,
                agent.agent_key,
                agent.description,
                now,
                now,
            ),
        )


def _store_usage(
    conn: sqlite3.Connection, device: sqlite3.Row, usage: list[UsagePayload]
) -> None:
    """用量入库（T1.7 交付：增量重传 + usage_daily UPSERT）。"""
    _ = conn, device, usage
