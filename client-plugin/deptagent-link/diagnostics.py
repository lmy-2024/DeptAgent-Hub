# -*- coding: utf-8 -*-
"""诊断模块（SPEC 3.2 包结构：diagnostics.py = 自检 / 手动同步 / 诊断导出）。

职责归位（T1.14）：
- self_check：主动健康自检——本地状态检查 + 服务器 /health 可达性探测。
  纯只读（不发遥测、不占 seq、不写水位），CI 冒烟与升级验证流水线
  （3.9：新版宿主起容器装插件跑 check --runtime + 三通道冒烟）消费，
  面板诊断导出不含此项（避免网络等待阻塞 UI）；
- run_manual_sync / SyncBusyError：手动同步统一入口（实现归 scheduler，
  周期循环与手动触发共用同一套通道编排——单一事实源；面板 /sync、
  绑定首次全量上报均走此入口）；
- build_diagnostics：诊断快照导出构造（面板 /diagnostics 薄壳调用；
  不含设备令牌，10.1 明文仅绑定响应一次）。

自检结论口径：verdict ∈ not_bound（未绑定，非故障）/ ok（全部通过）/
degraded（服务器不可达或红灯停报——按 3.7 属正常停报语义，但值得
员工注意：检查网络或重新绑定）。
"""

from __future__ import annotations

import platform
from datetime import UTC, datetime
from importlib import metadata

import httpx
from qwenpaw.plugins import PluginContext

import scheduler
from binding import get_binding
from config import ACTIVATED_AT, PLUGIN_VERSION, REPORTING_PAUSED_FILE, STORAGE_FILES

# 包结构归位（3.2）：手动同步入口统一由本模块导出
from scheduler import SyncBusyError, run_manual_sync  # noqa: F401

from uploader import STOPPED_STATES

# 自检的可达性探测超时（面板外场景，快速失败）
SELF_CHECK_TIMEOUT_SECONDS = 3


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _binding_public(binding: dict | None) -> dict | None:
    """绑定信息对外视图（脱敏：仅工号/服务器/绑定时间，不含令牌）。"""
    if binding is None:
        return None
    return {
        "employee_no": binding.get("employee_no"),
        "server_url": binding.get("server_url"),
        "bound_at": binding.get("bound_at"),
    }


async def self_check(context: PluginContext) -> dict:
    """健康自检：本地状态聚合 + 服务器可达性探测（只读、无副作用）。

    检查项（items）：
    - bound：绑定状态存在；
    - server_reachable：绑定的服务器 /health 可达（未绑定时跳过探测）；
    - token_state：上报令牌状态（ok / 上次失败可重试 / 红灯停报）；
    - watermark_structure：水位文件结构健康（channels 子键 + usage 指纹
      未被旧版本 bug 顶坏）；
    - usage_watermark_days：已提交的按日指纹数（透明展示）。
    """
    items: list[dict] = []

    binding = await get_binding(context)
    items.append(
        {
            "name": "bound",
            "ok": binding is not None,
            "detail": None if binding is not None else "尚未绑定设备",
        }
    )

    if binding is None:
        return {
            "checked_at": _now_iso(),
            "verdict": "not_bound",
            "items": items,
            "binding": None,
        }

    server_url = str(binding.get("server_url") or "").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=SELF_CHECK_TIMEOUT_SECONDS) as http:
            resp = await http.get(f"{server_url}/health")
        reachable = resp.status_code == 200
        detail = f"HTTP {resp.status_code}" if not reachable else None
    except httpx.HTTPError as exc:
        reachable = False
        detail = f"network_error: {exc}"
    items.append({"name": "server_reachable", "ok": reachable, "detail": detail})

    upload = await context.storage.aread_json(STORAGE_FILES["telemetry_status"], {})
    upload_state = upload.get("upload_state") or "idle" if isinstance(upload, dict) else "idle"
    token_ok = upload_state not in STOPPED_STATES
    items.append(
        {
            "name": "token_state",
            "ok": token_ok,
            "detail": (
                None
                if token_ok
                else f"红灯停报（{upload_state}）：等待重新绑定恢复上报"
            ),
        }
    )

    watermark = await context.storage.aread_json(STORAGE_FILES["watermark"], {})
    channels = watermark.get("channels") if isinstance(watermark, dict) else None
    fingerprints = watermark.get("usage") if isinstance(watermark, dict) else None
    # 结构健康 = 两个子键要么缺失（从未运行/未提交，非损坏），要么是 dict；
    # 被旧版本 bug 顶成字符串才是异常。
    structure_ok = (
        (channels is None or isinstance(channels, dict))
        and (fingerprints is None or isinstance(fingerprints, dict))
    )
    items.append(
        {
            "name": "watermark_structure",
            "ok": structure_ok,
            "detail": None if structure_ok else "水位文件结构异常（下轮成功上报后自愈）",
        }
    )
    items.append(
        {
            "name": "usage_watermark_days",
            "ok": True,
            "detail": (
                len(fingerprints) if isinstance(fingerprints, dict) else 0
            ),
        }
    )

    verdict = "ok" if (reachable and token_ok and structure_ok) else "degraded"
    return {
        "checked_at": _now_iso(),
        "verdict": verdict,
        "items": items,
        "binding": _binding_public(binding),
    }


async def build_diagnostics(context: PluginContext) -> dict:
    """诊断快照导出（3.8「导出诊断日志」数据源；不含设备令牌）。

    面板 GET /diagnostics 的构造逻辑；纯本地读取（无网络请求），
    导出内容与 self_check 互补：这里含通道元数据与今日透明数据。
    """
    binding = await get_binding(context)
    upload = await context.storage.aread_json(STORAGE_FILES["telemetry_status"], {})
    watermark = await context.storage.aread_json(STORAGE_FILES["watermark"], {})
    seq = await context.storage.aread_json(STORAGE_FILES["seq"], {})
    today = await context.storage.aread_json(STORAGE_FILES["today_report"], {})
    paused_state = await context.storage.aread_json(REPORTING_PAUSED_FILE, {})

    try:
        qwenpaw_version = metadata.version("qwenpaw")
    except metadata.PackageNotFoundError:
        qwenpaw_version = None

    channels_run = watermark.get("channels", {}) if isinstance(watermark, dict) else {}
    fingerprints = watermark.get("usage") if isinstance(watermark, dict) else None
    return {
        "exported_at": _now_iso(),
        "plugin": {
            "id": "deptagent-link",
            "version": PLUGIN_VERSION,
            "activated_at": (
                ACTIVATED_AT.isoformat() if ACTIVATED_AT is not None else None
            ),
        },
        "host": {
            "os": platform.platform() or None,
            "qwenpaw_version": qwenpaw_version,
        },
        "binding": _binding_public(binding),
        "upload": {
            "state": upload.get("upload_state") or "idle" if isinstance(upload, dict) else "idle",
            "detail": upload.get("detail") if isinstance(upload, dict) else None,
            "last_ok": upload.get("last_ok") if isinstance(upload, dict) else None,
            "seq": seq.get("seq") if isinstance(seq, dict) else None,
        },
        "channels": {
            name: {
                "last_run": (
                    channels_run.get(name) if isinstance(channels_run, dict) else None
                ),
                "interval_min": minutes,
            }
            for name, (_label, minutes) in scheduler.CHANNEL_META.items()
        },
        "usage_watermark_days": (
            len(fingerprints) if isinstance(fingerprints, dict) else 0
        ),
        "paused": bool(
            isinstance(paused_state, dict) and paused_state.get("paused", False)
        ),
        "today": today if isinstance(today, dict) and today.get("date") else None,
    }
