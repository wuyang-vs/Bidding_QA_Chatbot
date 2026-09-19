"""逐条招标要求响应对照矩阵。

输入: 招标文件 (结构化字段 + raw_text) + 已生成的投标稿 Markdown
输出: 逐条要求 → 投标响应内容 → 响应状态 (满足/正偏离/负偏离/不满足/未响应),
      并渲染 Markdown 对照表; 实质性条款不满足/未响应计为硬性不合格 (hard_failures)。

LLM 失败时降级: 用 qualification_requirements + 关键词包含做确定性匹配。
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time

logger = logging.getLogger(__name__)

# 状态码 → (展示文案, Markdown 标记, 是否红色不合格)
STATUS_MAP = {
    "SATISFIED": ("满足", "🟢 满足", False),
    "POSITIVE_DEVIATION": ("正偏离", "🔵 正偏离", False),
    "NEGATIVE_DEVIATION": ("负偏离", "🟡 负偏离", False),
    "NOT_SATISFIED": ("不满足", "🔴 不满足", True),
    "NO_RESPONSE": ("未响应", "🔴 未响应", True),
}
_RED_STATUSES = {"NOT_SATISFIED", "NO_RESPONSE"}
_WARN_STATUSES = {"NEGATIVE_DEVIATION"}

_MATRIX_SYSTEM = (
    "你是招投标符合性审查专家。根据招标文件原文要求与投标人已编制的投标稿, "
    "逐条抽取招标文件中的实质性/重要要求(资质、商务、技术、交付、售后等), "
    "并在投标稿中找到对应响应内容, 客观判定响应状态。\n"
    "状态枚举:\n"
    "  SATISFIED 满足; POSITIVE_DEVIATION 正偏离(优于要求); "
    "NEGATIVE_DEVIATION 负偏离(打折扣但不构成废标); "
    "NOT_SATISFIED 不满足; NO_RESPONSE 投标稿未提及该要求。\n"
    "判定必须依据投标稿原文, 投标稿没有对应内容时只能给 NO_RESPONSE, 严禁脑补。\n"
    "带★或标注'实质性/必须/否则否决/废标'的要求 material=true。\n"
    "只输出 JSON, 不要代码块标记或任何额外文字, 格式:\n"
    '{"rows": [{"no": "1", "requirement": "要求原文简述(<=60字)", '
    '"category": "资格|商务|技术|交付|售后", "material": true, '
    '"response": "投标稿对应响应(<=80字, 没有则空字符串)", '
    '"status": "SATISFIED|POSITIVE_DEVIATION|NEGATIVE_DEVIATION|NOT_SATISFIED|NO_RESPONSE", '
    '"evidence": "所在章节/条款", "note": "判定说明(<=40字)"}]}'
)

_MAX_TENDER_CHARS = 9000
_MAX_BID_CHARS = 14000


def _clean_cell(s: object) -> str:
    s = str(s or "").replace("|", "/").replace("\n", " ").strip()
    return re.sub(r"\s+", " ", s)


# ---- R9: 行结构校验 + material 启发式校正 ----
_CATEGORIES = {"资格", "商务", "技术", "交付", "售后", "其他"}
# 实质性条款关键词: 带★/实质性/必须/废标/否决/否则/不得/应当
_MATERIAL_KW = re.compile(r"(★|实质性|必须|废标|否决|否则|不得|应当|资格条件|资质要求)")


def _validate_row(r: dict, idx: int) -> dict | None:
    """校验 LLM 返回的单行; 结构不合规返回 None (丢弃), 字段超限/非法就地修正。"""
    if not isinstance(r, dict):
        return None
    requirement = _clean_cell(r.get("requirement"))[:80]
    if not requirement:
        return None  # 无要求文本的行丢弃
    status = str(r.get("status", "")).upper()
    if status not in STATUS_MAP:
        status = "NO_RESPONSE"
    category = _clean_cell(r.get("category"))[:10]
    if category not in _CATEGORIES:
        category = "其他"
    material = bool(r.get("material"))
    # 启发式校正: 要求文本含实质性关键词才算 material=true, 防 LLM 乱标
    if material and not _MATERIAL_KW.search(requirement):
        material = False
    return {
        "no": str(r.get("no") or idx),
        "requirement": requirement,
        "category": category,
        "material": material,
        "response": _clean_cell(r.get("response"))[:120],
        "status": status,
        "evidence": _clean_cell(r.get("evidence"))[:40],
        "note": _clean_cell(r.get("note"))[:60],
    }


# ---- R9: 内存 TTL 缓存 (db_id + bid_hash → matrix) ----
_MATRIX_CACHE: dict[str, tuple[float, dict]] = {}
_MATRIX_CACHE_TTL = 3600  # 1 小时
_MATRIX_CACHE_MAX = 64
_cache_lock = threading.Lock()


def _cache_key(db_id: int | None, tender_blob: str, bid_blob: str) -> str:
    h = hashlib.sha256()
    h.update(str(db_id or 0).encode())
    h.update(tender_blob[:_MAX_TENDER_CHARS].encode("utf-8"))
    h.update(bid_blob[:_MAX_BID_CHARS].encode("utf-8"))
    return h.hexdigest()[:32]


def _cache_get(key: str) -> dict | None:
    with _cache_lock:
        item = _MATRIX_CACHE.get(key)
        if item is None:
            return None
        ts, val = item
        if time.time() - ts > _MATRIX_CACHE_TTL:
            _MATRIX_CACHE.pop(key, None)
            return None
        return val


def _cache_set(key: str, val: dict) -> None:
    with _cache_lock:
        if len(_MATRIX_CACHE) >= _MATRIX_CACHE_MAX:
            # 淘汰最旧的一项
            oldest = min(_MATRIX_CACHE.items(), key=lambda kv: kv[1][0])
            _MATRIX_CACHE.pop(oldest[0], None)
        _MATRIX_CACHE[key] = (time.time(), val)


def clear_matrix_cache() -> None:
    """测试/运维用: 清空对照表缓存。"""
    with _cache_lock:
        _MATRIX_CACHE.clear()


def _fallback_rows(tender: dict, bid_md: str) -> list[dict]:
    """LLM 不可用时的确定性降级: 资质要求逐条做关键词包含匹配。"""
    rows = []
    reqs = list(tender.get("qualification_requirements") or [])
    for i, req in enumerate(reqs, 1):
        req_s = str(req).strip()
        if not req_s:
            continue
        hit = req_s[:8] in bid_md or any(
            w and w in bid_md for w in re.findall(r"[一-鿿]{4,12}", req_s)[:2])
        rows.append({
            "no": str(i), "requirement": req_s[:60], "category": "资格",
            "material": True,
            "response": "投标稿包含相关表述" if hit else "",
            "status": "SATISFIED" if hit else "NO_RESPONSE",
            "evidence": "关键词匹配(降级)", "note": "LLM 不可用, 关键词匹配",
        })
    return rows


def build_requirement_matrix(tender: dict, raw_text: str, bid_markdown: str,
                             llm_client=None, use_cache: bool = True) -> dict:
    """生成逐条响应对照矩阵。

    Returns:
        {rows, summary: {total, red, warn, hard_failures, status_counts},
         hard_failures: [rows...], verdict: pass|warn|fail, cached: bool}
    """
    if llm_client is None:
        from src.clients.llm_factory import get_llm_client
        llm_client = get_llm_client()

    tender_blob = (raw_text or "").strip()
    if not tender_blob:
        # 无全文时用结构化字段拼一个最小招标描述
        from src.tools.bid_generator import _summarize_tender_info
        tender_blob = _summarize_tender_info(tender)
    tender_blob = tender_blob[:_MAX_TENDER_CHARS]
    bid_blob = (bid_markdown or "")[:_MAX_BID_CHARS]

    # R9: 内存 TTL 缓存 (相同招标原文 + 相同投标稿直接复用, 跳过 LLM)
    if use_cache:
        key = _cache_key(tender.get("db_id"), tender_blob, bid_blob)
        cached = _cache_get(key)
        if cached is not None:
            logger.info("对照表命中缓存 (db_id=%s, bid %d 字)", tender.get("db_id"), len(bid_blob))
            return {**cached, "cached": True}

    user_msg = (
        f"【招标文件】\n{tender_blob}\n\n"
        f"【投标稿】\n{bid_blob}\n\n"
        "请抽取 8-20 条最关键要求(优先实质性条款)并逐条判定, 输出 JSON。"
    )

    rows: list[dict] = []
    try:
        raw = llm_client.chat([
            {"role": "system", "content": _MATRIX_SYSTEM},
            {"role": "user", "content": user_msg},
        ], temperature=0.1)
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)
        parsed = json.loads(cleaned)
        for i, r in enumerate(parsed.get("rows", []), 1):
            valid = _validate_row(r, i)
            if valid:
                rows.append(valid)
    except Exception as e:
        logger.warning("响应对照矩阵 LLM 失败, 降级关键词匹配: %s", e)
        rows = _fallback_rows(tender, bid_blob)

    if not rows:
        rows = _fallback_rows(tender, bid_blob)

    counts = {k: 0 for k in STATUS_MAP}
    hard_failures = []
    for r in rows:
        counts[r["status"]] += 1
        if r["material"] and r["status"] in _RED_STATUSES:
            hard_failures.append(r)

    red = sum(counts[s] for s in _RED_STATUSES)
    warn = sum(counts[s] for s in _WARN_STATUSES)
    if hard_failures:
        verdict = "fail"
    elif red or warn:
        verdict = "warn"
    else:
        verdict = "pass"

    matrix = {
        "rows": rows,
        "summary": {
            "total": len(rows), "red": red, "warn": warn,
            "hard_failures": len(hard_failures),
            "status_counts": counts,
        },
        "hard_failures": hard_failures,
        "verdict": verdict,
    }
    if use_cache:
        _cache_set(key, matrix)
    return {**matrix, "cached": False}


def render_matrix_markdown(matrix: dict) -> str:
    """矩阵 → 附录 Markdown 表格 (含 🔴/🟡 标记, docx 导出时红体标红)。"""
    rows = matrix.get("rows") or []
    summary = matrix.get("summary") or {}
    lines = [
        "## 附录：招标要求逐条响应对照表",
        "",
        f"共 {summary.get('total', len(rows))} 条要求；"
        f"🔴 不合格 {summary.get('red', 0)} 条"
        f"（其中实质性条款硬不合格 {summary.get('hard_failures', 0)} 条）；"
        f"🟡 负偏离 {summary.get('warn', 0)} 条。",
        "",
        "| 序号 | 招标要求 | 类别 | 实质性 | 投标响应内容 | 响应状态 | 所在章节/说明 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        label = STATUS_MAP.get(r["status"], ("未知", "⚪ 未知", False))[1]
        material = "★是" if r.get("material") else "否"
        if r["status"] in _RED_STATUSES:
            material = "★是" if r.get("material") else "是"
        lines.append("| {no} | {req} | {cat} | {mat} | {resp} | {st} | {ev} |".format(
            no=_clean_cell(r.get("no")),
            req=_clean_cell(r.get("requirement")),
            cat=_clean_cell(r.get("category")),
            mat=material,
            resp=_clean_cell(r.get("response")) or "（投标稿未提及）",
            st=label,
            ev=_clean_cell(r.get("evidence") or r.get("note")),
        ))
    if matrix.get("hard_failures"):
        lines += ["", "### ⛔ 实质性条款不合格项（投标前必须整改）", ""]
        for r in matrix["hard_failures"]:
            lines.append(
                f"- 🔴 **第 {r['no']} 条（{r['category']}）**：{r['requirement']}"
                f" — {STATUS_MAP[r['status']][1]}，{r.get('note') or '投标稿无对应响应'}")
    return "\n".join(lines)
