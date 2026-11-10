# -*- coding: utf-8 -*-
"""员工面板数据层（SPEC 3.8、D8 拍板路径）：PawApp 后端路由。

面板实现为前后端两件独立的事（3.8，不 fork、不改 console 源码）：
- 展示层：ui/index.js bundle（console 经 manifest entry.frontend 动态
  加载并注册路由/菜单，Python 端不画 UI）；
- 数据层：本文件 PawApp 六端点（SDK 公共 API qwenpaw.plugins.apps，
  PUBLIC_API 白名单内），在 main._on_activate 里 paw.register(context)
  注册，最终 URL = /api/deptagent-link/…（前端 host.getApiUrl 拼接）。

handler 闭包引用模块级 _context（on_activate 注入）。不使用路由层
ctx.storage——它是 PawApp scoped 目录（apps/<hash>/），与插件
context.storage 不共享（QwenPaw 源码 plugins/_apps.py scope 实现）。

隐私纪律：device_token 绝不出现在任何响应（10.1 明文仅绑定响应一次）；
/sync 与周期循环同语义（员工暂停跳过台账/用量，红灯停报，3.4/3.7）。
"""

from __future__ import annotations

from datetime import UTC, datetime

from qwenpaw.plugins import PluginContext, StaleContextError
from qwenpaw.plugins.apps import AppContext, HttpRequest, HttpResponse, PawApp

import diagnostics
import scheduler
from binding import BindError, bind_device, clear_binding, get_binding
from config import PLUGIN_VERSION, REPORTING_PAUSED_FILE, STORAGE_FILES

paw = PawApp(name="部门智通面板", app_id="deptagent-link")

# on_activate 注入的插件上下文（handler 闭包引用；未激活时路由未注册）
_context: PluginContext | None = None


def bind_context(context: PluginContext) -> None:
    """注入插件上下文（main._on_activate 调用，先于 paw.register）。"""
    global _context
    _context = context


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _http_error(status: int, code: str, message: str) -> HttpResponse:
    """8.5 风格统一错误体（panel 前端据此展示中文 message）。"""
    return HttpResponse(
        body={"error": {"code": code, "message": message}}, status=status
    )


def _stale() -> HttpResponse:
    return _http_error(503, "plugin_unavailable", "插件已停用，面板暂不可用")


def _binding_public(binding: dict | None) -> dict | None:
    """绑定信息对外视图（脱敏：仅工号/服务器/绑定时间，不含令牌）。"""
    if binding is None:
        return None
    return {
        "employee_no": binding.get("employee_no"),
        "server_url": binding.get("server_url"),
        "bound_at": binding.get("bound_at"),
    }


@paw.route("/status", methods=("GET",))
async def get_status(_ctx: AppContext, _req: HttpRequest) -> dict | HttpResponse:
    """状态卡全量数据（3.8 状态卡 + 3.4 今日已上报内容透明展示）。"""
    if _context is None:
        return _http_error(503, "plugin_unavailable", "插件尚未激活")
    try:
        binding = await get_binding(_context)
        upload = await _context.storage.aread_json(
            STORAGE_FILES["telemetry_status"], {}
        )
        watermark = await _context.storage.aread_json(STORAGE_FILES["watermark"], {})
        today = await _context.storage.aread_json(STORAGE_FILES["today_report"], {})
        paused_state = await _context.storage.aread_json(REPORTING_PAUSED_FILE, {})
    except StaleContextError:
        return _stale()

    channels_run = (
        watermark.get("channels", {}) if isinstance(watermark, dict) else {}
    )
    return {
        "plugin_version": PLUGIN_VERSION,
        "binding": _binding_public(binding),
        "upload": {
            "state": upload.get("upload_state") or "idle",
            "detail": upload.get("detail"),
            "last_ok": upload.get("last_ok"),
            "updated_at": upload.get("updated_at"),
        },
        "channels": [
            {
                "name": name,
                "label": label,
                "interval_min": minutes,
                "last_run": channels_run.get(name) if isinstance(channels_run, dict) else None,
            }
            for name, (label, minutes) in scheduler.CHANNEL_META.items()
        ],
        "paused": bool(
            isinstance(paused_state, dict) and paused_state.get("paused", False)
        ),
        "today": today if isinstance(today, dict) and today.get("date") else None,
    }


