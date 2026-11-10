# -*- coding: utf-8 -*-
"""智能体台账采集器（SPEC 3.4 ②）——T1.6 交付（本地数据目录扫描）。"""

from __future__ import annotations

from qwenpaw.plugins import PluginContext


async def collect_agents(context: PluginContext) -> list[dict]:
    """采集智能体台账快照（T1.6 实现；当前占位返回空列表）。"""
    _ = context
    return []
