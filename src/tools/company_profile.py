"""企业资料库: 账号 1:1 公司档案 + 标书占位符自动回填。

- PG 表 company_profiles (由 postgresql_client 启动时建表)
- get_profile / upsert_profile: CRUD
- profile_prompt_block: 注入标书生成 prompt, 让 LLM 直接使用真实企业信息
- apply_profile_placeholders: 生成后二次回填, 并汇总未填占位符
- fill_placeholders_stream: 流式增量回填 (跨 chunk 的 [占位符] 缓冲处理)
"""
from __future__ import annotations

import json
import logging
import re
from typing import Iterator

logger = logging.getLogger(__name__)

# ---- 档案字段 ----
PROFILE_FIELDS = (
    "company_name", "company_short", "address", "legal_person",
    "registered_capital", "established_date", "contact_person",
    "contact_phone", "contact_email", "bank_name", "bank_account",
    "business_scope",
)
JSON_FIELDS = ("certs", "past_projects")

# certs/past_projects 列表项允许的键 (白名单, 过滤前端塞入的其他内容)
CERT_KEYS = ("name", "level", "cert_no", "valid_until",
             "file_token", "file_name", "ocr_text")
PROJECT_KEYS = ("name", "owner", "amount", "date", "role")

EMPTY_PROFILE: dict = {f: "" for f in PROFILE_FIELDS}
EMPTY_PROFILE.update({"certs": [], "past_projects": []})

# ---- 占位符 → 档案字段 (精确匹配) ----
_PLACEHOLDER_FIELD: dict[str, str] = {
    "[公司全称]": "company_name",
    "[投标人全称]": "company_name",
    "[投标人名称]": "company_name",
    "[公司名称]": "company_name",
    "[公司简称]": "company_short",
    "[公司地址]": "address",
    "[注册地址]": "address",
    "[地址]": "address",
    "[法定代表人]": "legal_person",
    "[法人代表]": "legal_person",
    "[法人姓名]": "legal_person",
    "[注册资金]": "registered_capital",
    "[注册资本]": "registered_capital",
    "[成立日期]": "established_date",
    "[联系人]": "contact_person",
    "[联系电话]": "contact_phone",
    "[电话]": "contact_phone",
    "[电子邮箱]": "contact_email",
    "[邮箱]": "contact_email",
    "[开户银行]": "bank_name",
    "[银行账号]": "bank_account",
    "[开户行账号]": "bank_account",
}

# 属于"企业资料可填但档案里为空"的占位符标签 (用于缺失提示)
_COMPANY_LABELS = (
    "公司全称", "投标人全称", "投标人名称", "公司名称", "公司简称", "公司地址",
    "注册地址", "地址", "法定代表人", "法人代表", "法人姓名", "注册资金",
    "注册资本", "成立日期", "联系人", "联系电话", "电话", "电子邮箱", "邮箱",
    "开户银行", "银行账号", "开户行账号", "资质证书编号",
)

_BRACKET_RE = re.compile(r"\[([^\[\]\n]{1,40})\]")


def _norm(profile: dict | None) -> dict:
    p = dict(EMPTY_PROFILE)
    if profile:
        for f in PROFILE_FIELDS:
            v = profile.get(f)
            if v is not None:
                p[f] = str(v)
        if isinstance(profile.get("certs"), list):
            p["certs"] = _norm_items(profile["certs"], CERT_KEYS)
        if isinstance(profile.get("past_projects"), list):
            p["past_projects"] = _norm_items(profile["past_projects"], PROJECT_KEYS)
    return p


def _norm_items(items: list, keys: tuple) -> list[dict]:
    """列表项白名单清洗: 仅保留允许键, 值统一转字符串 (空值保留空串)。"""
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        row = {k: str(it.get(k) or "").strip() for k in keys if it.get(k) not in (None, "")}
        if row:
            out.append(row)
    return out


# ---------- CRUD ----------