@paw.route("/sync", methods=("POST",))
async def post_sync(_ctx: AppContext, _req: HttpRequest) -> dict | HttpResponse:
    """立即同步（3.8 操作）：三通道立即各执行一轮（与周期循环同语义）。"""
    if _context is None:
        return _http_error(503, "plugin_unavailable", "插件尚未激活")
    try:
        results = await diagnostics.run_manual_sync(_context)
    except diagnostics.SyncBusyError:
        return _http_error(409, "sync_busy", "同步已在进行中，请稍候")
    except StaleContextError:
        return _stale()
    ok = all(not status.startswith("failed") for status in results.values())
    return {"ok": ok, "results": results}


@paw.route("/pause", methods=("POST",))
async def post_pause(_ctx: AppContext, req: HttpRequest) -> dict | HttpResponse:
    """暂停/恢复本机上报（3.4 透明退出权）。

    台账/用量通道停发，心跳继续并携带开关状态（服务端
    devices.reporting_paused 置位，驾驶舱离线告警排除，3.4）。
    """
    if _context is None:
        return _http_error(503, "plugin_unavailable", "插件尚未激活")
    try:
        payload = req.json()
    except ValueError:
        return _http_error(422, "invalid_body", "请求体必须是 JSON")
    if not isinstance(payload, dict) or not isinstance(payload.get("paused"), bool):
        return _http_error(422, "invalid_field", "paused 必须为布尔值")
    paused = payload["paused"]
    try:
        await _context.storage.awrite_json(
            REPORTING_PAUSED_FILE, {"paused": paused, "updated_at": _now_iso()}
        )
        _context.logger.info(
            "deptagent-link reporting paused" if paused else "deptagent-link reporting resumed"
        )
    except StaleContextError:
        return _stale()
    return {
        "paused": paused,
        "note": "开关状态将随下一次心跳上报（约 5 分钟内；点「立即同步」可立即上报）",
    }


@paw.route("/bind", methods=("POST",))
async def post_bind(_ctx: AppContext, req: HttpRequest) -> dict | HttpResponse:
    """输码绑定（3.5；面板绑定表单提交）。成功即后台触发首次全量上报。"""
    if _context is None:
        return _http_error(503, "plugin_unavailable", "插件尚未激活")
    try:
        payload = req.json()
    except ValueError:
        return _http_error(422, "invalid_body", "请求体必须是 JSON")
    if not isinstance(payload, dict):
        return _http_error(422, "invalid_body", "请求体必须是 JSON 对象")
    server_url = str(payload.get("server_url") or "").strip()
    invite_code = str(payload.get("invite_code") or "").strip()
    employee_no = str(payload.get("employee_no") or "").strip()
    if not (server_url and invite_code and employee_no):
        return _http_error(
            422, "missing_fields", "服务器地址 / 邀请码 / 工号不能为空"
        )

    try:
        binding = await bind_device(
            _context,
            server_url,
            invite_code,
            employee_no,
            name=str(payload.get("name") or "").strip() or None,
            password=str(payload.get("password") or "").strip() or None,
            device_name=str(payload.get("device_name") or "").strip() or None,
        )
    except BindError as exc:
        return _http_error(exc.status_code or 400, exc.code, str(exc))
    except StaleContextError:
        return _stale()

    # 绑定成功 → 首次全量上报（3.5）后台执行，不阻塞面板响应；
    # 托管任务（resources.task）保证插件卸载时自动停止。
    try:
        _context.resources.task(
            diagnostics.run_manual_sync(_context), description="panel:first-sync"
        )
    except StaleContextError:
        return _stale()
    return {"ok": True, "binding": _binding_public(binding)}


@paw.route("/rebind", methods=("POST",))
async def post_rebind(_ctx: AppContext, _req: HttpRequest) -> dict | HttpResponse:
    """重新绑定第一步（3.8）：清除本机绑定与红灯状态（等重新输码）。"""
    if _context is None:
        return _http_error(503, "plugin_unavailable", "插件尚未激活")
    try:
        await clear_binding(_context)
    except StaleContextError:
        return _stale()
    return {"ok": True}


@paw.route("/diagnostics", methods=("GET",))
async def get_diagnostics(_ctx: AppContext, _req: HttpRequest) -> dict | HttpResponse:
    """诊断快照导出（3.8 操作「导出诊断日志」；不含设备令牌）。"""
    if _context is None:
        return _http_error(503, "plugin_unavailable", "插件尚未激活")
    try:
        return await diagnostics.build_diagnostics(_context)
    except StaleContextError:
        return _stale()
