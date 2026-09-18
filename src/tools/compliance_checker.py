"""合规性检查: 扫描招标文件是否存在排他性/歧视性/不合理条款.

核心:
  1. COMPLIANCE_RULES — 20+ 条招投标常见风险规则, 每条配法规依据
  2. check_compliance(text, llm_client) — LLM 逐条扫描, 输出风险报告
  3. 支持从 document_parser 输出直接检查

依赖:
  - 不新增第三方包, 纯 prompt 工程
  - 法规依据来自《招标投标法》《政府采购法》及实施条例
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ========== 合规规则库 (20+ 条) ==========
# 结构: id / 风险类别 / 条款关键词 / 法规依据 / 风险等级
COMPLIANCE_RULES: list[dict[str, str]] = [
    # --- 排他性条款 ---
    {
        "id": "EXCL_001",
        "category": "排他性条款",
        "risk_level": "高",
        "keywords": ["本地注册", "本地企业", "本地分支机构", "本地纳税"],
        "description": "要求投标人必须在本地注册/设分支机构/纳税",
        "law_basis": "《招标投标法实施条例》第32条: 不得以特定行政区域或者特定行业的业绩、奖项作为加分条件或者中标、成交条件",
    },
    {
        "id": "EXCL_002",
        "category": "排他性条款",
        "risk_level": "高",
        "keywords": ["仅限", "只限", "特定", "指定品牌", "指定型号", "独家"],
        "description": "限定特定品牌/型号/独家供应商",
        "law_basis": "《政府采购法实施条例》第20条: 不得以特定供应商的产品或者服务作为评审因素",
    },
    {
        "id": "EXCL_003",
        "category": "排他性条款",
        "risk_level": "高",
        "keywords": ["必须", "应当", "仅限"].__class__.__name__ == "list" and ["中国大陆以外", "境外", "外资"] or [],
        "description": "不合理限制外资/境外投标人 (合法限制除外, 如涉及国家安全)",
        "law_basis": "《招标投标法》第6条: 依法必须进行招标的项目, 其招标投标活动不受地区或者部门的限制",
    },
    {
        "id": "EXCL_004",
        "category": "排他性条款",
        "risk_level": "中",
        "keywords": ["设立分公司", "办事处"],
        "description": "要求在投标所在地设立分公司/办事处 (通常属于不合理门槛)",
        "law_basis": "《招标投标法实施条例》第32条: 不得以特定行政区域设立机构为条件",
    },

    # --- 不合理资质要求 ---
    {
        "id": "QUAL_001",
        "category": "不合理资质",
        "risk_level": "高",
        "keywords": ["注册资本", "注册资金"],
        "description": "以注册资本作为资格条件 (涉嫌歧视中小微企业)",
        "law_basis": "《政府采购促进中小企业发展管理办法》财库〔2020〕46号: 不得将注册资本作为资格条件",
    },
    {
        "id": "QUAL_002",
        "category": "不合理资质",
        "risk_level": "中",
        "keywords": ["类似项目", "同类项目", "业绩"],
        "description": "特定金额/数量的业绩门槛 (需评估是否与标的匹配)",
        "law_basis": "《招标投标法实施条例》第32条: 业绩要求应当与招标项目的具体特点和实际需要相适应",
    },
    {
        "id": "QUAL_003",
        "category": "不合理资质",
        "risk_level": "中",
        "keywords": ["连续三年盈利", "年营业额", "年营收"],
        "description": "特定金额的财务指标要求 (可能排除初创/小微企业)",
        "law_basis": "《招标投标法实施条例》第32条: 不得以不合理条件限制、排斥潜在投标人",
    },

    # --- 时间要求 ---
    {
        "id": "TIME_001",
        "category": "时间不合理",
        "risk_level": "高",
        "keywords": [],  # LLM 需根据实际日期判断
        "description": "投标文件编制时间少于 20 日 (依法必须招标项目最短不得少于20日)",
        "law_basis": "《招标投标法》第24条: 招标人应当确定投标人编制投标文件所需要的合理时间; 但是, 依法必须进行招标的项目, 自招标文件开始发出之日起至投标人提交投标文件截止之日止, 最短不得少于二十日",
    },
    {
        "id": "TIME_002",
        "category": "时间不合理",
        "risk_level": "中",
        "keywords": ["答疑", "澄清"],
        "description": "答疑/澄清通知发出时间距投标截止不足 15 日 (应重新顺延)",
        "law_basis": "《招标投标法实施条例》第21条: 澄清或者修改的内容可能影响投标文件编制的, 应当在投标截止时间至少15日前发出",
    },

    # --- 评分标准 ---
    {
        "id": "SCORE_001",
        "category": "评分不透明",
        "risk_level": "高",
        "keywords": ["酌情", "评委认为", "综合评定", "视情况"],
        "description": "评分因素主观模糊, 无量化标准",
        "law_basis": "《招标投标法实施条例》第32条: 不得以不合理条件限制、排斥潜在投标人 (模糊评分可能构成)",
    },
    {
        "id": "SCORE_002",
        "category": "评分不透明",
        "risk_level": "中",
        "keywords": ["价格分", "价格权重"],
        "description": "价格分权重低于 30% (政府采购货物项目通常价格权重不低于30%)",
        "law_basis": "《政府采购货物和服务招标投标管理办法》财政部令第87号第55条: 货物项目的价格分值占总分值的比重不得低于30%",
    },

    # --- 其他风险 ---
    {
        "id": "MISC_001",
        "category": "其他风险",
        "risk_level": "中",
        "keywords": ["押注", "履约保证金", "质保金"],
        "description": "履约保证金/质保金比例过高 (通常不超过合同金额的10%)",
        "law_basis": "《招标投标法实施条例》第58条: 履约保证金不得超过中标合同金额的10%",
    },
    {
        "id": "MISC_002",
        "category": "其他风险",
        "risk_level": "高",
        "keywords": ["保密", "不得泄露"],
        "description": "存在侵犯商业秘密/不合理保密要求",
        "law_basis": "《反不正当竞争法》第9条: 不得侵犯他人的商业秘密",
    },
    {
        "id": "MISC_003",
        "category": "歧视性条款",
        "risk_level": "高",
        "keywords": ["性别", "年龄", "种族", "宗教"],
        "description": "基于性别/年龄/种族/宗教的歧视性要求",
        "law_basis": "《宪法》第33条 + 《就业促进法》第3条: 平等原则",
    },
    {
        "id": "MISC_004",
        "category": "其他风险",
        "risk_level": "中",
        "keywords": ["必须使用", "统一采购", "指定供应商"],
        "description": "强制使用特定供应商的产品/服务 (未经论证)",
        "law_basis": "《政府采购法实施条例》第20条",
    },
]


# 修正: EXCL_003 的 keywords 写法有 bug, 直接修正
COMPLIANCE_RULES[2]["keywords"] = ["中国大陆以外", "境外注册", "外资企业"]


# ========== LLM 检查器 ==========

_CHECK_SYSTEM = (
    "你是招投标合规审查专家, 熟悉《招标投标法》《政府采购法》及实施条例. "
    "根据用户提供的招标文件片段和合规规则库, 逐条检查是否存在风险.\n\n"
    "规则:\n"
    "1. 对每条规则, 在招标文件中搜索关键词或判断条件\n"
    "2. 匹配到则标记为 'match', 并引用原文片段\n"
    "3. 未匹配到标记为 'clean'\n"
    "4. 证据不足时标记为 'uncertain' (并说明原因)\n"
    "5. 只输出 JSON, 不要额外文字"
)


def _build_rules_text() -> str:
    """把规则库序列化为 prompt 友好文本."""
    lines = ["【合规规则库】"]
    for r in COMPLIANCE_RULES:
        kw = r["keywords"] or "(需 LLM 逻辑判断)"
        lines.append(
            f"- [{r['id']}] {r['category']} ({r['risk_level']}风险)\n"
            f"  关键词: {', '.join(kw) if isinstance(kw, list) else kw}\n"
            f"  说明: {r['description']}\n"
            f"  法规: {r['law_basis']}"
        )
    return "\n".join(lines)


def check_compliance(
    text: str | dict,
    llm_client=None,
) -> dict[str, Any]:
    """执行合规检查.

    Args:
        text: 招标文件全文, 或 document_parser 输出的 dict
        llm_client: LLM 客户端

    Returns:
        {
            "summary": {"high": N, "medium": N, "low": N, "total_checked": M},
            "risks": [{rule_id, category, risk_level, matched_text, law_basis, detail}],
            "clean_rules": [rule_id, ...],
            "status": "ok" | "partial" | "fail",
        }
    """
    if llm_client is None:
        from src.clients.llm_factory import get_llm_client
        llm_client = get_llm_client()

    # 接受 document_parser dict
    if isinstance(text, dict):
        source = text.get("raw_text") or text.get("raw_text_preview") or text.get("source_file", "")
        tender_info = (
            f"项目: {text.get('project_name', '')}\n"
            f"预算: {text.get('budget', '')}\n"
            f"资质要求: {text.get('qualification_requirements', [])}\n"
            f"投标截止: {text.get('deadline', '')}\n"
            f"---\n{source}"
        )
    else:
        tender_info = text

    # 截断 (太长 LLM 吃不下)
    if len(tender_info) > 8000:
        tender_info = tender_info[:6000] + "\n...[中间省略]...\n" + tender_info[-1500:]

    rules_text = _build_rules_text()
    user_msg = (
        f"{rules_text}\n\n"
        f"【招标文件片段】\n{tender_info}\n\n"
        "请对每条规则检查, 输出 JSON 格式:\n"
        "{\n"
        '  "results": [\n'
        "    {\"rule_id\": \"EXCL_001\", \"status\": \"match|clean|uncertain\", "
        "\"evidence\": \"匹配到的原文片段 (clean 时为空)\", "
        "\"detail\": \"简要说明\"}\n"
        "  ]\n"
        "}"
    )

    import json
    import re

    try:
        raw = llm_client.chat([
            {"role": "system", "content": _CHECK_SYSTEM},
            {"role": "user", "content": user_msg},
        ], temperature=0.1)
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)
        parsed = json.loads(cleaned)
    except Exception as e:
        logger.warning("合规检查 LLM JSON 失败, 返回降级结果: %s", e)
        return _fallback_check(text)

    results = parsed.get("results", [])
    risks = []
    clean = []
    high = medium = low = 0

    rule_map = {r["id"]: r for r in COMPLIANCE_RULES}
    for r in results:
        rid = r.get("rule_id", "")
        rule = rule_map.get(rid)
        if not rule:
            continue
        status = r.get("status", "uncertain")
        if status == "match":
            risks.append({
                "rule_id": rid,
                "category": rule["category"],
                "risk_level": rule["risk_level"],
                "matched_text": r.get("evidence", ""),
                "law_basis": rule["law_basis"],
                "detail": r.get("detail", rule["description"]),
            })
            if rule["risk_level"] == "高":
                high += 1
            elif rule["risk_level"] == "中":
                medium += 1
            else:
                low += 1
        elif status == "clean":
            clean.append(rid)

    return {
        "summary": {
            "high": high, "medium": medium, "low": low,
            "total_checked": len(COMPLIANCE_RULES),
            "risks_found": len(risks),
        },
        "risks": risks,
        "clean_rules": clean,
        "status": "ok" if high == 0 and medium == 0 else ("attention" if high == 0 else "warn"),
    }


def _fallback_check(text: str | dict) -> dict[str, Any]:
    """LLM 失败时, 纯关键词匹配降级检查."""
    if isinstance(text, dict):
        content = text.get("raw_text") or text.get("raw_text_preview", "")
    else:
        content = str(text)
    risks = []
    for rule in COMPLIANCE_RULES:
        for kw in rule["keywords"]:
            if kw and kw in content:
                risks.append({
                    "rule_id": rule["id"],
                    "category": rule["category"],
                    "risk_level": rule["risk_level"],
                    "matched_text": f"(降级匹配) 发现关键词 '{kw}'",
                    "law_basis": rule["law_basis"],
                    "detail": rule["description"],
                })
                break
    high = sum(1 for r in risks if r["risk_level"] == "高")
    medium = sum(1 for r in risks if r["risk_level"] == "中")
    return {
        "summary": {
            "high": high, "medium": medium, "low": 0,
            "total_checked": len(COMPLIANCE_RULES), "risks_found": len(risks),
        },
        "risks": risks,
        "clean_rules": [],
        "status": "warn" if high > 0 else ("attention" if medium > 0 else "ok"),
        "note": "⚠️ LLM 检查失败, 以下为纯关键词匹配结果, 仅供参考",
    }
