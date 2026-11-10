# -*- coding: utf-8 -*-
"""统一上报器（SPEC 3.7/8.1）：seq 自增 → POST /api/v1/telemetry/report。

容错与降级链（3.7 渐进交付）：
- 401 token_revoked / token_invalid → 红灯停报：写 telemetry_status 的
  upload_state=revoked/invalid；通道循环每轮检查后直接跳过（循环存活），
  重新绑定（3.8 面板 clear + bind）自动恢复上报；
- 409 seq_conflict → 本地序号与服务端失同步：按服务端 last_seq 重置
  本地序号，下轮以正确序号重新上报；
- 网络失败 / HTTP 5xx → 可重试失败：本轮放弃等下个周期（离线队列
  增强留 T1.8+）。

seq 纪律（8.1 防重放配合）：三通道共用一个设备级递增序号，读-改-写
由 asyncio.Lock 串行化（插件单事件循环；跳号安全——服务端只要求
seq 严格递增，跳号不会被拒）。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
from qwenpaw.plugins import PluginContext

from binding import get_binding
from config import REPORTING_PAUSED_FILE, STORAGE_FILES

REPORT_TIMEOUT_SECONDS = 10

# 红灯状态值（telemetry_status.upload_state；3.8 面板信号灯数据源）
STOPPED_STATES = ("revoked", "invalid")

_SEQ_LOCK = asyncio.Lock()


class UploadStopped(Exception):
    """上报已停止（令牌吊销/失效）：等待重新绑定，重试无意义。"""


class UploadRetryable(Exception):
    """可重试失败（网络/5xx/seq 冲突重置）：下个周期自动重试。"""


async def reporting_stopped(context: PluginContext) -> bool:
    """红灯检查（3.7 吊销停报）：uploader 在 401 时写入停止状态。"""
    status = await context.storage.aread_json(STORAGE_FILES["telemetry_status"], {})
    return status.get("upload_state") in STOPPED_STATES


async def employee_paused(context: PluginContext) -> bool:
    """员工「暂停本机上报」开关（3.4 隐私红线；缺省关闭 = 正常上报）。

    语义：台账/用量通道停发，心跳继续（携带开关状态上报，服务端
    devices.reporting_paused 置位，驾驶舱离线告警排除，3.4）。
    """
    state = await context.storage.aread_json(REPORTING_PAUSED_FILE, {})
    return bool(state.get("paused", False)) if isinstance(state, dict) else False


async def send_report(
    context: PluginContext,
    *,
    device: dict,
    agents: list,
    usage: list,
) -> dict:
    """组装 seq 并 POST 一次上报（8.1）；成功返回服务端响应体。

    未绑定 → UploadRetryable（防御性；调度器在未绑定时本不发送）。
    """
    binding = await get_binding(context)
    if binding is None:
        raise UploadRetryable("尚未绑定设备，跳过本轮上报")

    seq = await _next_seq(context)
    body = {"device": device, "seq": seq, "agents": agents, "usage": usage}
    url = f"{binding['server_url']}/api/v1/telemetry/report"
    headers = {"Authorization": f"Bearer {binding['device_token']}"}

    try:
        async with httpx.AsyncClient(timeout=REPORT_TIMEOUT_SECONDS) as http:
            resp = await http.post(url, json=body, headers=headers)
    except httpx.HTTPError as exc:
        await _update_status(context, upload_state="error", detail=f"network_error: {exc}")
        raise UploadRetryable(f"上报网络失败：{exc}") from None

    if resp.status_code == 200:
        data = resp.json()
        server_config = data.get("server_config") if isinstance(data, dict) else None
        await _update_status(
            context,
            upload_state="ok",
            detail=None,
            last_ok=datetime.now(UTC).isoformat(timespec="seconds"),
            server_config=server_config,
        )
        return data

    error = _error_of(resp)

    if resp.status_code == 401:
        # 吊销（token_revoked）/失效（token_invalid 等）：重试永远 401，
        # 红灯停报等重新绑定（3.7；3.11 第 5 条）
        state = "revoked" if error.get("code") == "token_revoked" else "invalid"
        message = error.get("message") or "设备令牌已失效，上报停止"
        await _update_status(context, upload_state=state, detail=message)
        raise UploadStopped(message)

    if resp.status_code == 409:
        # seq 失同步（8.5）：按服务端 last_seq 重置本地序号，下轮重报
        detail = error.get("detail") or {}
        last_seq = detail.get("last_seq")
        if isinstance(last_seq, int):
            await _write_seq(context, last_seq)
        await _update_status(
            context, upload_state="error", detail="seq_conflict（已按服务端水位重置本地序号）"
        )
        raise UploadRetryable("上报序号冲突，已重置本地序号，下轮重报")

    await _update_status(
        context,
        upload_state="error",
        detail=f"http_{resp.status_code}: {error.get('message', '')}",
    )
    raise UploadRetryable(f"上报失败（HTTP {resp.status_code}）")


async def _next_seq(context: PluginContext) -> int:
    """取下一个设备级序号（读-改-写加锁，防三通道交错产生重复号）。"""
    async with _SEQ_LOCK:
        state = await context.storage.aread_json(STORAGE_FILES["seq"], {})
        seq = int(state.get("seq", 0)) + 1
        await context.storage.awrite_json(STORAGE_FILES["seq"], {"seq": seq})
    return seq


async def _write_seq(context: PluginContext, seq: int) -> None:
    """重置本地序号（409 后按服务端水位对齐）。"""
    async with _SEQ_LOCK:
        await context.storage.awrite_json(STORAGE_FILES["seq"], {"seq": seq})


async def _update_status(context: PluginContext, **fields: object) -> None:
    """更新 telemetry_status.json（3.8 面板信号灯数据源，原子写）。"""
    status = await context.storage.aread_json(STORAGE_FILES["telemetry_status"], {})
    status.update(fields)
    status["updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    await context.storage.awrite_json(STORAGE_FILES["telemetry_status"], status)


def _error_of(resp: httpx.Response) -> dict:
    """解析 8.5 统一错误体 {error: {code, message, detail}}；解析异常容错。"""
    try:
        err = resp.json().get("error")
        if isinstance(err, dict):
            return err
    except ValueError:
        pass
    return {}
