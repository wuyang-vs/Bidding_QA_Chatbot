"""R10: 企业资料敏感字段应用层加密 (Fernet, 支持多版本密钥轮换)。

设计:
- 敏感字段 bank_account / contact_phone / contact_email / legal_person 入库前加密,
  读取后解密, 业务侧(get_profile)拿到明文, 端点层再掩码展示。
- 密钥来源 (优先级):
  1. 环境变量 PROFILE_ENC_KEYS: 逗号分隔的多个 Fernet key,
     **第一个为当前加密密钥**, 其余为历史密钥 (仅用于解密旧密文) → 支持轮换;
  2. 未配置时回退由 AUTH_SECRET 经 PBKDF2HMAC 派生的单一密钥 (存量密文零迁移)。
- 轮换流程:
  a. python -m src.tools.field_crypto gen-key  # 生成新 key
  b. PROFILE_ENC_KEYS="<新key>,<旧key或留空由派生key兜底>" 重启
  c. python -m src.tools.field_crypto rotate     # 批量重加密全表到新 key
  (不执行 c 也会在用户下次 PUT 时惰性重加密)
"""
from __future__ import annotations

import base64
import logging
import sys

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

SENSITIVE_FIELDS = ("bank_account", "contact_phone", "contact_email", "legal_person")

_SALT = b"bid-profile-v1"
# key 列表缓存: [Fernet...], 第一个是当前加密密钥
_fernet_keys: list[Fernet] | None = None


def generate_key() -> str:
    """生成一个新的 Fernet 密钥 (urlsafe-base64 字符串), 供轮换时写入 PROFILE_ENC_KEYS。"""
    return Fernet.generate_key().decode("utf-8")


def _derived_fernet() -> Fernet:
    """由 auth_secret 经 PBKDF2 派生的兜底密钥 (V1.6 存量密文使用)。"""
    from src.config import settings
    secret = settings.auth_secret or "dev-change-me-in-prod-secret-key"
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32, salt=_SALT, iterations=100_000)
    key = base64.urlsafe_b64encode(kdf.derive(secret.encode("utf-8")))
    return Fernet(key)


def _load_keys() -> list[Fernet]:
    """加载密钥链: PROFILE_ENC_KEYS 显式密钥优先, 否则回退 auth_secret 派生密钥。"""
    from src.config import settings
    raw = (settings.profile_enc_keys or "").strip()
    if not raw:
        return [_derived_fernet()]
    keys: list[Fernet] = []
    for i, part in enumerate(raw.split(",")):
        part = part.strip()
        if not part:
            continue
        try:
            keys.append(Fernet(part.encode("utf-8")))
        except (ValueError, TypeError) as e:
            logger.warning("PROFILE_ENC_KEYS 第 %d 个密钥非法, 已跳过: %s", i, e)
    if not keys:
        logger.warning("PROFILE_ENC_KEYS 配置了但无有效密钥, 回退 auth_secret 派生密钥")
        return [_derived_fernet()]
    return keys


def _get_keys() -> list[Fernet]:
    global _fernet_keys
    if _fernet_keys is None:
        _fernet_keys = _load_keys()
    return _fernet_keys


def reload_keys() -> int:
    """重新从配置加载密钥链 (轮换脚本/测试用), 返回密钥数量。"""
    global _fernet_keys
    _fernet_keys = _load_keys()
    return len(_fernet_keys)


def _multi() -> MultiFernet:
    return MultiFernet(_get_keys())


def is_encrypted(value: str) -> bool:
    """判断字符串是否为密钥链中任一密钥产生的 Fernet 密文。"""
    if not value or not isinstance(value, str) or not value.startswith("gAAAAA"):
        return False
    for f in _get_keys():
        try:
            f.decrypt(value.encode("utf-8"))
            return True
        except InvalidToken:
            continue
        except Exception:
            continue
    return False


def encrypt_field(plaintext: str) -> str:
    """用当前(第一个)密钥加密; 空串/已密文原样返回, 避免二次加密。"""
    if not plaintext:
        return plaintext
    if is_encrypted(plaintext):
        return plaintext
    try:
        return _multi().encrypt(plaintext.encode("utf-8")).decode("utf-8")
    except Exception as e:
        logger.warning("敏感字段加密失败, 按明文存储: %s", e)
        return plaintext


