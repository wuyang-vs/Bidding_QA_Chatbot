"""R12 敏感操作审计: audit_logs 落库 + 查询。

安全原则:
- changed_fields 只存**字段名**清单 (JSONB), 绝不存字段值 (银行账号/电话等);
- detail/ip/user_agent 做长度截断, 防止超大文本写入;
- PG 未就绪或写库失败时降级 logger, 审计异常**永不阻断主业务**;
- 查询全部参数化绑定, 排序固定白名单, 防止注入。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# ---- action 常量 ----
ACTION_PROFILE_UPDATE = "profile.update"   # 企业资料更新 (含敏感字段)
ACTION_CERT_OCR = "cert.ocr"                # 证书原件上传 OCR
ACTION_KEY_ROTATE = "key.rotate"            # 敏感字段加密密钥批量轮换 (system)

_MAX_FIELDS = 50          # 单次审计字段名上限
_MAX_FIELD_LEN = 64       # 单个字段名长度上限
_MAX_TEXT_LEN = 500       # ip/ua/target_id 长度上限
_MAX_DETAIL_LEN = 2000    # detail 长度上限
_MAX_LIMIT = 200          # 单次查询条数上限
_DEFAULT_LIMIT = 50

# 查询排序白名单 (禁止外部传入任意 ORDER BY)
_SORT_DIRS = {"desc": "DESC", "asc": "ASC"}


def _clean_fields(fields: Any) -> list[str]:
    """清洗字段名清单: 仅接受非空字符串, 去重保序, 限长限量。"""
    if not isinstance(fields, (list, tuple)):
        return []
    out: list[str] = []
    for f in fields:
        if not isinstance(f, str):
            continue
        f = f.strip()[:_MAX_FIELD_LEN]
        if f and f not in out:
            out.append(f)
        if len(out) >= _MAX_FIELDS:
            break
    return out


def _clip(v: Any, limit: int) -> str:
    if v is None:
        return ""
    return str(v)[:limit]


def record_audit(*, user_id: int | None, username: str, action: str,
                 target_type: str = "", target_id: str = "",
                 changed_fields: list[str] | None = None,
                 ip: str = "", user_agent: str = "", detail: str = "") -> bool:
    """写入一条审计日志。返回是否落库成功 (失败仅降级, 不抛异常)。

    敏感字段值一律不得经 detail/changed_fields 传入; 调用方只传字段名。
    """
    from src.database.postgresql_client import postgresql_client

    action = str(action or "").strip()[:_MAX_FIELD_LEN]
    if not action:
        return False
    fields = _clean_fields(changed_fields)
    params = {
        "uid": user_id if isinstance(user_id, int) else None,
        "uname": _clip(username, _MAX_TEXT_LEN),
        "action": action,
        "ttype": _clip(target_type, _MAX_FIELD_LEN),
        "tid": _clip(target_id, _MAX_TEXT_LEN),
        "fields": json.dumps(fields, ensure_ascii=False),
        "ip": _clip(ip, _MAX_TEXT_LEN),
        "ua": _clip(user_agent, _MAX_TEXT_LEN),
        "detail": _clip(detail, _MAX_DETAIL_LEN),
    }
    if not postgresql_client.ready:
        logger.info("[审计-降级] action=%s user=%s fields=%s detail=%s",
                    action, params["uname"], fields, params["detail"])
        return False
    try:
        postgresql_client._run(
            "INSERT INTO audit_logs "
            "(user_id, username, action, target_type, target_id, "
            "changed_fields, ip, user_agent, detail) "
            "VALUES (:uid, :uname, :action, :ttype, :tid, "
            "CAST(:fields AS JSONB), :ip, :ua, :detail)",
            params)
        return True
    except Exception as e:
        logger.warning("[审计-写库失败降级] action=%s user=%s err=%s",
                       action, params["uname"], e)
        return False


def list_audit_logs(*, user_id: int | None = None, username: str | None = None,
                    action: str | None = None, target_type: str | None = None,
                    start_time: datetime | str | None = None,
                    end_time: datetime | str | None = None,
                    limit: int = _DEFAULT_LIMIT, offset: int = 0,
                    order: str = "desc") -> dict:
    """分页查询审计日志 (仅供 admin/auditor 端点调用, RBAC 在路由层强制)。

    返回 {items, total, limit, offset}; PG 不可用时 items 为空、total=0。
    """
    from src.database.postgresql_client import postgresql_client

    try:
        limit = max(1, min(int(limit), _MAX_LIMIT))
    except (TypeError, ValueError):
        limit = _DEFAULT_LIMIT
    try:
        offset = max(0, int(offset))
    except (TypeError, ValueError):
        offset = 0
    sort_dir = _SORT_DIRS.get(str(order).lower(), "DESC")

    conds: list[str] = []
    params: dict[str, Any] = {}
    if isinstance(user_id, int):
        conds.append("user_id = :uid")
        params["uid"] = user_id
    if username:
        conds.append("username = :uname")
        params["uname"] = str(username)[:_MAX_TEXT_LEN]
    if action:
        conds.append("action = :action")
        params["action"] = str(action)[:_MAX_FIELD_LEN]
    if target_type:
        conds.append("target_type = :ttype")
        params["ttype"] = str(target_type)[:_MAX_FIELD_LEN]
    if start_time:
        conds.append("created_at >= :start")
        params["start"] = start_time
    if end_time:
        conds.append("created_at <= :end")
        params["end"] = end_time
    where = (" WHERE " + " AND ".join(conds)) if conds else ""

    if not postgresql_client.ready:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}

    sql_items = (
        "SELECT id, user_id, username, action, target_type, target_id, "
        "changed_fields, ip, user_agent, detail, created_at "
        f"FROM audit_logs{where} ORDER BY id {sort_dir} LIMIT :limit OFFSET :offset")
    q_params = dict(params, limit=limit, offset=offset)
    sql_count = f"SELECT COUNT(*) AS cnt FROM audit_logs{where}"
    try:
        rows = postgresql_client._run(sql_items, q_params)
        total_rows = postgresql_client._run(sql_count, params)
    except Exception as e:
        logger.warning("[审计-查询失败] %s", e)
        return {"items": [], "total": 0, "limit": limit, "offset": offset}

    items: list[dict] = []
    for r in rows:
        item = dict(r)
        # JSONB 经 psycopg 返回已是 list; 兜底解析字符串形态
        cf = item.get("changed_fields")
        if isinstance(cf, str):
            try:
                item["changed_fields"] = json.loads(cf)
            except (ValueError, TypeError):
                item["changed_fields"] = []
        elif cf is None:
            item["changed_fields"] = []
        # datetime 序列化为 ISO 字符串, 便于端点 JSON 响应
        ts = item.get("created_at")
        if isinstance(ts, datetime):
            item["created_at"] = ts.isoformat(sep=" ", timespec="seconds")
        items.append(item)
    total = int(total_rows[0]["cnt"]) if total_rows else 0
    return {"items": items, "total": total, "limit": limit, "offset": offset}
