"""api 层：路由（SPEC 13.1 routers: auth / accounts / …阶段 1 起 bind / telemetry / admin）。"""

from . import accounts, auth

__all__ = ["accounts", "auth"]
