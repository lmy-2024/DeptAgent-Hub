# -*- coding: utf-8 -*-
"""员工面板数据层单测（SPEC 3.8/3.4）：PawApp handler 直调 + 调度器配套。

FakeContext 只实现插件实际使用的 PluginContext 面（storage/logger/
resources）；handler 语义与真实宿主一致（PawApp 注册层仅做路由分发，
handler 本体是纯编排逻辑）。
"""

from __future__ import annotations

import json

import pytest
from qwenpaw.plugins.apps import HttpRequest, HttpResponse

import panel
import scheduler
from binding import BindError
from collectors import usage as usage_mod
from config import REPORTING_PAUSED_FILE, STORAGE_FILES
from fakes import FakeContext
from uploader import employee_paused


def _request(body: dict | None = None) -> HttpRequest:
    payload = b"" if body is None else json.dumps(body).encode("utf-8")
    return HttpRequest("POST", "/panel", {}, {}, {}, payload)


@pytest.fixture(autouse=True)
def bound_panel(monkeypatch: pytest.MonkeyPatch, context: FakeContext):
    """每个用例注入独立 FakeContext，结束复位（避免跨用例泄漏）。"""
    panel.bind_context(context)
    yield context
    panel._context = None  # noqa: SLF001 - 测试复位模块级注入


# ── GET /status ─────────────────────────────────────────────────────────


async def test_status_unbound_defaults(context: FakeContext):
    result = await panel.get_status(None, None)
    assert result["binding"] is None
    assert result["paused"] is False
    assert result["upload"]["state"] == "idle"
    assert result["today"] is None
    assert [c["name"] for c in result["channels"]] == ["heartbeat", "agents", "usage"]
    assert all(c["last_run"] is None for c in result["channels"])
    assert {c["interval_min"] for c in result["channels"]} == {5, 15}


async def test_status_bound_sanitized_no_token(context: FakeContext):
    await context.storage.awrite_json(
        STORAGE_FILES["binding"],
        {
            "server_url": "https://dept.example.com",
            "employee_no": "M102",
            "device_token": "SECRET-TOKEN",
            "bound_at": "2026-11-10T00:00:00+00:00",
        },
    )
    result = await panel.get_status(None, None)
    assert result["binding"] == {
        "employee_no": "M102",
        "server_url": "https://dept.example.com",
        "bound_at": "2026-11-10T00:00:00+00:00",
    }
    assert "device_token" not in json.dumps(result)


async def test_status_reads_channels_and_today(context: FakeContext):
    await context.storage.awrite_json(
        STORAGE_FILES["watermark"],
        {"channels": {"heartbeat": "2026-11-10T08:00:00+00:00"}, "usage": {}},
    )
    await context.storage.awrite_json(
        STORAGE_FILES["today_report"],
        {"date": "2026-11-10", "usage_tokens": 1234},
    )
    await context.storage.awrite_json(
        STORAGE_FILES["telemetry_status"], {"upload_state": "ok", "last_ok": "t"}
    )
    result = await panel.get_status(None, None)
    by_name = {c["name"]: c for c in result["channels"]}
    assert by_name["heartbeat"]["last_run"] == "2026-11-10T08:00:00+00:00"
    assert by_name["agents"]["last_run"] is None
    assert result["upload"]["state"] == "ok"
    assert result["today"]["usage_tokens"] == 1234


async def test_status_paused_flag(context: FakeContext):
    await context.storage.awrite_json(
        REPORTING_PAUSED_FILE, {"paused": True, "updated_at": "t"}
    )
    result = await panel.get_status(None, None)
    assert result["paused"] is True


# ── POST /pause ─────────────────────────────────────────────────────────


async def test_pause_rejects_invalid_body(context: FakeContext):
    result = await panel.post_pause(None, _request(None))
    assert isinstance(result, HttpResponse)
    assert result.status == 422

    result = await panel.post_pause(None, _request({"paused": "yes"}))
    assert isinstance(result, HttpResponse)
    assert result.status == 422


async def test_pause_writes_switch(context: FakeContext):
    result = await panel.post_pause(None, _request({"paused": True}))
    assert result["paused"] is True
    state = await context.storage.aread_json(REPORTING_PAUSED_FILE, {})
    assert state["paused"] is True
    assert "updated_at" in state
    assert await employee_paused(context) is True

    result = await panel.post_pause(None, _request({"paused": False}))
    assert result["paused"] is False
    assert await employee_paused(context) is False


# ── POST /bind / POST /rebind ───────────────────────────────────────────


