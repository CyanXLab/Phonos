"""FastAPI 依赖注入：当前用户、数据库会话。"""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header, HTTPException, Request, status

from ..core.config import get_settings
from ..core.logging import bind_user, get_logger
from ..core.security import generate_token


# 兼容旧 auth_service 的桥接器
def get_current_user_v2(request: Request) -> dict:
    """新版 get_current_user，写入 request_id/user_id 到日志上下文。"""
    from auth_service import get_auth_service  # 兼容旧实现

    auth_header = request.headers.get("Authorization", "")
    token = ""
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    auth = get_auth_service()
    user = auth.get_user_by_token(token)
    if user and user.get("id"):
        bind_user(user["id"])
    return user


def require_user(request: Request) -> dict:
    """强制要求登录（无 default 兜底）。

    拒绝：
    - 无 token
    - 伪造 token
    - default/guest 兜底用户
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    token = auth_header[7:]
    if not token or len(token) < 10:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )
    user = get_current_user_v2(request)
    if not user or not user.get("id") or user.get("id") in ("default", "guest"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return user


def require_admin(request: Request) -> dict:
    """要求管理员。"""
    user = require_user(request)
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin required")
    return user
