# -*- coding: utf-8 -*-
"""智能体台账采集器（SPEC 3.4 ②）：经适配层读本地清单（15 min 全量）。

台账全量语义（D3 拍板）：每轮上报完整清单，服务端 UPSERT 幂等；归属
（创建人/科室）由服务端按上报设备令牌登记，客户端不自报（8.1）。
文件 IO 经 asyncio.to_thread 下放线程池，不阻塞宿主事件循环。
"""

from __future__ import annotations

import asyncio

from qwenpaw.plugins import PluginContext

from adapters.base import detect_format


async def collect_agents(context: PluginContext) -> list[dict]:
    """采集台账快照（8.1 agents 段；格式不匹配/读取失败 → 空列表降级）。"""
    fmt, reader = detect_format()
    if reader is None or fmt is None:
        context.logger.info(
            "deptagent-link agents: format not detected, skip round",
        )
        return []
    return await asyncio.to_thread(reader.read_agents)
