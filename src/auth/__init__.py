"""鉴权模块 — JWT 签发/校验 + 密码哈希 + FastAPI Depends."""
from .jwt import (
    hash_password,
    verify_password,
    create_access_token,
    decode_token,
    get_current_user,
    get_current_user_optional,
    get_current_user_required,
)

__all__ = [
    "hash_password",
    "verify_password",
    "create_access_token",
    "decode_token",
    "get_current_user",
    "get_current_user_optional",
    "get_current_user_required",
]
