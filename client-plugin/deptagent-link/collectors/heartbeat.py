# -*- coding: utf-8 -*-
"""心跳采集器（SPEC 3.4 ①）：设备/宿主/插件状态快照（纯本机读取，无网络）。

隐私红线（3.4）：心跳不含任何内容类字段，只有标识、版本、计数与开关。
"""

from __future__ import annotations

import asyncio
import platform
from datetime import UTC, datetime
from importlib import metadata

from qwenpaw.plugins import PluginContext

import config
from adapters.base import detect_format
from binding import get_binding
from uploader import employee_paused


def _host_version() -> str | None:
    """宿主 QwenPaw 版本（包元数据；未以发行包安装时返回 None）。"""
    try:
        return metadata.version("qwenpaw")
    except metadata.PackageNotFoundError:
        return None


async def collect_heartbeat(context: PluginContext) -> dict:
    """采集心跳快照（8.1 device 段 8 字段，3.4 ①全字段）。"""
    uptime_hours: float | None = None
    if config.ACTIVATED_AT is not None:
        delta = datetime.now(UTC) - config.ACTIVATED_AT
        uptime_hours = round(delta.total_seconds() / 3600, 2)

    binding = await get_binding(context)
    # 格式探测（adapters/base.py）：探测失败 None（服务端 COALESCE 不覆盖旧值，降级留痕）
    fmt, _reader = await asyncio.to_thread(detect_format)
    return {
        "name": platform.node() or None,
        "os": platform.platform() or None,
        "client_version": _host_version(),
        "plugin_version": config.PLUGIN_VERSION,
        "uptime_hours": uptime_hours,
        "binding_status": "ok" if binding is not None else "unbound",
        "format_probe": fmt,
        "reporting_paused": await employee_paused(context),
    }
