# -*- coding: utf-8 -*-
"""心跳采集器（SPEC 3.4 ①）：设备/宿主/插件状态快照（纯本机读取，无网络）。

隐私红线（3.4）：心跳不含任何内容类字段，只有标识、版本、计数与开关。
"""

from __future__ import annotations

import platform
from datetime import UTC, datetime
from importlib import metadata

from qwenpaw.plugins import PluginContext

import config
from binding import get_binding


def _host_version() -> str | None:
    """宿主 QwenPaw 版本（包元数据；未以发行包安装时返回 None）。"""
    try:
        return metadata.version("qwenpaw")
    except metadata.PackageNotFoundError:
        return None


async def _reporting_paused(context: PluginContext) -> bool:
    """员工「暂停本机上报」开关（3.4 隐私红线；缺省关闭 = 正常上报）。"""
    state = await context.storage.aread_json(config.REPORTING_PAUSED_FILE, {})
    return bool(state.get("paused", False))


async def collect_heartbeat(context: PluginContext) -> dict:
    """采集心跳快照（8.1 device 段 8 字段，3.4 ①全字段）。"""
    uptime_hours: float | None = None
    if config.ACTIVATED_AT is not None:
        delta = datetime.now(UTC) - config.ACTIVATED_AT
        uptime_hours = round(delta.total_seconds() / 3600, 2)

    binding = await get_binding(context)
    return {
        "name": platform.node() or None,
        "os": platform.platform() or None,
        "client_version": _host_version(),
        "plugin_version": config.PLUGIN_VERSION,
        "uptime_hours": uptime_hours,
        "binding_status": "ok" if binding is not None else "unbound",
        # 本地数据格式探测（T1.6 台账扫描本地数据时填充；None 不覆盖服务端旧值）
        "format_probe": None,
        "reporting_paused": await _reporting_paused(context),
    }