def get_profile(user_id: int) -> dict:
    """取账号档案; 无记录/PG 不可用时返回空骨架。敏感字段出库后解密为明文(业务用)。"""
    from src.database.postgresql_client import postgresql_client
    if not postgresql_client.ready:
        return dict(EMPTY_PROFILE)
    try:
        rows = postgresql_client._run(
            "SELECT * FROM company_profiles WHERE user_id = :uid", {"uid": user_id})
    except Exception as e:
        logger.warning("企业资料读取失败: %s", e)
        return dict(EMPTY_PROFILE)
    if not rows:
        return dict(EMPTY_PROFILE)
    row = rows[0]
    raw = {f: (row.get(f) or "") for f in PROFILE_FIELDS}
    for f in JSON_FIELDS:
        v = row.get(f)
        raw[f] = v if isinstance(v, list) else []
    # R10: 敏感字段解密为明文 (历史明文自动兼容)
    from src.tools.field_crypto import decrypt_sensitive
    raw = decrypt_sensitive(raw)
    # 过白名单归一化, 保证 certs/业绩项字段形状一致 (历史数据/新附件键兼容)
    return _norm(raw)


def upsert_profile(user_id: int, data: dict, audit_meta: dict | None = None) -> dict:
    """全量更新档案 (未提供字段置空), 返回最新档案。敏感字段入库前加密。

    audit_meta: R12 审计上下文 {username, ip, user_agent}, 由 API 层传入;
    任一字段变化时写 audit_logs (只记字段名, 含 certs/past_projects 结构性变更)。
    """
    from src.database.postgresql_client import postgresql_client
    from src.tools.field_crypto import encrypt_sensitive, SENSITIVE_FIELDS
    p = _norm(data)
    if not postgresql_client.ready:
        raise RuntimeError("PostgreSQL 未就绪")
    # R10 操作审计 + 掩码回传保护: 取旧明文, 敏感字段若为掩码(含 *)则保留旧值
    old = get_profile(user_id)
    for f in SENSITIVE_FIELDS:
        if isinstance(p.get(f), str) and "*" in p[f] and old.get(f):
            p[f] = old[f]
    changed = [f for f in PROFILE_FIELDS if (p.get(f) or "") != (old.get(f) or "")]
    certs_changed = p.get("certs") != old.get("certs")
    projects_changed = p.get("past_projects") != old.get("past_projects")
    if certs_changed:
        changed.append("certs")
    if projects_changed:
        changed.append("past_projects")
    if changed:
        logger.info("企业资料更新审计 user_id=%s changed_fields=%s", user_id, changed)
        if audit_meta:
            from src.tools.audit_log import record_audit, ACTION_PROFILE_UPDATE
            record_audit(
                user_id=user_id,
                username=audit_meta.get("username", ""),
                action=ACTION_PROFILE_UPDATE,
                target_type="company_profile",
                target_id=str(user_id),
                changed_fields=changed,
                ip=audit_meta.get("ip", ""),
                user_agent=audit_meta.get("user_agent", ""),
                detail=audit_meta.get("detail", ""))
    # R10: 敏感字段加密后入库
    p_enc = encrypt_sensitive(p)
    params: dict = {"uid": user_id}
    for f in PROFILE_FIELDS:
        params[f] = p_enc[f]
    params["certs"] = json.dumps(p["certs"], ensure_ascii=False)
    params["past_projects"] = json.dumps(p["past_projects"], ensure_ascii=False)
    cols = ", ".join(PROFILE_FIELDS)
    vals = ", ".join(f":{f}" for f in PROFILE_FIELDS)
    updates = ", ".join(f"{f}=EXCLUDED.{f}" for f in PROFILE_FIELDS)
    sql = (
        f"INSERT INTO company_profiles (user_id, {cols}, certs, past_projects, updated_at) "
        f"VALUES (:uid, {vals}, CAST(:certs AS JSONB), CAST(:past_projects AS JSONB), NOW()) "
        f"ON CONFLICT (user_id) DO UPDATE SET {updates}, "
        "certs=EXCLUDED.certs, past_projects=EXCLUDED.past_projects, updated_at=NOW()"
    )
    postgresql_client._run(sql, params)
    return get_profile(user_id)


