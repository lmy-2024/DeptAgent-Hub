# -*- coding: utf-8 -*-
"""diagnostics 模块单测（SPEC 3.2：自检 / 手动同步 / 诊断导出）。

self_check 的服务器可达性探测用假 AsyncClient 替身（不发真网络）；
真服务器路径由 test_smoke_channels 端到端覆盖。
"""

from __future__ import annotations

import json

import httpx
import pytest

import diagnostics
from config import STORAGE_FILES
from fakes import FakeContext


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _FakeAsyncClient:
    """httpx.AsyncClient 替身：GET /health 按注入行为返回或抛错。"""

    def __init__(self, behavior) -> None:
        self._behavior = behavior

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def get(self, url: str) -> _FakeResponse:
        result = self._behavior(url)
        if isinstance(result, Exception):
            raise result
        return _FakeResponse(result)


def _patch_client(monkeypatch: pytest.MonkeyPatch, behavior) -> None:
    monkeypatch.setattr(
        diagnostics.httpx, "AsyncClient", lambda timeout=None: _FakeAsyncClient(behavior)
    )


def _bound(context: FakeContext, server_url: str = "https://dept.example.com") -> None:
    context.storage._files[STORAGE_FILES["binding"]] = {  # noqa: SLF001 - 测试注入
        "server_url": server_url,
        "employee_no": "M102",
        "device_token": "SECRET",
        "bound_at": "2026-11-10T00:00:00+00:00",
    }


# ── self_check ──────────────────────────────────────────────────────────


async def test_self_check_unbound():
    result = await diagnostics.self_check(FakeContext())
    assert result["verdict"] == "not_bound"
    assert [item["name"] for item in result["items"]] == ["bound"]
    assert result["binding"] is None


async def test_self_check_all_healthy(
    context: FakeContext, monkeypatch: pytest.MonkeyPatch
):
    _bound(context)
    context.storage._files[STORAGE_FILES["telemetry_status"]] = {  # noqa: SLF001
        "upload_state": "ok"
    }
    context.storage._files[STORAGE_FILES["watermark"]] = {"usage": {"2026-11-10": "md5"}}  # noqa: SLF001
    _patch_client(monkeypatch, lambda url: 200)

    result = await diagnostics.self_check(context)
    assert result["verdict"] == "ok"
    assert {item["name"] for item in result["items"]} == {
        "bound",
        "server_reachable",
        "token_state",
        "watermark_structure",
        "usage_watermark_days",
    }
    assert all(item["ok"] for item in result["items"])
    # 脱敏：绑定视图不含令牌
    assert "device_token" not in json.dumps(result)


async def test_self_check_server_unreachable(
    context: FakeContext, monkeypatch: pytest.MonkeyPatch
):
    _bound(context)
    _patch_client(monkeypatch, lambda url: httpx.ConnectError("refused"))

    result = await diagnostics.self_check(context)
    assert result["verdict"] == "degraded"
    by_name = {item["name"]: item for item in result["items"]}
    assert by_name["server_reachable"]["ok"] is False
    assert "network_error" in by_name["server_reachable"]["detail"]


async def test_self_check_server_error_status(
    context: FakeContext, monkeypatch: pytest.MonkeyPatch
):
    _bound(context)
    _patch_client(monkeypatch, lambda url: 503)

    result = await diagnostics.self_check(context)
    assert result["verdict"] == "degraded"
    by_name = {item["name"]: item for item in result["items"]}
    assert by_name["server_reachable"]["ok"] is False
    assert by_name["server_reachable"]["detail"] == "HTTP 503"


async def test_self_check_red_light_token(
    context: FakeContext, monkeypatch: pytest.MonkeyPatch
):
    _bound(context)
    context.storage._files[STORAGE_FILES["telemetry_status"]] = {  # noqa: SLF001
        "upload_state": "revoked"
    }
    _patch_client(monkeypatch, lambda url: 200)

    result = await diagnostics.self_check(context)
    assert result["verdict"] == "degraded"
    by_name = {item["name"]: item for item in result["items"]}
    assert by_name["token_state"]["ok"] is False
    assert "revoked" in by_name["token_state"]["detail"]


async def test_self_check_corrupted_watermark(
    context: FakeContext, monkeypatch: pytest.MonkeyPatch
):
    _bound(context)
    # 旧版本 bug 产物：usage 被时间戳字符串顶掉
    context.storage._files[STORAGE_FILES["watermark"]] = {"usage": "2026-11-10T00:00:00"}  # noqa: SLF001
    _patch_client(monkeypatch, lambda url: 200)

    result = await diagnostics.self_check(context)
    assert result["verdict"] == "degraded"
    by_name = {item["name"]: item for item in result["items"]}
    assert by_name["watermark_structure"]["ok"] is False


# ── 手动同步入口（包结构归位：diagnostics re-export，实现归 scheduler）──


async def test_run_manual_sync_is_scheduler_implementation():
    assert diagnostics.run_manual_sync is __import__("scheduler").run_manual_sync
    assert diagnostics.SyncBusyError is __import__("scheduler").SyncBusyError


# ── build_diagnostics（面板 /diagnostics 数据源）─────────────────────────


async def test_build_diagnostics_shape():
    context = FakeContext()
    _bound(context)
    context.storage._files[STORAGE_FILES["seq"]] = {"seq": 7}  # noqa: SLF001

    result = await diagnostics.build_diagnostics(context)
    assert result["plugin"]["id"] == "deptagent-link"
    assert result["upload"]["seq"] == 7
    assert set(result["channels"]) == {"heartbeat", "agents", "usage"}
    assert "device_token" not in json.dumps(result)