async def test_bind_missing_fields(context: FakeContext):
    result = await panel.post_bind(
        None, _request({"server_url": "https://x", "employee_no": "M1"})
    )
    assert isinstance(result, HttpResponse)
    assert result.status == 422
    assert result.body["error"]["code"] == "missing_fields"


async def test_bind_success_schedules_first_sync(
    context: FakeContext, monkeypatch: pytest.MonkeyPatch
):
    async def fake_bind(ctx, server_url, invite_code, employee_no, **kwargs):
        assert (server_url, invite_code, employee_no) == (
            "https://dept.example.com",
            "DA-12345678",
            "M102",
        )
        assert kwargs["name"] == "张三"
        return {
            "server_url": server_url,
            "employee_no": employee_no,
            "device_token": "SECRET",
            "bound_at": "2026-11-10T00:00:00+00:00",
        }

    monkeypatch.setattr(panel, "bind_device", fake_bind)
    result = await panel.post_bind(
        None,
        _request(
            {
                "server_url": "https://dept.example.com",
                "invite_code": "DA-12345678",
                "employee_no": "M102",
                "name": "张三",
            }
        ),
    )
    assert result["ok"] is True
    assert "device_token" not in json.dumps(result)
    # 首次全量上报任务已托管（3.5）
    assert context.resources.descriptions == ["panel:first-sync"]


async def test_bind_error_maps_http_status(
    context: FakeContext, monkeypatch: pytest.MonkeyPatch
):
    async def fake_bind(ctx, *args, **kwargs):
        raise BindError("invite_invalid", "邀请码无效", 400)

    monkeypatch.setattr(panel, "bind_device", fake_bind)
    result = await panel.post_bind(
        None,
        _request(
            {
                "server_url": "https://x",
                "invite_code": "DA-X",
                "employee_no": "M1",
            }
        ),
    )
    assert isinstance(result, HttpResponse)
    assert result.status == 400
    assert result.body["error"]["code"] == "invite_invalid"
    assert result.body["error"]["message"] == "邀请码无效"


async def test_rebind_clears_binding_and_red_light(context: FakeContext):
    await context.storage.awrite_json(STORAGE_FILES["binding"], {"employee_no": "M1"})
    await context.storage.awrite_json(
        STORAGE_FILES["telemetry_status"], {"upload_state": "revoked"}
    )
    result = await panel.post_rebind(None, None)
    assert result["ok"] is True
    assert await context.storage.aread_json(STORAGE_FILES["binding"], None) is None
    assert await context.storage.aread_json(
        STORAGE_FILES["telemetry_status"], None
    ) is None


# ── GET /diagnostics ────────────────────────────────────────────────────


async def test_diagnostics_excludes_token(context: FakeContext):
    await context.storage.awrite_json(
        STORAGE_FILES["binding"],
        {"employee_no": "M102", "device_token": "SECRET-TOKEN", "server_url": "s"},
    )
    await context.storage.awrite_json(STORAGE_FILES["seq"], {"seq": 42})
    await context.storage.awrite_json(
        STORAGE_FILES["watermark"], {"usage": {"2026-11-10": "abc", "2026-11-09": "def"}}
    )
    result = await panel.get_diagnostics(None, None)
    assert result["plugin"]["id"] == "deptagent-link"
    assert result["upload"]["seq"] == 42
    assert result["usage_watermark_days"] == 2
    assert set(result["channels"]) == {"heartbeat", "agents", "usage"}
    assert "device_token" not in json.dumps(result)


# ── scheduler 配套：watermark 修复 / today_report / 暂停 / 手动同步 ────


async def test_touch_watermark_preserves_usage_fingerprints(context: FakeContext):
    """回归（T1.13 修复）：通道时间戳不得覆盖 usage 按日指纹。"""
    await context.storage.awrite_json(
        STORAGE_FILES["watermark"], {"usage": {"2026-11-10": "md5-old"}}
    )
    await scheduler._touch_watermark(context, "heartbeat")  # noqa: SLF001
    watermark = await context.storage.aread_json(STORAGE_FILES["watermark"], {})
    assert watermark["usage"] == {"2026-11-10": "md5-old"}
    assert "heartbeat" in watermark["channels"]


async def test_touch_watermark_ignores_corrupted_usage_key(context: FakeContext):
    """旧版本 bug 产物（usage 被写成时间戳字符串）：touch 不碰它也不崩，
    由 collect_usage 的 isinstance 防御容读 + 下轮成功后
    commit_usage_watermark 全量覆盖自愈。"""
    await context.storage.awrite_json(
        STORAGE_FILES["watermark"], {"usage": "2026-11-10T00:00:00+00:00"}
    )
    await scheduler._touch_watermark(context, "heartbeat")  # noqa: SLF001
    watermark = await context.storage.aread_json(STORAGE_FILES["watermark"], {})
    assert "heartbeat" in watermark["channels"]


