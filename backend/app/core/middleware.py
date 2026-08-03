"""FastAPI 中间件：request_id、CORS 收紧、错误处理、访问日志。"""

from __future__ import annotations

import time
import uuid
from typing import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .logging import get_logger, new_request_id, request_id_var


class RequestIDMiddleware(BaseHTTPMiddleware):
    """为每个请求注入 request_id 并写入响应头。"""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]):
        rid = request.headers.get("X-Request-ID") or new_request_id()
        request_id_var.set(rid)
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response


class AccessLogMiddleware(BaseHTTPMiddleware):
    """访问日志：method/path/status/duration_ms。"""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        dur_ms = (time.perf_counter() - start) * 1000.0
        get_logger("access").info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round(dur_ms, 2),
        )
        return response


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """全局错误处理：避免裸露 500 stacktrace 给客户端。"""

    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:  # noqa: BLE001
            rid = request_id_var.get() or uuid.uuid4().hex[:16]
            get_logger("error").exception(
                "unhandled_exception",
                error=str(exc),
                error_type=type(exc).__name__,
                path=request.url.path,
            )
            return JSONResponse(
                status_code=500,
                content={
                    "detail": "Internal Server Error",
                    "request_id": rid,
                    "type": type(exc).__name__,
                },
            )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """添加 HTTP 安全头。"""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Powered-By"] = "Phonos"
        return response
