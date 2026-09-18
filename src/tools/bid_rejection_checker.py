"""废标(否决投标)条款检查 — 从招标文件中提取全部废标/无效投标条款.

核心流程:
  1. 输入: 招标文件全文 (或 document_parser 输出的 dict)
  2. LLM 提取所有"否决投标/废标/无效投标/拒收"条款, 逐条归类
  3. 可选: 用户提供本企业投标响应情况 → 逐条自查是否可能触发废标
  4. 输出: 分类条款清单 + 风险等级 + 投标注意事项 + (可选)自查结论

条款分类:
  - 形式响应: 盖章/签字/密封/送达/格式/份数
  - 资格性:   营业执照/资质证书/联合体/失信记录
  - 价格性:   超预算/最高限价/报价唯一/明显低于成本
  - 响应性:   工期/质保/投标有效期/保证金/关键技术参数
  - 行为性:   串通投标/弄虚作假/行贿
  - 其他

设计:
  - LLM 失败时有关键词降级 (扫描"否决/废标/无效投标"附近句子)
  - 文件中无废标条款时明确提示, 不编造
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# 废标条款触发关键词 (降级模式用)
_REJECTION_KEYWORDS = [
    "否决", "废标", "无效投标", "投标无效", "按无效", "拒收",
    "不予受理", "拒绝其投标", "不得参加",
]

# 条款分类规则 (降级模式分类用)
_CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("形式响应", ["盖章", "签字", "签章", "密封", "送达", "逾期", "迟交", "份数", "格式", "字迹", "标记"]),
    ("资格性", ["营业执照", "资质", "资格", "联合体", "失信", "违法", "授权", "法人"]),
    ("价格性", ["预算", "最高限价", "限价", "报价", "低于成本", "两个以上"]),
    ("响应性", ["工期", "质保", "有效期", "保证金", "交货", "技术参数", "实质性", "偏离"]),
    ("行为性", ["串通", "弄虚作假", "行贿", "陪标", "围标"]),
]


_EXTRACT_SYSTEM = (
    "你是招投标文件审查专家, 精通《招标投标法》《政府采购法》及实施条例中关于"
    "否决投标(废标/无效投标)的规定. 你的任务是从招标文件中完整、准确地提取"
    "所有会导致投标被否决或按无效投标处理的条款.\n\n"
    "提取要求:\n"
    "1. 只提取明确表述否决/废标/无效/拒收后果的硬性条款, 不提取一般流程性描述\n"
    "2. 每条保留原文关键表述, 不要概括到丢失具体要求\n"
    "3. 按类别归类: 形式响应/资格性/价格性/响应性/行为性/其他\n"
    "4. risk_level: 高频踩雷且无补救空间=高; 常见但可提前准备=中; 其余=低\n"
    "5. 只输出 JSON, 不要任何额外文字或代码块标记"
)


def _content_from_input(text: str | dict) -> str:
    """从全文或 document_parser dict 中组织待分析文本."""
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


def check_bid_rejection(
    text: str | dict,
    bidder_status: str | None = None,
    llm_client=None,
) -> dict[str, Any]:
    """提取废标条款, 可选结合投标人自身情况做废标风险自查.

    Args:
        text: 招标文件全文, 或 document_parser 输出的 dict (含 raw_text_preview)
        bidder_status: 可选, 用户描述本企业投标准备情况 (自由文本/逐行清单)
        llm_client: LLM 客户端

    Returns:
        {
            "summary": {"total_clauses": N, "by_category": {类别: 数量}, "risk_count": N},
            "clauses": [{"id","category","clause_text","requirement","risk_level","tip"}],
            "self_check": None | [{"clause_id","status","reason"}],
            "verdict": "unknown|safe|attention|danger",
            "note": "降级/空结果提示 (可选)",
        }
    """
    content = _content_from_input(text)
    if not content.strip():
        return _empty_result("⚠️ 文件内容为空, 无法提取废标条款, 请确认文件已正确解析.")

    if llm_client is None:
        from src.clients.llm_factory import get_llm_client
        llm_client = get_llm_client()

    # 截断保护
    analyze_text = content
    if len(analyze_text) > 8000:
        analyze_text = analyze_text[:6500] + "\n...[中间省略]...\n" + analyze_text[-1200:]

    import json

    user_msg = (
        f"【招标文件】\n{analyze_text}\n\n"
        "请提取全部废标/否决投标/无效投标条款, 输出 JSON:\n"
        '{"clauses": [\n'
        '  {"category": "形式响应|资格性|价格性|响应性|行为性|其他",\n'
        '   "clause_text": "条款原文关键表述",\n'
        '   "requirement": "对投标人的具体要求(一句话)",\n'
        '   "risk_level": "高|中|低",\n'
        '   "tip": "投标准备注意事项(一句话)"}\n'
        "]}\n"
        "若文件中确实没有废标条款, 返回 {\"clauses\": []}"
    )

    try:
        raw = llm_client.chat([
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user", "content": user_msg},
        ], temperature=0.1)
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)
        parsed = json.loads(cleaned)
        clauses_raw = parsed.get("clauses", [])
        degraded = False
    except Exception as e:
        logger.warning("废标条款 LLM 提取失败, 降级为关键词扫描: %s", e)
        clauses_raw = _fallback_extract(content)
        degraded = True

    # 规整
    clauses: list[dict[str, Any]] = []
    by_category: dict[str, int] = {}
    for i, c in enumerate(clauses_raw, start=1):
        clause_text = str(c.get("clause_text", "")).strip()
        if not clause_text:
            continue
        category = c.get("category", "其他") or "其他"
        if category not in ("形式响应", "资格性", "价格性", "响应性", "行为性", "其他"):
            category = "其他"
        item = {
            "id": f"R{i}",
            "category": category,
            "clause_text": clause_text,
            "requirement": str(c.get("requirement", "")).strip(),
            "risk_level": c.get("risk_level", "中") if c.get("risk_level") in ("高", "中", "低") else "中",
            "tip": str(c.get("tip", "")).strip(),
        }
        clauses.append(item)
        by_category[category] = by_category.get(category, 0) + 1

    result: dict[str, Any] = {
        "summary": {
            "total_clauses": len(clauses),
            "by_category": by_category,
            "risk_count": sum(1 for c in clauses if c["risk_level"] == "高"),
        },
        "clauses": clauses,
        "self_check": None,
        "verdict": "unknown",
    }
    if degraded:
        result["note"] = "⚠️ LLM 提取失败, 以下为关键词扫描结果, 可能不完整, 建议稍后重试"

    if not clauses:
        result["note"] = (
            "未在文件中识别到明确的废标/否决投标条款. 部分招标文件以"
            "'投标人须知前附表'或'否决投标情形一览表'集中列示, 请确认文件是否完整."
        )
        return result

    # 可选: 投标人自查
    status_text = (bidder_status or "").strip()
    if status_text:
        result["self_check"], result["verdict"] = _self_check(
            clauses, status_text, llm_client, degraded)
    return result


# ========== 投标人自查 ==========

_SELFCHECK_SYSTEM = (
    "你是投标风险评估专家. 根据招标文件废标条款和投标人自述的准备情况, "
    "逐条判断该投标人是否可能触发废标.\n"
    "判定标准 (务必果断, 不要回避判断):\n"
    "  risk      — 自述信息与条款明确冲突或明确不满足 (如条款限价860万, 自述报价920万; "
    "条款不接受联合体, 自述以联合体投标; 要求一级资质, 自述只有二级资质)\n"
    "  safe      — 自述明确表明满足该条款 (如已交10万保证金、已盖章、工期承诺满足)\n"
    "  uncertain — 自述完全没有提及该条款相关信息, 无法判断 (仅在信息缺失时使用, "
    "不要把明确冲突判成 uncertain)\n"
    "只输出 JSON, 不要任何额外文字或代码块标记"
)


def _self_check(
    clauses: list[dict[str, Any]],
    bidder_status: str,
    llm_client,
    degraded: bool,
) -> tuple[list[dict[str, Any]], str]:
    """结合投标人自述, 对每条废标条款做风险判定."""
    import json

    clause_text = "\n".join(
        f"{c['id']}. [{c['category']}] {c['clause_text']}" for c in clauses
    )
    user_msg = (
        f"【废标条款】\n{clause_text}\n\n"
        f"【投标人自述情况】\n{bidder_status}\n\n"
        "请逐条判定, 输出 JSON:\n"
        '{"checks": [{"clause_id": "R1", "status": "safe|risk|uncertain",'
        ' "reason": "判定依据(一句话)"}]}'
    )
    try:
        raw = llm_client.chat([
            {"role": "system", "content": _SELFCHECK_SYSTEM},
            {"role": "user", "content": user_msg},
        ], temperature=0.1)
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)
        parsed = json.loads(cleaned)
        checks = parsed.get("checks", [])
    except Exception as e:
        logger.warning("废标自查 LLM 判定失败: %s", e)
        return [], "unknown"

    valid_ids = {c["id"] for c in clauses}
    result_checks = []
    for ch in checks:
        cid = ch.get("clause_id", "")
        if cid not in valid_ids:
            continue
        status = ch.get("status", "uncertain")
        if status not in ("safe", "risk", "uncertain"):
            status = "uncertain"
        result_checks.append({
            "clause_id": cid,
            "status": status,
            "reason": str(ch.get("reason", "")).strip(),
        })

    risks = sum(1 for c in result_checks if c["status"] == "risk")
    uncertain = sum(1 for c in result_checks if c["status"] == "uncertain")
    if not result_checks:
        verdict = "unknown"
    elif risks == 0 and uncertain == 0:
        verdict = "safe"
    elif risks == 0:
        verdict = "attention"
    else:
        verdict = "danger"
    return result_checks, verdict


# ========== 降级: 关键词扫描 ==========

def _fallback_extract(content: str) -> list[dict[str, Any]]:
    """LLM 失败时, 按'否决/废标/无效投标'关键词切句扫描."""
    # 按句号/分号/换行切分
    sentences = re.split(r"[。;；\n]+", content)
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for s in sentences:
        s = s.strip()
        if len(s) < 6 or len(s) > 200:
            continue
        if not any(kw in s for kw in _REJECTION_KEYWORDS):
            continue
        key = s[:40]
        if key in seen:
            continue
        seen.add(key)
        category = "其他"
        for cat, kws in _CATEGORY_RULES:
            if any(k in s for k in kws):
                category = cat
                break
        found.append({
            "category": category,
            "clause_text": s,
            "requirement": "",
            "risk_level": "中",
            "tip": "",
        })
    return found
