"""运行配置（SPEC 10.1：机密一律环境变量注入，不入库不入 git）。"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Settings:
    db_path: str
    jwt_secret: str
    jwt_ttl_hours: int = 12  # SPEC 10.1：JWT HS256、12h 有效期、无 refresh
    login_max_failures: int = 5  # SPEC 12 章"管理账号共享"对策：密码策略 + 失败锁定
    login_lock_minutes: int = 15
    bind_rate_limit_per_minute: int = 10  # SPEC 8.2/10.1：/api/v1/bind IP 限速（防邀请码枚举）
    console_dist: str | None = None  # 管理控制台构建产物目录（T0.8，缺省自动探测）


def load_settings(env: dict[str, str] | None = None) -> Settings:
    """从环境变量读取配置；env 参数供测试注入。"""
    source = dict(os.environ) if env is None else env
    return Settings(
        db_path=source.get("DEPTAGENT_DB_PATH", "deptagent.db"),
        # 未显式注入时每次启动随机生成：进程重启后所有 JWT 失效、强制重新登录
        # （安全缺省；生产部署必须设置 DEPTAGENT_JWT_SECRET，见 SPEC 10.1）
        jwt_secret=source.get("DEPTAGENT_JWT_SECRET") or secrets.token_urlsafe(32),
        console_dist=source.get("DEPTAGENT_CONSOLE_DIST"),
    )


def with_overrides(settings: Settings, **changes: object) -> Settings:
    """返回替换部分字段的副本（CLI --db 等场景）。"""
    return replace(settings, **changes)  # type: ignore[arg-type]
