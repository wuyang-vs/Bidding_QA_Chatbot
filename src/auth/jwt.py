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


# 角色常量
ROLE_ADMIN = "admin"          # 管理员: 全部
ROLE_AUDITOR = "auditor"      # 评标专家/审计员: 审查与评审意见
ROLE_PURCHASER = "purchaser"  # 招标人: 自己的项目 + 公开文档
ROLE_BIDDER = "bidder"        # 投标人: 仅公开文档 + 自查工具, 禁评审意见/围串标

# 自助注册允许选择的角色 (不允许自封 admin/auditor)
SELF_REGISTER_ROLES = {ROLE_BIDDER, ROLE_PURCHASER}


def require_roles(*roles: str, allow_anonymous: bool = True):
    """生成一个 FastAPI 依赖, 做角色访问控制.

    - 匿名(无 token): allow_anonymous=True 时放行并返回 None (保持免登录兼容);
      False 时 401。
    - 已登录但角色不在 roles 中: 403。
    - 通过则返回当前用户 dict。
    """
    async def _dep(
        user: dict[str, Any] | None = Depends(get_current_user),
    ) -> dict[str, Any] | None:
        if user is None:
            if allow_anonymous:
                return None
            raise HTTPException(status_code=401, detail="未登录或登录已过期")
        if roles and user.get("role") not in roles:
            raise HTTPException(
                status_code=403,
                detail=f"当前角色「{user.get('role')}」无权访问该功能")
        return user
    return _dep
