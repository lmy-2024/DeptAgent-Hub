# -*- coding: utf-8 -*-
"""Token 用量采集器（SPEC 3.4 ③六项计数）——T1.7 交付（增量水位算法）。"""

from __future__ import annotations

from qwenpaw.plugins import PluginContext


async def collect_usage(context: PluginContext) -> list[dict]:
    """采集增量用量快照（T1.7 实现；当前占位返回空列表）。"""
    _ = context
    return []