async def test_commit_usage_watermark_heals_corrupted_key(context: FakeContext):
    """旧版本 bug 产物自愈路径：上报成功后的指纹提交整体覆盖 usage 键。"""
    await context.storage.awrite_json(
        STORAGE_FILES["watermark"], {"usage": "corrupted-timestamp"}
    )
    await usage_mod.commit_usage_watermark(
        context, {"2026-11-10": "md5-new", "2026-11-09": "md5-old"}
    )
    watermark = await context.storage.aread_json(STORAGE_FILES["watermark"], {})
    assert watermark["usage"] == {"2026-11-10": "md5-new", "2026-11-09": "md5-old"}


async def test_collect_usage_survives_corrupted_watermark(
    context: FakeContext, monkeypatch: pytest.MonkeyPatch
):
    class FakeReader:
        def read_usage(self):
            return {
                "2026-11-10": [
                    {
                        "agent_key": None,
                        "provider_id": "p",
                        "model": "m",
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "cache_read_tokens": 0,
                        "cache_write_tokens": 0,
                        "call_count": 1,
                    }
                ]
            }

    monkeypatch.setattr(usage_mod, "detect_format", lambda: ("2.3", FakeReader()))
    await context.storage.awrite_json(
        STORAGE_FILES["watermark"], {"usage": "corrupted-timestamp"}
    )
    rows, fingerprints = await usage_mod.collect_usage(context)
    assert len(rows) == 1
    assert "2026-11-10" in fingerprints


async def test_record_today_resets_on_new_day(context: FakeContext):
    await context.storage.awrite_json(
        STORAGE_FILES["today_report"], {"date": "2000-01-01", "usage_tokens": 999}
    )
    await scheduler._record_today(context, agents_count=2)  # noqa: SLF001
    report = await context.storage.aread_json(STORAGE_FILES["today_report"], {})
    from datetime import datetime

    assert report["date"] == datetime.now().strftime("%Y-%m-%d")
    assert report["agents_count"] == 2
    assert "usage_tokens" not in report


async def test_run_agents_skipped_when_paused(
    context: FakeContext, monkeypatch: pytest.MonkeyPatch
):
    await context.storage.awrite_json(REPORTING_PAUSED_FILE, {"paused": True})

    async def must_not_collect(ctx):
        raise AssertionError("暂停时不得采集台账")

    monkeypatch.setattr(scheduler, "collect_agents", must_not_collect)
    status = await scheduler._run_agents(context)  # noqa: SLF001
    assert status == "skipped_paused"


async def test_run_usage_skipped_when_paused(
    context: FakeContext, monkeypatch: pytest.MonkeyPatch
):
    await context.storage.awrite_json(REPORTING_PAUSED_FILE, {"paused": True})

    async def must_not_collect(ctx):
        raise AssertionError("暂停时不得采集用量")

    monkeypatch.setattr(scheduler, "collect_usage", must_not_collect)
    status = await scheduler._run_usage(context)  # noqa: SLF001
    assert status == "skipped_paused"


async def test_run_manual_sync_busy_rejected():
    async with scheduler._MANUAL_SYNC_LOCK:  # noqa: SLF001
        with pytest.raises(scheduler.SyncBusyError):
            await scheduler.run_manual_sync(None)


async def test_run_manual_sync_runs_three_channels(
    context: FakeContext, monkeypatch: pytest.MonkeyPatch
):
    calls: list[str] = []

    async def fake_run(ctx, name):
        calls.append(name)
        return "ok"

    monkeypatch.setattr(scheduler, "_run_heartbeat", lambda ctx: fake_run(ctx, "heartbeat"))
    monkeypatch.setattr(scheduler, "_run_agents", lambda ctx: fake_run(ctx, "agents"))
    monkeypatch.setattr(scheduler, "_run_usage", lambda ctx: fake_run(ctx, "usage"))
    results = await scheduler.run_manual_sync(context)
    assert results == {"heartbeat": "ok", "agents": "ok", "usage": "ok"}
    assert calls == ["heartbeat", "agents", "usage"]


# ── panel 未激活防御 ────────────────────────────────────────────────────


async def test_handlers_guard_unactivated():
    saved = panel._context  # noqa: SLF001
    panel._context = None  # noqa: SLF001
    try:
        result = await panel.get_status(None, None)
        assert isinstance(result, HttpResponse)
        assert result.status == 503
        result = await panel.post_sync(None, None)
        assert result.status == 503
    finally:
        panel._context = saved
