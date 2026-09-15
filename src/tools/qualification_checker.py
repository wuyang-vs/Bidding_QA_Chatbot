"""资格审查辅助 — 招标文件资质要求 vs 企业资质清单 → 匹配报告.

核心流程:
  1. 输入: 招标要求清单 (list[str]) + 企业资质清单 (list[str])
  2. LLM 语义匹配 (处理同义词: "建筑一级" ≈ "施工总承包一级")
  3. 输出: ✅满足 / ⚠️部分 / ❌缺失 + 缺口建议

设计:
  - LLM 失败时有关键词 fallback (contains 匹配)
  - 要求为空时返回 "未检测到资质要求" 而非空结果
  - 独立模块, 可被 Agent skill 或 API 直接调用
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


_CHECK_SYSTEM = (
    "你是招投标资格审查专家. 根据用户提供的招标项目资质要求清单和投标人企业资质清单, "
    "逐条比对并判定满足程度.\n\n"
    "判定标准:\n"
    "  ✅ FULL_MATCH   — 企业资质完全覆盖招标要求 (含同义词/等价表述)\n"
    "  ⚠️ PARTIAL_MATCH — 企业资质部分覆盖 (如招标要'一级', 企业只有'二级')\n"
    "  ❌ NO_MATCH     — 企业完全没有相关资质\n"
    "  ⚠️ INFO_MISSING — 招标要求描述含糊, 无法判定 (需人工补充)\n\n"
    "同义词示例 (自行扩展):\n"
    "  '建筑一级资质' = '建筑工程施工总承包一级' = '房建一级'\n"
    "  '电子与智能化' = '智能化工程' = '弱电工程'\n"
    "  'ISO9001' = '质量管理体系认证'\n"
    "  'CSDN' = '信息系统集成及服务资质'\n\n"
    "只输出 JSON, 不要任何额外文字或代码块标记."
)


def _clean_list(items: list[str] | None) -> list[str]:
    if not items:
        return []
    return [str(i).strip() for i in items if i and str(i).strip()]


def check_qualification(
    tender_requirements: list[str] | None,
    company_qualifications: list[str] | None,
    llm_client=None,
) -> dict[str, Any]:
    """执行资格比对.

    Args:
        tender_requirements: 招标文件列出的资质要求 (来自 document_parser.qualification_requirements)
        company_qualifications: 用户提供的企业资质清单

    Returns:
        {
            "summary": {"total_req": N, "full": N, "partial": N, "missing": N, "coverage": "XX%"},
            "checks": [
                {
                    "requirement": "招标要求原文",
                    "status": "FULL_MATCH|PARTIAL_MATCH|NO_MATCH|INFO_MISSING",
                    "matched_qualification": "企业匹配到的资质 (NO_MATCH 时为空)",
                    "detail": "简要说明/缺口建议",
                }
            ],
            "gap_report": "汇总缺口清单 + 行动建议",
            "verdict": "pass|attention|fail",
            "note": "LLM 失败时的降级提示 (可能不存在)",
        }
    """
    reqs = _clean_list(tender_requirements)
    quals = _clean_list(company_qualifications)

    # 空输入边界处理
    if not reqs:
        return {
            "summary": {"total_req": 0, "full": 0, "partial": 0, "missing": 0, "coverage": "N/A"},
            "checks": [],
            "gap_report": "⚠️ 未检测到招标文件中的资质要求, 无法进行比对. 请确认招标文件是否已正确解析.",
            "verdict": "unknown",
        }
    if not quals:
        return {
            "summary": {"total_req": len(reqs), "full": 0, "partial": 0, "missing": len(reqs),
                        "coverage": "0%"},
            "checks": [
                {"requirement": r, "status": "NO_MATCH",
                 "matched_qualification": "",
                 "detail": "企业未提供任何资质清单, 无法匹配"}
                for r in reqs
            ],
            "gap_report": f"❌ 企业资质清单为空, 无法进行比对. 请提供至少 {len(reqs)} 项资质.",
            "verdict": "fail",
        }

    if llm_client is None:
        from src.clients.llm_factory import get_llm_client
        llm_client = get_llm_client()

    user_msg = (
        f"【招标资质要求】\n"
        + "\n".join(f"  {i + 1}. {r}" for i, r in enumerate(reqs))
        + f"\n\n【企业资质清单】\n"
        + "\n".join(f"  {i + 1}. {q}" for i, q in enumerate(quals))
        + "\n\n请逐条比对, 输出 JSON:"
        + '\n{"checks": ['
        + '{"requirement": "...", "status": "FULL_MATCH|PARTIAL_MATCH|NO_MATCH|INFO_MISSING", '
        + '"matched_qualification": "...", "detail": "..."}'
        + "]}"
    )

    import json

    try:
        raw = llm_client.chat([
            {"role": "system", "content": _CHECK_SYSTEM},
            {"role": "user", "content": user_msg},
        ], temperature=0.1)
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)
        parsed = json.loads(cleaned)
        checks = parsed.get("checks", [])
    except Exception as e:
        logger.warning("LLM 资格审查失败, 降级为关键词匹配: %s", e)
        checks = _fallback_match(reqs, quals)

    # 汇总
    full = sum(1 for c in checks if c.get("status") == "FULL_MATCH")
    partial = sum(1 for c in checks if c.get("status") == "PARTIAL_MATCH")
    missing = sum(1 for c in checks if c.get("status") in ("NO_MATCH", "INFO_MISSING"))
    total = len(checks) or len(reqs)

    coverage = f"{int((full + partial * 0.5) / total * 100)}%" if total > 0 else "N/A"
    if missing == 0:
        verdict = "pass"
    elif full >= total * 0.7 and missing <= 2:
        verdict = "attention"
    else:
        verdict = "fail"

    gap_lines = []
    for c in checks:
        if c.get("status") in ("NO_MATCH", "PARTIAL_MATCH"):
            gap_lines.append(
                f"  ❌ 要求: {c['requirement']}\n"
                f"     状态: {c['status']}  匹配: {c.get('matched_qualification', '无')}\n"
                f"     建议: {c.get('detail', '-')}"
            )
    gap_report = "## 资格审查缺口报告\n\n"
    gap_report += f"- **招标要求**: {total} 项\n"
    gap_report += f"- **完全满足**: {full} 项 ✅\n"
    gap_report += f"- **部分满足**: {partial} 项 ⚠️\n"
    gap_report += f"- **缺失/不满足**: {missing} 项 ❌\n"
    gap_report += f"- **覆盖率**: {coverage}\n\n"
    if gap_lines:
        gap_report += "### 缺口详情\n\n" + "\n\n".join(gap_lines)
    else:
        gap_report += "### 结论\n\n✅ **所有资质要求均已满足, 可以投标.**"

    result = {
        "summary": {
            "total_req": total, "full": full, "partial": partial,
            "missing": missing, "coverage": coverage,
        },
        "checks": checks,
        "gap_report": gap_report,
        "verdict": verdict,
    }
    if gap_lines or verdict != "pass":
        result["action_suggestions"] = [
            "1. 优先补齐 NO_MATCH 项的资质证书",
            "2. PARTIAL_MATCH 项评估是否可接受或需升级",
            "3. INFO_MISSING 项建议人工复核招标文件原文",
        ]
    return result


def _fallback_match(reqs: list[str], quals: list[str]) -> list[dict[str, Any]]:
    """LLM 失败时的关键词包含匹配降级."""
    checks = []
    for req in reqs:
        found = []
        for q in quals:
            # 双向包含判断
            if req and q and (req in q or q in req):
                found.append(q)
        if found:
            checks.append({
                "requirement": req, "status": "FULL_MATCH",
                "matched_qualification": found[0],
                "detail": f"关键词包含匹配: {found[0]}",
            })
        else:
            checks.append({
                "requirement": req, "status": "NO_MATCH",
                "matched_qualification": "",
                "detail": "未找到关键词匹配 (降级模式, 建议 LLM 重新检查)",
            })
    return checks