def profile_completeness(profile: dict) -> dict:
    """档案填写完整度 (前端/端点用): 已填基础字段数与证书/业绩条数。"""
    p = _norm(profile)
    filled = [f for f in PROFILE_FIELDS if p[f].strip()]
    return {
        "filled_fields": len(filled),
        "total_fields": len(PROFILE_FIELDS),
        "certs_count": len(p["certs"]),
        "projects_count": len(p["past_projects"]),
        "missing_fields": [f for f in PROFILE_FIELDS if not p[f].strip()],
    }


# ---------- prompt 注入 ----------

def _fmt_certs(profile: dict) -> str:
    certs = profile.get("certs") or []
    lines = []
    for c in certs:
        if not isinstance(c, dict):
            continue
        name = c.get("name") or ""
        level = c.get("level") or ""
        no = c.get("cert_no") or ""
        valid = c.get("valid_until") or ""
        bits = [b for b in (name, f"等级:{level}" if level else "",
                            f"编号:{no}" if no else "",
                            f"有效期至:{valid}" if valid else "") if b]
        if bits:
            lines.append("  - " + " | ".join(bits))
    return "\n".join(lines)


def _fmt_projects(profile: dict) -> str:
    projs = profile.get("past_projects") or []
    lines = []
    for pjt in projs[:10]:
        if not isinstance(pjt, dict):
            continue
        bits = [pjt.get(k, "") for k in ("name", "owner", "amount", "date", "role")]
        line = " | ".join(str(b) for b in bits if b)
        if line:
            lines.append("  - " + line)
    return "\n".join(lines)


def profile_prompt_block(profile: dict | None) -> str:
    """注入标书 prompt 的企业资料块; 空档案返回空串。"""
    p = _norm(profile)
    if not p["company_name"].strip() and not p["certs"] and not p["past_projects"]:
        return ""
    lines = ["## 投标人企业资料 (真实信息, 正文中必须直接使用, 禁止再输出对应占位符)"]
    for label, key in (("公司全称", "company_name"), ("公司简称", "company_short"),
                       ("注册地址", "address"), ("法定代表人", "legal_person"),
                       ("注册资本", "registered_capital"), ("成立日期", "established_date"),
                       ("联系人", "contact_person"), ("联系电话", "contact_phone"),
                       ("电子邮箱", "contact_email"), ("开户银行", "bank_name"),
                       ("银行账号", "bank_account"), ("经营范围", "business_scope")):
        if p.get(key):
            lines.append(f"- {label}: {p[key]}")
    certs_text = _fmt_certs(p)
    if certs_text:
        lines.append("- 资质证书:\n" + certs_text)
    projs_text = _fmt_projects(p)
    if projs_text:
        lines.append("- 同类业绩:\n" + projs_text)
    return "\n".join(lines)


def as_company_qualifications(profile: dict | None) -> list[str]:
    """企业资料 → /api/qualification/check 需要的企业资质字符串清单。"""
    p = _norm(profile)
    out: list[str] = []
    if p["company_name"]:
        out.append(f"企业名称: {p['company_name']}")
    if p["registered_capital"]:
        out.append(f"注册资本: {p['registered_capital']}")
    if p["established_date"]:
        out.append(f"成立日期: {p['established_date']}")
    if p["business_scope"]:
        out.append(f"经营范围: {p['business_scope']}")
    for c in p["certs"]:
        if isinstance(c, dict) and c.get("name"):
            bits = [c["name"], c.get("level", ""), c.get("cert_no", ""),
                    f"有效期至:{c['valid_until']}" if c.get("valid_until") else ""]
            out.append("资质: " + " | ".join(b for b in bits if b))
    return out


