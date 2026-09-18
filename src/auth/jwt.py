"""JWT 签发/校验 + FastAPI Depends + 密码哈希."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from fastapi import Depends, HTTPException, Request
from jose import JWTError, jwt

from src.config import settings

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    """bcrypt 哈希密码, 返回 $2b$ 开头的字符串."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


def create_access_token(subject: str | int, extra: dict[str, Any] | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.auth_expire_minutes)).timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.auth_secret, algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.auth_secret, algorithms=[ALGORITHM])
    except JWTError as e:
        logger.debug("JWT decode failed: %s", e)
        return None


async def get_current_user(request: Request) -> dict[str, Any] | None:
    """从 Authorization: Bearer <token> 解析当前用户. 无 token 返回 None."""
    auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:].strip()
    payload = decode_token(token)
    if not payload or not payload.get("sub"):
        return None
    # 查库拿完整用户信息
    try:
        from src.database.postgresql_client import postgresql_client
        uid = payload.get("uid") or int(payload["sub"])
        rows = postgresql_client._run(
            "SELECT id, username, role, display_name FROM users WHERE id=:id", {"id": uid})
        if rows:
            return dict(rows[0])
    except Exception as e:
        logger.warning("查 user 失败: %s", e)
    # 降级: 直接从 payload 返回最小用户信息 (避免因 DB 不通而完全阻断)
    return {
        "id": int(payload["sub"]),
        "username": payload.get("username", ""),
        "role": payload.get("role", "auditor"),
        "display_name": payload.get("display_name", ""),
    }


async def get_current_user_required(
    request: Request,
    user: dict[str, Any] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """必须登录, 否则 401."""
    if not user:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    return user


async def get_current_user_optional(
    user: dict[str, Any] | None = Depends(get_current_user),
) -> dict[str, Any] | None:
    """可选登录, 有 token 就返回用户, 没有返回 None."""
    return user
