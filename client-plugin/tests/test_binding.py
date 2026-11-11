# -*- coding: utf-8 -*-
"""binding 模块单测（SPEC 3.5 / 3.7）。

覆盖「重新绑定清除红灯」缺陷回归：bind 成功后 telemetry_status 必须被
清除，否则 reporting_stopped 拦截新令牌上报（T1.15 真机验收抓到）。
"""

from __future__ import annotations

import httpx
import pytest

import binding
from config import STORAGE_FILES
from fakes import FakeContext


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def _patch_post(monkeypatch: pytest.MonkeyPatch, response) -> None:
    """httpx.AsyncClient 替身：POST /api/v1/bind 按注入结果返回。"""

    class _Client:
        def __init__(self, timeout=None) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc) -> bool:
            return False

        async def post(self, url: str, json: dict):
            if isinstance(response, Exception):
                raise response
            assert url == "https://dept.example.com/api/v1/bind"
            return response

    monkeypatch.setattr(binding.httpx, "AsyncClient", _Client)


async def test_bind_success_clears_red_light(context: FakeContext, monkeypatch):
    context.storage._files[STORAGE_FILES["telemetry_status"]] = {  # noqa: SLF001
        "upload_state": "revoked",
        "detail": "设备令牌已被吊销",
    }
    _patch_post(
        monkeypatch,
        _FakeResponse(
            200,
            {
                "device_token": "NEW-TOKEN",
                "server_config": {"report_intervals_sec": {"heartbeat": 300}},
            },
        ),
    )
    result = await binding.bind_device(
        context, "https://dept.example.com", "DA-1", "M102"
    )
    assert result["device_token"] == "NEW-TOKEN"
    stored = await context.storage.aread_json(STORAGE_FILES["binding"], None)
    assert stored["employee_no"] == "M102"
    # 红灯状态必须被清除，否则新令牌上报会被 reporting_stopped 拦截
    assert (
        await context.storage.aread_json(STORAGE_FILES["telemetry_status"], None) is None
    )


async def test_bind_failure_keeps_existing_state(context: FakeContext, monkeypatch):
    context.storage._files[STORAGE_FILES["binding"]] = {"employee_no": "OLD"}  # noqa: SLF001
    context.storage._files[STORAGE_FILES["telemetry_status"]] = {  # noqa: SLF001
        "upload_state": "invalid"
    }
    _patch_post(
        monkeypatch,
        _FakeResponse(
            400, {"error": {"code": "invite_invalid", "message": "邀请码无效或已被使用"}}
        ),
    )
    with pytest.raises(binding.BindError) as exc_info:
        await binding.bind_device(context, "https://dept.example.com", "DA-X", "M102")
    assert exc_info.value.code == "invite_invalid"
    assert exc_info.value.status_code == 400
    # 失败不动本地状态：原绑定与红灯保留
    assert (await context.storage.aread_json(STORAGE_FILES["binding"], None))[
        "employee_no"
    ] == "OLD"
    assert (
        await context.storage.aread_json(STORAGE_FILES["telemetry_status"], None)
    )["upload_state"] == "invalid"


async def test_bind_network_error(context: FakeContext, monkeypatch):
    _patch_post(monkeypatch, httpx.ConnectError("connection refused"))
    with pytest.raises(binding.BindError) as exc_info:
        await binding.bind_device(context, "https://dept.example.com", "DA-1", "M102")
    assert exc_info.value.code == "network_error"
    assert exc_info.value.status_code == 0
