"""智能体台账端点（SPEC 4.2 / 5.3 / 8.5：T1.10，lead 门槛只读）。

阶段 1 交付列表 + 筛选 + 详情抽屉数据源；治理动作（确认/归并/改派/
归档/封停）与 CSV 导出留后续任务（4.2/5.3）。
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ..core import agents as service
from .deps import DbDep, LeadUser

router = APIRouter(prefix="/api/v1/admin/agents", tags=["agents"])


class AgentListItem(BaseModel):
    """六列（4.2）：名称/功能描述/创建人/维护人/状态/所属科室 + 附加。"""

    id: int
    agent_key: str
    name: str
    description: str | None
    status: str
    shared: int
    category: str | None
    tags: str | None
    definition_key: str | None
    first_seen_at: str | None
    last_seen_at: str | None
    owner_user_id: int
    owner_name: str
    owner_employee_no: str
    team: str | None
    maintainer_user_id: int | None
    maintainer_name: str | None
    maintainer_employee_no: str | None
    total_tokens: int


class AgentListResponse(BaseModel):
    """8.5 分页响应：{items, total, page, page_size}。"""

    items: list[AgentListItem]
    total: int
    page: int
    page_size: int


class UsagePoint(BaseModel):
    stat_date: str
    prompt_tokens: int
    completion_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    call_count: int
    total_tokens: int


class UsageSummary(BaseModel):
    total_tokens: int
    call_count: int
    days: int


class TimelineEvent(BaseModel):
    at: str
    event: str
    label: str


class AgentDetailResponse(BaseModel):
    id: int
    agent_key: str
    name: str
    description: str | None
    status: str
    shared: int
    category: str | None
    tags: str | None
    definition_key: str | None
    first_seen_at: str | None
    last_seen_at: str | None
    owner_user_id: int
    owner_name: str
    owner_employee_no: str
    team: str | None
    maintainer_user_id: int | None
    maintainer_name: str | None
    maintainer_employee_no: str | None
    usage_series: list[UsagePoint]
    usage_summary: UsageSummary
    timeline: list[TimelineEvent]


@router.get("", response_model=AgentListResponse)
def list_agents(
    user: LeadUser,
    db: DbDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    sort: str = Query(default="-last_seen_at"),
    # 内联 Literal：B008 豁免（ruff 对 Query 调用的豁免逻辑不解析模块级
    # Literal 别名，内联后 422 校验行为不变）。
    status: Literal["new", "active", "archived", "blocked"] | None = Query(default=None),
    team: str | None = Query(default=None, max_length=64),
    q: str | None = Query(default=None, max_length=64),
) -> AgentListResponse:
    return AgentListResponse(
        **service.list_agents(
            db, page=page, page_size=page_size, sort=sort, status=status, team=team, q=q
        )
    )


@router.get("/{agent_id}", response_model=AgentDetailResponse)
def get_agent(agent_id: int, user: LeadUser, db: DbDep) -> AgentDetailResponse:
    return AgentDetailResponse(**service.get_agent_detail(db, agent_id))
