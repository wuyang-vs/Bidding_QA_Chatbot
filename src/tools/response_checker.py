"""投标响应性检查 — 对照招标文件实质性条款, 判断投标文件是否逐条响应.

核心流程:
  1. 输入: 招标文件全文 (或 db_id) + 投标文件全文
  2. (可选) 指定具体条款号 (如 "3.2"), 则只检查该条款
  3. LLM 从招标文件中提取实质性条款 (技术参数/工期/质保/付款/有效期/保证金等)
  4. 逐条在投标文件中检索响应, 判定: 响应 / 正偏离 / 负偏离 / 未响应
  5. 输出: 条款对照表 + 统计 + 风险提示

判定标准:
  - 响应 (response): 投标内容满足或优于招标文件要求
  - 正偏离 (positive): 投标优于招标要求 (如工期更短、质保更长)
  - 负偏离 (negative): 投标不满足招标要求 (可能构成实质性偏离, 影响中标)
  - 未响应 (none): 投标文件中未提及该条款

设计:
  - LLM 失败时有关键词降级 (按实质性要求关键词扫描)
  - 文件过短时提示信息不足
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# 实质性条款类别 (降级模式 + 提示用)
_SUBSTANTIVE_CATEGORIES = [
    ("技术参数", ["技术参数", "技术要求", "规格", "配置", "性能", "指标"]),
    ("工期/交货期", ["工期", "交货期", "交付时间", "供货期", "完成时间"]),
    ("质保期", ["质保", "保修期", "质量保证期", "免费维护"]),
    ("付款方式", ["付款", "支付方式", "结算", "预付款", "进度款"]),
    ("投标有效期", ["投标有效期", "报价有效期"]),
    ("投标保证金", ["保证金", "担保"]),
    ("售后服务", ["售后", "服务", "培训", "运维"]),
]


_EXTRACT_SYSTEM = (
    "你是招投标响应性审查专家. 根据招标文件, 提取需要投标人实质性响应的条款.\n"
    "要求:\n"
    "1. 只提取实质性要求 (技术参数/工期/质保/付款/有效期/保证金/售后服务等), 不提取流程性说明\n"
    "2. 每条保留条款编号 (如 3.2) 和原文关键表述\n"
    "3. requirement 字段用一句话概括对投标人的具体要求 (含可量化指标)\n"
    "4. 只输出 JSON, 不要任何额外文字或代码块标记"
)


_RESPONSE_SYSTEM = (
    "你是投标响应性审查专家. 根据招标文件条款和投标文件内容, 逐条判定投标是否响应.\n"
    "判定标准:\n"
    "  response  — 投标内容满足招标要求\n"
    "  positive  — 投标优于招标要求 (如工期更短、质保更长、配置更高), 属正偏离\n"
    "  negative  — 投标不满足或低于招标要求 (负偏离), 可能影响中标\n"
    "  none      — 投标文件中未提及该条款 (未响应)\n"
    "证据: 引用投标文件中的对应原文片段; 未响应时 evidence 为空.\n"
    "只输出 JSON, 不要任何额外文字或代码块标记"
)


def _content_from_input(text: str | dict) -> str:
    if isinstance(text, dict):
        parts = []
        if text.get("project_name"):
            parts.append(f"项目名称: {text.get('project_name')}")
        if text.get("budget"):
            parts.append(f"预算金额: {text.get('budget')}")
        if text.get("deadline"):
            parts.append(f"投标截止时间: {text.get('deadline')}")
        if text.get("qualification_requirements"):
            reqs = text["qualification_requirements"]
            if isinstance(reqs, list):
                parts.append("资格要求:\n" + "\n".join(f"- {r}" for r in reqs))
            else:
                parts.append(f"资格要求: {reqs}")
        raw = text.get("raw_text") or text.get("raw_text_preview") or ""
        parts.append(raw)
        return "\n".join(parts)
    return str(text or "")


def _truncate(text: str, head: int = 6000, tail: int = 2000) -> str:
    if len(text) <= head + tail + 500:
        return text
    return text[:head] + "\n...[中间省略]...\n" + text[-tail:]


def check_response(
    tender: str | dict,
    bid: str | dict,
    clause: str | None = None,
    llm_client=None,
) -> dict[str, Any]:
    """检查投标文件对招标文件实质性条款的响应情况.

    Args:
        tender: 招标文件全文, 或 document_parser dict
        bid: 投标文件全文, 或 document_parser dict
        clause: 可选, 指定条款号 (如 "3.2"), 只检查该条款
        llm_client: LLM 客户端

    Returns:
        {
            "summary": {"total": N, "response": N, "positive": N, "negative": N, "none": N},
            "clauses": [{"id","clause_no","category","tender_clause","requirement",
                         "status","evidence","detail"}],
            "verdict": "pass|attention|danger",
            "note": "...",
        }
    """
    tender_text = _content_from_input(tender)
    bid_text = _content_from_input(bid)

    if not tender_text.strip():
        return _empty_result("⚠️ 招标文件内容为空, 请确认招标文件已正确解析.")
    if not bid_text.strip():
        return _empty_result("⚠️ 投标文件内容为空, 请提供投标文件内容.")

    if llm_client is None:
        from src.clients.llm_factory import get_llm_client
        llm_client = get_llm_client()

    tender_analyze = _truncate(tender_text, 7000, 2000)
    bid_analyze = _truncate(bid_text, 7000, 2000)

    # 步骤 1: 提取招标实质性条款
    clauses_raw = _extract_clauses(tender_analyze, clause, llm_client)
    if not clauses_raw:
        note = "未在招标文件中提取到实质性条款"
        if clause:
            note += f" (指定条款 '{clause}' 未找到, 请确认条款号是否正确)"
        return _empty_result(f"⚠️ {note}.")

    # 步骤 2: 逐条判定响应性
    responses = _judge_responses(clauses_raw, bid_analyze, llm_client)

    # 规整
    clauses: list[dict[str, Any]] = []
    stats = {"response": 0, "positive": 0, "negative": 0, "none": 0}
    for i, (c, resp) in enumerate(zip(clauses_raw, responses), start=1):
        status = resp.get("status", "none")
        if status not in stats:
            status = "none"
        stats[status] += 1
        clauses.append({
            "id": f"C{i}",
            "clause_no": c.get("clause_no", ""),
            "category": c.get("category", "其他"),
            "tender_clause": str(c.get("tender_clause", "")).strip(),
            "requirement": str(c.get("requirement", "")).strip(),
            "status": status,
            "evidence": str(resp.get("evidence", "")).strip(),
            "detail": str(resp.get("detail", "")).strip(),
        })

    verdict = "pass"
    if stats["negative"] > 0:
        verdict = "danger"
    elif stats["none"] > 0 or stats["positive"] > 0:
        verdict = "attention"

    return {
        "summary": {
            "total": len(clauses),
            "response": stats["response"],
            "positive": stats["positive"],
            "negative": stats["negative"],
            "none": stats["none"],
        },
        "clauses": clauses,
        "verdict": verdict,
    }


def _extract_clauses(tender_text: str, clause: str | None, llm_client) -> list[dict[str, Any]]:
    """从招标文件提取实质性条款."""
    clause_hint = ""
    if clause:
        clause_hint = f"\n\n只提取与条款 '{clause}' 相关的实质性要求. 若该条款号不存在, 返回空数组."

    user_msg = (
        f"【招标文件】\n{tender_text}\n\n"
        "请提取需要投标人实质性响应的条款, 输出 JSON:\n"
        '{"clauses": [\n'
        '  {"clause_no": "条款编号(如3.2, 无则空)",\n'
        '   "category": "技术参数|工期/交货期|质保期|付款方式|投标有效期|投标保证金|售后服务|其他",\n'
        '   "tender_clause": "条款原文关键表述",\n'
        '   "requirement": "对投标人的具体要求(一句话, 含量化指标)"}\n'
        "]}"
        f"{clause_hint}"
    )
    try:
        raw = llm_client.chat([
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user", "content": user_msg},
        ], temperature=0.1)
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)
        parsed = json.loads(cleaned)
        clauses = parsed.get("clauses", [])
    except Exception as e:
        logger.warning("实质性条款提取 LLM 失败, 降级: %s", e)
        clauses = _fallback_extract(tender_text, clause)
    return clauses


def _fallback_extract(tender_text: str, clause: str | None) -> list[dict[str, Any]]:
    """LLM 失败时按实质性类别关键词扫描."""
    sentences = re.split(r"[。;；\n]+", tender_text)
    found: list[dict[str, Any]] = []
    for s in sentences:
        s = s.strip()
        if len(s) < 8 or len(s) > 200:
            continue
        category = None
        for cat, kws in _SUBSTANTIVE_CATEGORIES:
            if any(kw in s for kw in kws):
                category = cat
                break
        if category is None:
            continue
        if clause and clause not in s:
            continue
        # 提取条款号
        m = re.search(r"(第?\d+(?:\.\d+)*[条款]?)", s)
        clause_no = m.group(1) if m else ""
        found.append({
            "clause_no": clause_no,
            "category": category,
            "tender_clause": s,
            "requirement": s,
        })
    return found[:15]


def _judge_responses(
    clauses: list[dict[str, Any]],
    bid_text: str,
    llm_client,
) -> list[dict[str, Any]]:
    """逐条判定投标响应性."""
    if not clauses:
        return []

    clauses_text = "\n".join(
        f"[{i+1}] ({c.get('category','')}) {c.get('clause_no','')} "
        f"要求: {c.get('requirement','')} | 原文: {c.get('tender_clause','')[:80]}"
        for i, c in enumerate(clauses)
    )
    user_msg = (
        f"【招标实质性条款】\n{clauses_text}\n\n"
        f"【投标文件】\n{bid_text}\n\n"
        "请逐条判定投标文件的响应情况, 输出 JSON:\n"
        '{"responses": [\n'
        '  {"index": 1, "status": "response|positive|negative|none",\n'
        '   "evidence": "投标文件中对应原文片段(none时为空)",\n'
        '   "detail": "判定说明(一句话, 如工期满足/质保优于要求/未提及付款方式)"}\n'
        "]}"
    )
    try:
        raw = llm_client.chat([
            {"role": "system", "content": _RESPONSE_SYSTEM},
            {"role": "user", "content": user_msg},
        ], temperature=0.1)
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)
        parsed = json.loads(cleaned)
        responses = parsed.get("responses", [])
        # 按 index 对齐
        result: list[dict[str, Any]] = []
        for c in clauses:
            result.append({"status": "none", "evidence": "", "detail": ""})
        for resp in responses:
            idx = resp.get("index", 0)
            if isinstance(idx, int) and 1 <= idx <= len(result):
                result[idx - 1] = {
                    "status": resp.get("status", "none"),
                    "evidence": resp.get("evidence", ""),
                    "detail": resp.get("detail", ""),
                }
        return result
    except Exception as e:
        logger.warning("响应性判定 LLM 失败, 返回全未响应: %s", e)
        return [{"status": "none", "evidence": "", "detail": "LLM 判定失败"} for _ in clauses]


def _empty_result(note: str) -> dict[str, Any]:
    return {
        "summary": {"total": 0, "response": 0, "positive": 0, "negative": 0, "none": 0},
        "clauses": [],
        "verdict": "unknown",
        "note": note,
    }
