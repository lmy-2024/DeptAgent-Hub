"""时间口径（SPEC 10.1：时间戳一律 UTC ISO 8601）。"""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now_iso() -> str:
    """当前时刻的 UTC ISO 8601 字符串（秒级）。"""
    return datetime.now(UTC).isoformat(timespec="seconds")
