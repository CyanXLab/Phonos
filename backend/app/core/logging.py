"""结构化日志（structlog）。

特性：
- JSON 格式（生产） / 彩色控制台（开发）
- request_id 中间件绑定
- 关键事件：model_load, evaluate_start, evaluate_done, fsrs_fit, exam_submit
- 兼容旧 print 调用：通过日志桥接器
"""

from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar
from typing import Any

import structlog

from .config import get_settings


# 请求级上下文
request_id_var: ContextVar[str] = ContextVar("request_id", default="")
user_id_var: ContextVar[str] = ContextVar("user_id", default="")


def _add_contextvars(_: Any, __: Any, event_dict: dict) -> dict:
    rid = request_id_var.get()
    if rid:
        event_dict["request_id"] = rid
    uid = user_id_var.get()
    if uid:
        event_dict["user_id"] = uid
    return event_dict


def _drop_color_message(_, __, event_dict: dict) -> dict:
    """移除 structlog 自带的 color_message 键（避免污染 JSON）。"""
    event_dict.pop("color_message", None)
    return event_dict


def configure_logging() -> None:
    """配置 structlog 与标准 logging 桥接。"""
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # 共享处理器
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=False),
        _add_contextvars,
        _drop_color_message,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.log_format == "json" or settings.is_production:
        renderer = structlog.processors.JSONRenderer(ensure_ascii=False)
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    # 标准 logging 桥接（兼容第三方库）
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # 拦截旧 print：可选，默认不开（避免破坏 stdout 抓取）
    # 如需启用：sys.stdout = _PrintInterceptor(sys.stdout)


def get_logger(name: str = "phonos") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


def new_request_id() -> str:
    rid = uuid.uuid4().hex[:16]
    request_id_var.set(rid)
    return rid


def bind_user(user_id: str) -> None:
    user_id_var.set(user_id)