def decrypt_field(ciphertext: str) -> str:
    """按密钥链顺序解密; 非密文(历史明文)原样返回, 向后兼容。"""
    if not ciphertext or not isinstance(ciphertext, str):
        return ciphertext
    if not ciphertext.startswith("gAAAAA"):
        return ciphertext
    try:
        return _multi().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except (InvalidToken, Exception) as e:
        logger.warning("敏感字段解密失败, 返回原值: %s", e)
        return ciphertext


def key_index(ciphertext: str) -> int | None:
    """返回能解开该密文的密钥下标; 非密文/全部失败返回 None。0=当前密钥。"""
    if not ciphertext or not isinstance(ciphertext, str) or not ciphertext.startswith("gAAAAA"):
        return None
    for i, f in enumerate(_get_keys()):
        try:
            f.decrypt(ciphertext.encode("utf-8"))
            return i
        except InvalidToken:
            continue
        except Exception:
            continue
    return None


def needs_rotation(value: str) -> bool:
    """密文是否由历史(非当前)密钥加密 → 需要重加密。非密文/当前密钥 → False。"""
    idx = key_index(value)
    return idx is not None and idx > 0


def rotate_value(value: str) -> tuple[str, bool]:
    """把历史密钥密文重加密为当前密钥; 返回 (新值, 是否发生重加密)。"""
    idx = key_index(value)
    if idx is None or idx == 0:
        return value, False
    plaintext = _get_keys()[idx].decrypt(value.encode("utf-8")).decode("utf-8")
    return _get_keys()[0].encrypt(plaintext.encode("utf-8")).decode("utf-8"), True


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


def rotate_all_profiles(dry_run: bool = False) -> dict:
    """批量把全表敏感字段重加密为当前密钥 (密钥轮换收尾步骤)。

    Returns:
        {scanned: 用户行数, rotated_users: 发生重加密的用户数,
         rotated_fields: 重加密字段总数, skipped: 明文/当前密钥跳过字段数,
         dry_run: bool}
    """
    from src.database.postgresql_client import postgresql_client
    if not postgresql_client.ready:
        postgresql_client.initialize()
    rows = postgresql_client._run(
        f"SELECT user_id, {', '.join(SENSITIVE_FIELDS)} FROM company_profiles")
    result = {"scanned": len(rows), "rotated_users": 0,
              "rotated_fields": 0, "skipped": 0, "dry_run": dry_run}
    for row in rows:
        uid = row["user_id"]
        updates: dict[str, str] = {}
        for f in SENSITIVE_FIELDS:
            val = row.get(f) or ""
            if not val:
                continue
            new_val, rotated = rotate_value(val)
            if rotated:
                updates[f] = new_val
            else:
                result["skipped"] += 1
        if not updates:
            continue
        result["rotated_users"] += 1
        result["rotated_fields"] += len(updates)
        if not dry_run:
            sets = ", ".join(f"{k}=:{k}" for k in updates)
            params = dict(updates)
            params["uid"] = uid
            postgresql_client._run(
                f"UPDATE company_profiles SET {sets}, updated_at=NOW() WHERE user_id=:uid",
                params)
            logger.info("密钥轮换: user_id=%s 重加密字段=%s", uid, list(updates.keys()))
    # R12: 实际轮换 (非 dry-run) 落一条 system 审计, 仅统计数字不含任何密文/明文
    if not dry_run and result["rotated_fields"]:
        from src.tools.audit_log import record_audit, ACTION_KEY_ROTATE
        record_audit(
            user_id=None, username="system", action=ACTION_KEY_ROTATE,
            target_type="company_profiles",
            detail=(f"scanned={result['scanned']};rotated_users="
                    f"{result['rotated_users']};rotated_fields="
                    f"{result['rotated_fields']};skipped={result['skipped']}"))
    return result


def _cli(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "gen-key":
        print(generate_key())
        print("# 将其放到 PROFILE_ENC_KEYS 的第一位 (当前密钥), 旧密钥放后面用逗号分隔",
              file=sys.stderr)
        return 0
    if cmd == "rotate":
        dry = "--dry-run" in argv[2:]
        n = reload_keys()
        print(f"已加载 {n} 个密钥 (第 1 个为当前加密密钥), dry_run={dry}")
        stats = rotate_all_profiles(dry_run=dry)
        print(stats)
        return 0
    if cmd == "status":
        n = reload_keys()
        print(f"密钥链长度: {n} (第 1 个=当前加密密钥)")
        return 0
    print("用法: python -m src.tools.field_crypto [gen-key|rotate [--dry-run]|status]")
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv))
