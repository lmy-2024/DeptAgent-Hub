# -*- coding: utf-8 -*-
"""Token 用量采集器（SPEC 3.4 ③、3.6 增量算法）。

增量语义（3.6）：当日数据每次全量重传（服务端 UPSERT 全量覆盖）、
历史日仅在指纹变化时重传；首次绑定（无水位）= 90 天回灌（D3 拍板）。

水位纪律：指纹在上报成功后才提交（scheduler 调
commit_usage_watermark）——上报失败/红灯时水位不动，下轮自动重传，
无指针漂移。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta

from qwenpaw.plugins import PluginContext

from adapters.base import detect_format
from config import STORAGE_FILES

# D3 拍板：回灌深度 90 天（窗口外日期不报也不记水位）
USAGE_BACKFILL_DAYS = 90


async def collect_usage(
    context: PluginContext,
) -> tuple[list[dict], dict[str, str]]:
    """采集增量用量：返回 (待上报行, 全量日指纹)。

    待上报行 = 当日全部 + 指纹变化的历史日全部（90 天窗口内）；
    指纹 = {date: md5(当日六项计数)}，由调用方在上报成功后提交水位。
    本地无数据/格式不匹配 → ([], {})（通道本轮静默，在线信号由心跳
    通道维持）。
    """
    fmt, reader = detect_format()
    if reader is None or fmt is None:
        context.logger.info("deptagent-link usage: format not detected, skip round")
        return [], {}

    daily = await asyncio.to_thread(reader.read_usage)
    if not daily:
        return [], {}
    watermark = await context.storage.aread_json(STORAGE_FILES["watermark"], {})
    known: dict = watermark.get("usage", {})

    # 员工本地日期（1.5：stat_date 客户端生成，服务器不做时区换算）
    today = datetime.now().strftime("%Y-%m-%d")
    cutoff = (datetime.now() - timedelta(days=USAGE_BACKFILL_DAYS)).strftime(
        "%Y-%m-%d"
    )

    rows: list[dict] = []
    fingerprints: dict[str, str] = {}
    for day, day_rows in daily.items():
        if not isinstance(day, str) or len(day) != 10:
            continue
        if not (cutoff <= day <= today):  # 90 天窗口外：不报不记（D3）
            continue
        fingerprints[day] = _fingerprint(day_rows)
        if day == today or known.get(day) != fingerprints[day]:
            for row in day_rows:
                rows.append({"stat_date": day, **row})
    return rows, fingerprints


async def commit_usage_watermark(
    context: PluginContext, fingerprints: dict[str, str]
) -> None:
    """上报成功后提交用量水位（指纹只含 90 天窗口内日期，自然滚动）。"""
    watermark = await context.storage.aread_json(STORAGE_FILES["watermark"], {})
    watermark["usage"] = fingerprints
    await context.storage.awrite_json(STORAGE_FILES["watermark"], watermark)


def _fingerprint(day_rows: list[dict]) -> str:
    """单日用量行稳定指纹（行排序后 md5——与本地写入顺序无关）。"""
    ordered = sorted(
        day_rows,
        key=lambda r: (
            str(r.get("agent_key") or ""),
            str(r.get("provider_id") or ""),
            str(r.get("model") or ""),
        ),
    )
    payload = json.dumps(ordered, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()
