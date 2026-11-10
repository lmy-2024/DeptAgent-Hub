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
  绑定后自动恢复，采集器/uploader 每轮重新读 binding）；
- 员工暂停（3.4 隐私红线）：台账/用量通道停发，心跳继续（携带
  reporting_paused 开关上报，服务端置位、驾驶舱离线告警排除）。

面板（3.8）配套：通道元数据 CHANNEL_META、今日已上报快照
（today_report，3.4 透明展示数据源）、手动同步入口 run_manual_sync。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Awaitable, Callable

from qwenpaw.plugins import PluginContext, StaleContextError

import config
import state
from collectors.agents import collect_agents
from collectors.heartbeat import collect_heartbeat
from collectors.usage import collect_usage, commit_usage_watermark
from config import STORAGE_FILES
from uploader import UploadStopped, employee_paused, reporting_stopped, send_report

# 拍板 D2（2026-11-10）：用量 / 台账 / 心跳 = 5 / 15 / 5 min
USAGE_INTERVAL_SECONDS = 5 * 60
AGENTS_INTERVAL_SECONDS = 15 * 60
HEARTBEAT_INTERVAL_SECONDS = 5 * 60

# 通道元数据（面板 3.8 状态卡：展示名 + 周期分钟数；panel.py 复用）
CHANNEL_META: dict[str, tuple[str, int]] = {
    "heartbeat": ("心跳", HEARTBEAT_INTERVAL_SECONDS // 60),
    "agents": ("智能体台账", AGENTS_INTERVAL_SECONDS // 60),
    "usage": ("Token 用量", USAGE_INTERVAL_SECONDS // 60),
}


class SyncBusyError(Exception):
    """手动同步已在进行中（面板 3.8「立即同步」防抖）。"""


_MANUAL_SYNC_LOCK = asyncio.Lock()


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

    channels: tuple[tuple[str, float, Callable[[PluginContext], Awaitable[str]]], ...] = (
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
    action: Callable[[PluginContext], Awaitable[str]],
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


async def run_manual_sync(context: PluginContext) -> dict[str, str]:
    """面板「立即同步」（3.8）：三通道立即各执行一轮。

    语义与周期循环完全一致（员工暂停跳过台账/用量、红灯停报）；
    与周期任务的并发安全由 state 文件锁 + seq 锁 + 服务端 UPSERT
    幂等保证。返回各通道状态（ok / skipped_* / failed: …）。
    """
    if _MANUAL_SYNC_LOCK.locked():
        raise SyncBusyError("同步已在进行中，请稍候")
    async with _MANUAL_SYNC_LOCK:
        results: dict[str, str] = {}
        for name, action in (
            ("heartbeat", _run_heartbeat),
            ("agents", _run_agents),
            ("usage", _run_usage),
        ):
            try:
                results[name] = await action(context)
            except StaleContextError:
                raise
            except Exception as exc:  # noqa: BLE001 - 单通道失败不拖垮整轮
                results[name] = f"failed: {exc}"
        return results


async def _touch_watermark(context: PluginContext, channel: str) -> None:
    """记录通道本轮执行时间（watermark.channels 子键）。

    修复（T1.13）：旧实现直接写 watermark[channel]，与 usage 通道的
    按日指纹（collectors.usage.commit_usage_watermark 写
    watermark["usage"]）互相覆盖——指纹被时间戳顶掉后下一轮
    collect_usage 对字符串调 .get 抛 AttributeError，用量通道从此
    静默失败。通道执行时间统一收纳到 channels 子键并持锁写。
    """
    stamp = _now_iso()

    def mutate(watermark: dict) -> None:
        channels = watermark.get("channels")
        if not isinstance(channels, dict):
            channels = {}
            watermark["channels"] = channels
        channels[channel] = stamp

    await state.update_json(context, "watermark", mutate)


async def _record_today(context: PluginContext, **fields: object) -> None:
    """记录/合并「今日已上报」快照（3.4 透明展示数据源；跨日自动重置）。

    日期口径与 usage stat_date 一致（员工本地日期）；面板（3.8）直接
    读取展示，员工可见"本机今日已上报内容"。
    """
    today = datetime.now().strftime("%Y-%m-%d")

    def mutate(report: dict) -> None:
        if report.get("date") != today:
            report.clear()
            report["date"] = today
        report.update(fields)

    await state.update_json(context, "today_report", mutate)


async def _run_heartbeat(context: PluginContext) -> str:
    """心跳通道（T1.5）：采集设备快照 → 上报（agents/usage 段为空）。

    暂停不跳过心跳（3.4）：开关状态须随心跳上报给服务端。
    """
    device = await collect_heartbeat(context)
    if await _send(context, device=device, agents=[], usage=[]):
        await _record_today(context, heartbeat_sent_at=_now_iso())
        return "ok"
    return "skipped_stopped"  # 红灯/吊销（3.7 正常停报状态）


async def _run_agents(context: PluginContext) -> str:
    """台账通道（T1.6）：采集智能体快照 → 上报（采集器当前占位返空）。"""
    if await employee_paused(context):
        return "skipped_paused"
    agents = await collect_agents(context)
    if await _send(context, device={}, agents=agents, usage=[]):
        await _record_today(context, agents_count=len(agents), agents_sent_at=_now_iso())
        return "ok"
    return "skipped_stopped"


async def _run_usage(context: PluginContext) -> str:
    """用量通道（T1.7）：采集增量用量 → 上报 → 成功后提交按日指纹水位。

    增量算法（SPEC 3.6）：当日全量重传（服务端 UPSERT 覆盖）、历史日
    仅指纹变化时重传；水位纪律：上报成功才 commit——失败/红灯不动
    水位，下轮自动重传（丢数据风险 < 重复上报的幂等覆盖）；本地无新
    数据本轮静默（在线信号由心跳通道维持）。
    """
    if await employee_paused(context):
        return "skipped_paused"
    usage, fingerprints = await collect_usage(context)
    if not usage:
        return "skipped_no_data"
    if await _send(context, device={}, agents=[], usage=usage):
        await commit_usage_watermark(context, fingerprints)
        # 今日已上报快照（3.4 透明展示）：只记当日行（历史日回灌不属于"今日"）
        today = datetime.now().strftime("%Y-%m-%d")
        today_rows = [row for row in usage if row.get("stat_date") == today]
        await _record_today(
            context,
            usage_rows=today_rows,
            usage_tokens=_tokens_of(today_rows),
            usage_sent_at=_now_iso(),
        )
        return "ok"
    return "skipped_stopped"


async def _send(
    context: PluginContext, *, device: dict, agents: list, usage: list
) -> bool:
    """通道公共尾部：红灯检查 → 上报 → 异常分类；返回是否上报成功。

    - 红灯（3.7 吊销/失效）：本轮直接跳过，循环存活等重新绑定；
    - UploadStopped：吊销确认（红灯已由 uploader 写入），记 info 不抛错；
    - UploadRetryable / 其他异常：继续上抛 → _channel_loop 记 warning
      后下个周期重试（3.7 容错与降级链）；
    - 返回 False（红灯/吊销停报）：用量通道不提交增量水位（3.6：下轮
      自动重传），心跳/台账通道忽略返回值。
    """
    if await reporting_stopped(context):
        return False
    try:
        await send_report(context, device=device, agents=agents, usage=usage)
    except UploadStopped as exc:
        try:
            context.logger.info(
                "deptagent-link reporting stopped", fields={"reason": str(exc)}
            )
        except StaleContextError:
            return False
        return False
    return True


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


_TOKEN_FIELDS = (
    "prompt_tokens",
    "completion_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
)


def _tokens_of(rows: list[dict]) -> int:
    """今日已上报 token 总数（六项计数中四个 token 字段之和）。"""
    total = 0
    for row in rows:
        for field in _TOKEN_FIELDS:
            value = row.get(field, 0) or 0
            total += value if isinstance(value, int) else 0
    return total