# ---------- 占位符回填 ----------

def _certs_placeholder(profile: dict) -> str:
    """[资质证书编号] 的回填: 展开为档案中证书编号清单; 无证书则保持占位符。"""
    certs = [c for c in (profile.get("certs") or []) if isinstance(c, dict)]
    if not certs:
        return ""
    parts = []
    for c in certs:
        name = c.get("name") or "资质证书"
        no = c.get("cert_no") or "(编号待补)"
        level = c.get("level") or ""
        parts.append(f"{name}{('（' + level + '）') if level else ''}，编号：{no}")
    return "；".join(parts)


def _replace_token(token: str, profile: dict) -> str:
    if token in _PLACEHOLDER_FIELD:
        val = (profile.get(_PLACEHOLDER_FIELD[token]) or "").strip()
        return val if val else token
    if token == "[资质证书编号]":
        return _certs_placeholder(profile) or token
    return token


def apply_profile_placeholders(markdown: str, profile: dict | None) -> tuple[str, dict]:
    """回填正文中的占位符。

    返回 (回填后文本, {
        filled: 已回填占位符标签列表,
        missing_company: 企业资料缺失导致未填的标签,
        pending_business: 业务测算类占位 (参数/报价/项目经理等),
    })
    """
    p = _norm(profile)
    filled: list[str] = []
    missing_company: list[str] = []
    pending_business: list[str] = []

    def _sub(m: re.Match) -> str:
        token = m.group(0)
        label = m.group(1)
        new = _replace_token(token, p)
        if new != token:
            if label not in filled:
                filled.append(label)
            return new
        if label in _COMPANY_LABELS:
            if label not in missing_company:
                missing_company.append(label)
        else:
            if label not in pending_business:
                pending_business.append(label)
        return token

    text = _BRACKET_RE.sub(_sub, markdown)
    return text, {
        "filled": filled,
        "missing_company": missing_company,
        "pending_business": pending_business,
    }


def unfilled_notice(info: dict) -> str:
    """生成文末"待补清单" Markdown (回填后仍残留的占位符)。"""
    miss, pending = info.get("missing_company", []), info.get("pending_business", [])
    if not miss and not pending:
        return ""
    lines = ["---", "", "## 📋 待补清单（系统未能自动回填的占位符）", ""]
    for label in miss:
        lines.append(f"- [ ] [{label}] — 请先在**企业资料库**补全后重新生成")
    for label in pending:
        lines.append(f"- [ ] [{label}] — 需结合本项目实际测算/配置手工填写")
    return "\n".join(lines)


class _StreamFiller:
    """增量占位符回填: 缓存 '[' 起的未闭合片段, 跨 chunk 正确替换。"""

    def __init__(self, profile: dict | None):
        self.p = _norm(profile)
        self.buf = ""

    def push(self, chunk: str) -> str:
        self.buf += chunk
        out: list[str] = []
        while True:
            i = self.buf.find("[")
            if i < 0:
                out.append(self.buf)
                self.buf = ""
                break
            j = self.buf.find("]", i + 1)
            if j < 0:
                # 未闭合: 先吐出 '[' 之前的安全前缀, 其余缓存
                out.append(self.buf[:i])
                self.buf = self.buf[i:]
                break
            out.append(self.buf[:i])
            out.append(_replace_token(self.buf[i:j + 1], self.p))
            self.buf = self.buf[j + 1:]
        return "".join(out)

    def flush(self) -> str:
        # 流结束仍未闭合 (LLM 输出残缺括号), 原样吐出
        tail, self.buf = self.buf, ""
        return tail


def fill_placeholders_stream(chunks: Iterator[str], profile: dict | None) -> Iterator[str]:
    """对 LLM token 流做占位符回填, 保持流式体验。"""
    f = _StreamFiller(profile)
    for chunk in chunks:
        out = f.push(chunk)
        if out:
            yield out
    tail = f.flush()
    if tail:
        yield tail
