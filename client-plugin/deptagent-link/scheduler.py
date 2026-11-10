# -*- coding: utf-8 -*-
"""常驻调度器：on_activate 内启动的三通道采集/上报循环（SPEC 3.2、3.12）。

纪律（源码级硬约束）：
- 一切后台任务只能在 on_activate 回调内创建（3.12 第 3 条，register 内
  创建资源会被宿主以 ResourceError 拒绝）；
- StaleContextError = 插件已被禁用/升级/替换（3.12 第 8 条）→ 视为正常
  停机信号，安静退出，不打错误日志；
- 持久化只走 context.storage（原子写、路径锁定插件数据目录，3.12 第 5 条）：
  存储键在 config.STORAGE_FILES 集中声明（binding / uploader / collectors
  共用，独立模块避免相互导入成环）；
- 红灯停报（3.7）：令牌吊销后各通道本轮直接跳过（循环存活，等重新
  绑定后自动恢复，采集器/uploader 每轮重新读 binding）。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Awaitable, Callable

from qwenpaw.plugins import PluginContext, StaleContextError

import config
from collectors.agents import collect_agents
from collectors.heartbeat import collect_heartbeat
from collectors.usage import collect_usage
from config import STORAGE_FILES
from uploader import UploadStopped, reporting_stopped, send_report

# 拍板 D2（2026-11-10）：用量 / 台账 / 心跳 = 5 / 15 / 5 min
USAGE_INTERVAL_SECONDS = 5 * 60
AGENTS_INTERVAL_SECONDS = 15 * 60
HEARTBEAT_INTERVAL_SECONDS = 5 * 60


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
    config.ACTIVATED_AT = datetime.now(UTC)
    watermark = await context.storage.aread_json(STORAGE_FILES["watermark"], {})
    context.logger.info(
        "deptagent-link scheduler started",
        fields={"restored_watermark": watermark, "run_immediately": run_immediately},
    )

    channels: tuple[tuple[str, float, Callable[[PluginContext], Awaitable[None]]], ...] = (
        ("heartbeat", HEARTBEAT_INTERVAL_SECONDS, _run_heartbeat),
        ("agents", AGENTS_INTERVAL_SECONDS, _run_agents),
        ("usage", USAGE_INTERVAL_SECONDS, _run_usage),
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


async def _run_heartbeat(context: PluginContext) -> None:
    """心跳通道（T1.5）：采集设备快照 → 上报（agents/usage 段为空）。"""
    device = await collect_heartbeat(context)
    await _send(context, device=device, agents=[], usage=[])


async def _run_agents(context: PluginContext) -> None:
    """台账通道（T1.6）：采集智能体快照 → 上报（采集器当前占位返空）。"""
    agents = await collect_agents(context)
    await _send(context, device={}, agents=agents, usage=[])


async def _run_usage(context: PluginContext) -> None:
    """用量通道（T1.7）：采集增量用量 → 上报（采集器当前占位返空）。"""
    usage = await collect_usage(context)
    await _send(context, device={}, agents=[], usage=usage)


async def _send(
    context: PluginContext, *, device: dict, agents: list, usage: list
) -> None:
    """通道公共尾部：红灯检查 → 上报 → 异常分类。

    - 红灯（3.7 吊销/失效）：本轮直接跳过，循环存活等重新绑定；
    - UploadStopped：吊销确认（红灯已由 uploader 写入），记 info 不抛错；
    - UploadRetryable / 其他异常：继续上抛 → _channel_loop 记 warning
      后下个周期重试（3.7 容错与降级链）。
    """
    if await reporting_stopped(context):
        return
    try:
        await send_report(context, device=device, agents=agents, usage=usage)
    except UploadStopped as exc:
        try:
            context.logger.info(
                "deptagent-link reporting stopped", fields={"reason": str(exc)}
            )
        except StaleContextError:
            return
