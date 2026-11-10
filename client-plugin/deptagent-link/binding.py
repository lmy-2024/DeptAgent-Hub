# -*- coding: utf-8 -*-
"""绑定链路（SPEC 3.5）：输码 → 服务端校验签发设备令牌 → 本地持久化。

令牌存储（源码校准 v0.7，SPEC 3.5）：2.3.0b3 SDK 无插件侧 secrets 写入
API（config 仅只读快照），设备令牌存 context.storage 的 binding.json——
本机威胁域内可接受（令牌仅能上报本人遥测数据、服务端随时吊销）。

绑定成功 → 调度器按"绑定状态存在"在启动首轮立即执行（首次全量上报，
SPEC 3.5；采集器 T1.5–T1.7 交付）。重新绑定（3.8 面板操作）= clear + bind。
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
from qwenpaw.plugins import PluginContext

from config import STORAGE_FILES

BIND_TIMEOUT_SECONDS = 10


class BindError(Exception):
    """绑定失败：携带服务端 8.5 错误 code 与中文 message。"""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


async def bind_device(
    context: PluginContext,
    server_url: str,
    invite_code: str,
    employee_no: str,
    *,
    name: str | None = None,
    password: str | None = None,
    device_name: str | None = None,
    os_name: str | None = None,
    client_version: str | None = None,
) -> dict:
    """输码绑定（8.2 协议）：成功写 binding.json 并返回绑定状态。

    失败抛 BindError（含 invite_invalid / invite_expired / rate_limited 等
    服务端 code）；网络异常归一为 network_error。
    """
    payload = {
        "invite_code": invite_code,
        "employee_no": employee_no,
        "name": name,
        "password": password,
        "device_info": {
            "name": device_name,
            "os": os_name,
            "client_version": client_version,
        },
    }
    url = f"{server_url.rstrip('/')}/api/v1/bind"
    try:
        async with httpx.AsyncClient(timeout=BIND_TIMEOUT_SECONDS) as http:
            resp = await http.post(url, json=payload)
    except httpx.HTTPError as exc:
        raise BindError("network_error", f"无法连接部门智通服务器：{exc}", 0) from None

    if resp.status_code != 200:
        try:
            err = resp.json()["error"]
            raise BindError(
                str(err.get("code", "unknown")),
                str(err.get("message", "绑定失败")),
                resp.status_code,
            )
        except (ValueError, KeyError) as parse_error:
            raise BindError(
                "unknown", f"服务器响应异常（HTTP {resp.status_code}）", resp.status_code
            ) from parse_error

    data = resp.json()
    binding = {
        "server_url": server_url.rstrip("/"),
        "employee_no": employee_no,
        "device_token": data["device_token"],  # 明文仅此一份（SPEC 10.1）
        "server_config": data.get("server_config", {}),
        "bound_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    await context.storage.awrite_json(STORAGE_FILES["binding"], binding)
    context.logger.info(
        "deptagent-link bound",
        fields={"employee_no": employee_no, "server_url": binding["server_url"]},
    )
    return binding


async def get_binding(context: PluginContext) -> dict | None:
    """读取绑定状态；未绑定返回 None（调度器据此决定是否上报）。"""
    return await context.storage.aread_json(STORAGE_FILES["binding"], None)


async def clear_binding(context: PluginContext) -> None:
    """清除绑定（重新绑定第一步；对应 3.8 面板"重新绑定"操作）。

    一并清除红灯状态（telemetry_status）：红灯语义 = 等待重新绑定
    （3.7 吊销停报），不清除会让 reporting_stopped 永久拦截新
    令牌的上报。
    """
    await context.storage.adelete(STORAGE_FILES["binding"])
    await context.storage.adelete(STORAGE_FILES["telemetry_status"])
    context.logger.info("deptagent-link binding cleared")
