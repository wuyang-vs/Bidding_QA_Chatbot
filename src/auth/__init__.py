"""鉴权模块 — JWT 签发/校验 + 密码哈希 + FastAPI Depends + 角色控制."""
from .jwt import (
    hash_password,
    verify_password,
    create_access_token,
    decode_token,
    get_current_user,
    get_current_user_optional,
    get_current_user_required,
    require_roles,
    ROLE_ADMIN,
    ROLE_AUDITOR,
    ROLE_PURCHASER,
    ROLE_BIDDER,
    SELF_REGISTER_ROLES,
)

__all__ = [
    "hash_password",
    "verify_password",
    "create_access_token",
    "decode_token",
    "get_current_user",
    "get_current_user_optional",
    "get_current_user_required",
    "require_roles",
    "ROLE_ADMIN",
    "ROLE_AUDITOR",
    "ROLE_PURCHASER",
    "ROLE_BIDDER",
    "SELF_REGISTER_ROLES",
]
