# -*- coding: utf-8 -*-
"""状态文件读-改-写串行化（watermark / today_report 多写方并发保护）。

写方：三通道常驻循环（scheduler）+ 面板手动同步（panel →
scheduler.run_manual_sync）+ 用量水位提交（collectors.usage）——
asyncio 单循环内读与写之间仍可让渡，读-改-写必须整体持锁，
否则后写者会以陈旧快照覆盖前写者的字段（如 usage 指纹被通道
时间戳顶掉）。锁仅约束本插件内的交错，不涉及跨进程。
"""

from __future__ import annotations

import asyncio
from typing import Callable

from qwenpaw.plugins import PluginContext

from config import STORAGE_FILES

_FILE_LOCK = asyncio.Lock()


async def update_json(
    context: PluginContext,
    key: str,
    mutate: Callable[[dict], None],
) -> None:
    """持锁读-改-写 STORAGE_FILES[key]（非 dict 内容容错归一 {}）。"""
    async with _FILE_LOCK:
        value = await context.storage.aread_json(STORAGE_FILES[key], {})
        if not isinstance(value, dict):
            value = {}
        mutate(value)
        await context.storage.awrite_json(STORAGE_FILES[key], value)
