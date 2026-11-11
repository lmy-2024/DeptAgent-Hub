# -*- coding: utf-8 -*-
"""格式降级链单测（SPEC 3.7/3.11-4）。

「篡改本地 token 文件模拟格式破坏」的行为断言：
- 探测失败 → 采集降级（usage/agents 空）仅心跳；
- 心跳上报显式 format_mismatch 事件（服务端 COALESCE 不覆盖 None）；
- 面板状态 collect.degraded=true（黄灯数据源）。
"""

from __future__ import annotations

import json

import pytest

import panel
from adapters.qwenpaw_2_3 import QwenPaw23Reader
from collectors import heartbeat
from fakes import FakeContext


def _make_workdir(tmp_path, token_content: str | None = '{"2026-11-10": {}}'):
    """造最小宿主数据目录：config.json + 可选 token_usage.json。"""
    root = tmp_path / "qwenpaw-home"
    root.mkdir()
    (root / "config.json").write_text(
        json.dumps({"agents": {"profiles": {"default": {}}}}), encoding="utf-8"
    )
    if token_content is not None:
        (root / "token_usage.json").write_text(token_content, encoding="utf-8")
    return root


def _patch_env(monkeypatch: pytest.MonkeyPatch, root) -> None:
    monkeypatch.setenv("QWENPAW_WORKING_DIR", str(root))
    monkeypatch.delenv("QWENPAW_TOKEN_USAGE_FILE", raising=False)


def test_probe_ok_when_token_file_valid(tmp_path, monkeypatch):
    _patch_env(monkeypatch, _make_workdir(tmp_path))
    assert QwenPaw23Reader().probe_format() == "qwenpaw-2.3"


def test_probe_ok_when_token_file_missing(tmp_path, monkeypatch):
    """token 文件缺失 = 尚未产生用量，非降级。"""
    _patch_env(monkeypatch, _make_workdir(tmp_path, token_content=None))
    assert QwenPaw23Reader().probe_format() == "qwenpaw-2.3"


def test_probe_fails_when_token_file_corrupted(tmp_path, monkeypatch):
    """篡改 token 文件（坏 JSON）→ 探测失败（3.11-4 模拟口径）。"""
    _patch_env(monkeypatch, _make_workdir(tmp_path, token_content="{broken json"))
    assert QwenPaw23Reader().probe_format() is None


async def test_heartbeat_reports_format_mismatch(context: FakeContext, monkeypatch):
    monkeypatch.setattr(heartbeat, "detect_format", lambda: (None, None))
    payload = await heartbeat.collect_heartbeat(context)
    assert payload["format_probe"] == "format_mismatch"


async def test_agents_channel_skipped_when_degraded(context: FakeContext, monkeypatch):
    """采集器返回 None（格式探测失败）→ 台账通道不走上报（仅心跳）。"""
    import scheduler
    from collectors import agents as agents_mod

    monkeypatch.setattr(agents_mod, "detect_format", lambda: (None, None))
    assert await agents_mod.collect_agents(context) is None
    monkeypatch.setattr(
        scheduler, "collect_agents", lambda ctx: _async_none()
    )
    assert await scheduler._run_agents(context) == "skipped_degraded"  # noqa: SLF001


async def _async_none():
    return None


async def test_status_exposes_degraded_flag(context: FakeContext, monkeypatch):
    panel.bind_context(context)
    try:
        monkeypatch.setattr(panel, "detect_format", lambda: (None, None))
        result = await panel.get_status(None, None)
        assert result["collect"]["degraded"] is True
        assert result["collect"]["format"] is None
        assert "仅心跳" in result["collect"]["detail"]

        monkeypatch.setattr(panel, "detect_format", lambda: ("qwenpaw-2.3", object()))
        result = await panel.get_status(None, None)
        assert result["collect"]["degraded"] is False
        assert result["collect"]["format"] == "qwenpaw-2.3"
        assert result["collect"]["detail"] is None
    finally:
        panel._context = None  # noqa: SLF001 - 测试复位模块级注入
