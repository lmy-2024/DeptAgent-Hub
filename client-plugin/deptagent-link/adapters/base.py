# -*- coding: utf-8 -*-
"""适配层公共接口（SPEC 3.12 adapters/base.py）：Reader 协议 + 格式探测/降级判定。

- working_dir()：宿主工作目录定位，优先级复刻宿主源码 constant.py
  （QWENPAW_WORKING_DIR env > ~/.copaw 旧装 > ~/.qwenpaw）——不 import
  宿主内部模块（3.12 运行时纪律第 5 条：公共 SDK 类型只从
  qwenpaw.plugins.* 导入）；
- AgentReader：数据读取协议（2.3 实现见 qwenpaw_2_3.py；T1.7 扩展
  read_usage）；
- detect_format()：降级判定——探测失败返回 (None, None)，采集器据此
  返回空数据、心跳 format_probe=None（服务端 COALESCE 不覆盖旧值，
  降级留痕见 SPEC 7 章 last_format_probe 注释）。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol


def working_dir() -> Path:
    """宿主工作目录（优先级同 QwenPaw 源码 constant.py WORKING_DIR）。"""
    explicit = os.environ.get("QWENPAW_WORKING_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve()
    legacy = Path("~/.copaw").expanduser()
    if legacy.exists():
        return legacy.resolve()
    return Path("~/.qwenpaw").expanduser().resolve()


class AgentReader(Protocol):
    """本地数据 Reader 协议（格式族自描述）。"""

    def probe_format(self) -> str | None:
        """探测本机数据格式族；不匹配返回 None。"""
        ...

    def read_agents(self) -> list[dict]:
        """读智能体台账清单（3.4 ②字段：agent_key/name/description/status）。"""
        ...


def detect_format() -> tuple[str | None, AgentReader | None]:
    """格式探测 + 降级判定：返回 (格式族标签, Reader)。

    逐适配器探测（当前唯一格式族 qwenpaw-2.3，见 qwenpaw_2_3.py）；
    全部不匹配 → (None, None)，采集器返回空（3.7 容错降级）。
    """
    from .qwenpaw_2_3 import QwenPaw23Reader

    reader = QwenPaw23Reader()
    fmt = reader.probe_format()
    if fmt is not None:
        return fmt, reader
    return None, None
