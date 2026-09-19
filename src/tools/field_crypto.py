"""R10: 企业资料敏感字段应用层加密 (Fernet, 密钥派生自 auth_secret)。

设计:
- 敏感字段 bank_account / contact_phone / contact_email / legal_person 入库前加密,
  读取后解密, 业务侧(get_profile)拿到明文, 端点层再掩码展示。
- 向后兼容: 历史明文数据 is_encrypted()=False 时原样返回, 下次 PUT 自动加密。
- 密钥: PBKDF2HMAC(auth_secret, salt=b"bid-profile-v1", 100k iter) → 32B → Fernet。
"""
from __future__ import annotations

import base64
import logging

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

SENSITIVE_FIELDS = ("bank_account", "contact_phone", "contact_email", "legal_person")

_SALT = b"bid-profile-v1"
_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet
    from src.config import settings
    secret = settings.auth_secret or "dev-change-me-in-prod-secret-key"
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32, salt=_SALT, iterations=100_000)
    key = base64.urlsafe_b64encode(kdf.derive(secret.encode("utf-8")))
    _fernet = Fernet(key)
    return _fernet


def is_encrypted(value: str) -> bool:
    """判断字符串是否为 Fernet 密文 (以 gAAAAA 开头且能解出)。"""
    if not value or not isinstance(value, str):
        return False
    if not value.startswith("gAAAAA"):
        return False
    try:
        _get_fernet().decrypt(value.encode("utf-8"))
        return True
    except (InvalidToken, Exception):
        return False


def encrypt_field(plaintext: str) -> str:
    """加密; 空串/已密文原样返回, 避免二次加密。"""
    if not plaintext:
        return plaintext
    if is_encrypted(plaintext):
        return plaintext
    try:
        return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")
    except Exception as e:
        logger.warning("敏感字段加密失败, 按明文存储: %s", e)
        return plaintext


def decrypt_field(ciphertext: str) -> str:
    """解密; 非密文(历史明文)原样返回, 向后兼容。"""
    if not ciphertext or not isinstance(ciphertext, str):
        return ciphertext
    if not ciphertext.startswith("gAAAAA"):
        return ciphertext
    try:
        return _get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except (InvalidToken, Exception) as e:
        logger.warning("敏感字段解密失败, 返回原值: %s", e)
        return ciphertext


def encrypt_sensitive(profile: dict) -> dict:
    """对敏感字段加密后返回新 dict (供 upsert 入库)。"""
    out = dict(profile)
    for f in SENSITIVE_FIELDS:
        if f in out and isinstance(out[f], str):
            out[f] = encrypt_field(out[f])
    return out


def decrypt_sensitive(profile: dict) -> dict:
    """对敏感字段解密后返回新 dict (供 get_profile 返回明文)。"""
    out = dict(profile)
    for f in SENSITIVE_FIELDS:
        if f in out and isinstance(out[f], str):
            out[f] = decrypt_field(out[f])
    return out


def mask_value(field: str, value: str) -> str:
    """掩码展示: 保留后 4 位/首字符等, 用于 GET 端点返回。"""
    if not value:
        return ""
    if field == "bank_account":
        return "*" * (len(value) - 4) + value[-4:] if len(value) > 4 else "*" * len(value)
    if field == "contact_phone":
        if len(value) > 7:
            return value[:3] + "*" * (len(value) - 7) + value[-4:]
        return "*" * len(value)
    if field == "contact_email":
        if "@" in value:
            local, domain = value.split("@", 1)
            return (local[0] + "***@" + domain) if local else ("***@" + domain)
        return "*" * len(value)
    if field == "legal_person":
        return value[0] + "*" * (len(value) - 1) if len(value) > 1 else value
    return value


def mask_profile(profile: dict) -> dict:
    """对敏感字段掩码后返回新 dict (供 GET /api/profile 展示用)。"""
    out = dict(profile)
    for f in SENSITIVE_FIELDS:
        if f in out and isinstance(out[f], str):
            out[f] = mask_value(f, out[f])
    return out
