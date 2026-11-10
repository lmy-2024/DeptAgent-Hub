"""统一错误响应（SPEC 8.5：{"error": {code, message, detail}}）。

code 枚举基线 = SPEC 8.5：token_revoked / token_invalid（401）、auth_failed（401）、
forbidden_role（403）、invite_invalid / invite_expired（400）、seq_conflict（409）、
quota_exceeded（429）、validation_error（422）。
本模块另补充账号治理闭环所必需的三个 code（8.5 为"常用枚举"非穷尽）：
not_found（404）、account_exists（409）、target_protected（400）。
"""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse


class ApiError(Exception):
    """业务错误：携带 HTTP 状态码与 8.5 风格的错误 code。"""

    def __init__(self, status_code: int, code: str, message: str, detail: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.detail = detail


def error_body(code: str, message: str, detail: Any = None) -> dict[str, Any]:
    """构造 8.5 统一格式的错误响应体。"""
    return {
        "error": {"code": code, "message": message, "detail": detail if detail is not None else {}}
    }


def error_response(exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(exc.code, exc.message, exc.detail),
    )
