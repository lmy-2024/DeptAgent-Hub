# -*- coding: utf-8 -*-
"""常驻调度器：on_activate 内启动的三通道采集/上报循环（SPEC 3.2、3.12）。

纪律（源码级硬约束）：
- 一切后台任务只能在 on_activate 回调内创建（3.12 第 3 条，register 内
  创建资源会被宿主以 ResourceError 拒绝）；
- StaleContextError = 插件已被禁用/升级/替换（3.12 第 8 条）→ 视为正常
  停机信号，安静退出，不打错误日志；
- 持久化只走 context.storage（原子写、路径锁定插件数据目录，3.12 第 5 条）：
  离线队列 / 增量水位 / 绑定状态的存储键在 STORAGE_FILES 中集中声明，
  由 binding.py（T1.3）、uploader.py（T1.4）、collectors/usage.py（T1.7）使用。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Awaitable, Callable

from qwenpaw.plugins import PluginContext, StaleContextError

# 拍板 D2（2026-11-10）：用量 / 台账 / 心跳 = 5 / 15 / 5 min
USAGE_INTERVAL_SECONDS = 5 * 60
AGENTS_INTERVAL_SECONDS = 15 * 60
HEARTBEAT_INTERVAL_SECONDS = 5 * 60

# 持久化键（context.storage 相对路径；SPEC 3.12 第 5 条：只写插件数据目录）
STORAGE_FILES = {
    "offline_queue": "offline_queue.json",  # 离线上报队列（T1.4 uploader）
    "watermark": "watermark.json",  # 各通道增量水位（T1.7 usage）
    "binding": "binding.json",  # 绑定状态（T1.3 binding）
}


async def start_scheduler(context: PluginContext, *, run_immediately: bool = False) -> None:
    """在 on_activate 回调内调用：恢复水位并启动三通道常驻任务。

    本函数只在 activate 阶段执行一次性轻量 IO（读水位记日志），
    周期任务先 sleep 后执行，避免激活路径做重活。

    run_immediately=True（已绑定，SPEC 3.5 首次全量上报）：各通道
    首轮跳过 sleep 立即执行。

    任务统一走 context.resources.task()（官方托管任务：卸载时由
    resources.close() → custody.stop_task 自动停止，否则 check
    --runtime 会报 unhosted_task 残留，见 QwenPaw 源码
    plugins/resources.py ResourceScope.task）。
    """
    watermark = await context.storage.aread_json(STORAGE_FILES["watermark"], {})
    context.logger.info(
        "deptagent-link scheduler started",
        fields={"restored_watermark": watermark, "run_immediately": run_immediately},
    )

    channels: tuple[tuple[str, float, Callable[[PluginContext], Awaitable[None]]], ...] = (
        ("heartbeat", HEARTBEAT_INTERVAL_SECONDS, _collect_heartbeat),
        ("agents", AGENTS_INTERVAL_SECONDS, _collect_agents),
        ("usage", USAGE_INTERVAL_SECONDS, _collect_usage),
    )
    for name, interval, action in channels:
        context.resources.task(
            _channel_loop(context, name, interval, action, immediate=run_immediately),
            description=f"channel:{name}",
        )


async def _channel_loop(
    context: PluginContext,
    name: str,
    interval_seconds: float,
    action: Callable[[PluginContext], Awaitable[None]],
    *,
    immediate: bool = False,
) -> None:
    """单通道常驻循环：固定周期执行 action；Stale 即安静停机。

    容错策略（SPEC 3.7 容错与降级链）：通道失败不终止循环，
    记 warning 后等下个周期重试；指数退避由 T1.4 uploader 接入。
    """
    first_round = True
    while True:
        if not (first_round and immediate):
            await asyncio.sleep(interval_seconds)
        first_round = False
        try:
            await action(context)
            await _touch_watermark(context, name)
        except StaleContextError:
            # 宿主已禁用/升级/替换本插件：正常停机信号（3.12 第 8 条）
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 单通道失败不拖垮其他通道
            try:
                context.logger.warning(
                    "deptagent-link channel failed",
                    fields={"channel": name, "error": str(exc)},
                )
            except StaleContextError:
                return


async def _touch_watermark(context: PluginContext, channel: str) -> None:
    """记录通道本轮执行时间（增量水位雏形，T1.7 扩展为按日水位）。"""
    watermark = await context.storage.aread_json(STORAGE_FILES["watermark"], {})
    watermark[channel] = datetime.now(UTC).isoformat()
    await context.storage.awrite_json(STORAGE_FILES["watermark"], watermark)


async def _collect_heartbeat(context: PluginContext) -> None:
    """心跳采集器（T1.5 替换实现：SPEC 3.4 ①全字段）。"""
    _ = context


async def _collect_agents(context: PluginContext) -> None:
    """智能体台账采集器（T1.6 替换实现：SPEC 3.4 ②字段）。"""
    _ = context


async def _collect_usage(context: PluginContext) -> None:
    """Token 用量采集器（T1.7 替换实现：SPEC 3.4 ③六项计数）。"""
    _ = context
