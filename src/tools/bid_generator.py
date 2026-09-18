"""投标书辅助生成: 章节级生成器.

Agent 调用方式 (通过 skill 触发):
  1. 先 RAG 检索同类案例
  2. 调用本模块生成章节草稿
  3. 输出 Markdown + 占位符

也可独立 API 调用:
  POST /api/bid/generate  →  完整草稿
  POST /api/bid/section   →  单章
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# 5 个核心章节定义: 标题 + 生成 prompt 模板
SECTIONS: dict[str, dict[str, str]] = {
    "technical": {
        "title": "技术方案",
        "prompt": (
            "请为以下招标项目撰写【技术方案】章节 (600-800 字):\n\n"
            "## 招标要求\n{tender_info}\n\n"
            "## 同类案例参考\n{cases}\n\n"
            "写作要点:\n"
            "1. 技术路线与架构: 清晰描述实现方案\n"
            "2. 方案优势: 3-5 点差异化优势\n"
            "3. 关键技术指标: 对标招标要求的参数响应表\n"
            "4. 风险与应对: 可能的技术风险及预案\n\n"
            "格式: Markdown. 占位符用 [公司全称]/[具体参数] 标注.\n"
            "禁止编造资质编号或具体数据."
        ),
    },
    "commercial": {
        "title": "商务报价说明",
        "prompt": (
            "请为以下招标项目撰写【商务报价说明】章节 (300-500 字):\n\n"
            "## 招标要求\n{tender_info}\n\n"
            "## 同类案例参考\n{cases}\n\n"
            "写作要点:\n"
            "1. 报价依据与原则\n"
            "2. 分项报价说明 (用 Markdown 表格)\n"
            "3. 优惠条件与付款方式\n"
            "4. 价格有效期\n\n"
            "⚠️ 所有具体金额标注为 [参考值, 以实际测算为准]\n"
            "预算参考: {budget}"
        ),
    },
    "qualification": {
        "title": "资格声明",
        "prompt": (
            "请为以下招标项目撰写【资格声明】章节 (300-400 字):\n\n"
            "## 招标要求\n{tender_info}\n\n"
            "写作要点:\n"
            "1. 投标人资格声明 (法人/资质/财务)\n"
            "2. 无重大违法记录声明\n"
            "3. 信用状况声明\n"
            "4. 资质证书清单 (占位)\n\n"
            "⚠️ 证书编号统一用 [资质证书编号] 占位, 不编造"
        ),
    },
    "project_management": {
        "title": "项目管理方案",
        "prompt": (
            "请为以下招标项目撰写【项目管理方案】章节 (400-600 字):\n\n"
            "## 招标要求\n{tender_info}\n\n"
            "## 同类案例参考\n{cases}\n\n"
            "写作要点:\n"
            "1. 项目组织架构 (项目经理、技术负责人、团队)\n"
            "2. 里程碑计划 (时间节点表)\n"
            "3. 沟通与汇报机制\n"
            "4. 质量管理体系\n\n"
            "项目经理简历用占位符 [项目经理姓名/资质]"
        ),
    },
    "after_sales": {
        "title": "售后服务方案",
        "prompt": (
            "请为以下招标项目撰写【售后服务方案】章节 (300-500 字):\n\n"
            "## 招标要求\n{tender_info}\n\n"
            "写作要点:\n"
            "1. 服务响应机制 (7x24/2小时响应等)\n"
            "2. 质保期承诺\n"
            "3. 培训方案 (用户培训/运维培训)\n"
            "4. 备品备件保障\n\n"
            "响应时间等标注为 [服务承诺, 以公司标准为准]"
        ),
    },
}


def _summarize_tender_info(parsed: dict) -> str:
    """把 document_parser 输出的 dict 压缩成 LLM prompt 友好的文本."""
    lines = []
    if parsed.get("project_name"):
        lines.append(f"项目名称: {parsed['project_name']}")
    if parsed.get("project_code"):
        lines.append(f"项目编号: {parsed['project_code']}")
    if parsed.get("purchaser"):
        lines.append(f"采购人: {parsed['purchaser']}")
    if parsed.get("subject_matter"):
        lines.append(f"采购内容: {parsed['subject_matter']}")
    if parsed.get("budget"):
        lines.append(f"预算/最高限价: {parsed['budget']}")
    qr = parsed.get("qualification_requirements") or []
    if qr:
        lines.append("资质要求:")
        for q in qr:
            lines.append(f"  - {q}")
    if parsed.get("scoring_criteria"):
        lines.append(f"评分方法: {parsed['scoring_criteria']}")
    if parsed.get("deadline"):
        lines.append(f"投标截止: {parsed['deadline']}")
    return "\n".join(lines) if lines else "(用户未提供详细招标要求)"


def _summarize_cases(cases: list[dict]) -> str:
    if not cases:
        return "(暂无同类案例参考)"
    parts = []
    for i, c in enumerate(cases[:3], 1):
        q = c.get("question") or c.get("title") or ""
        a = c.get("answer") or c.get("content") or ""
        source = c.get("source_file") or c.get("source") or ""
        parts.append(f"【案例{i}】{q[:100]}\n  {a[:200]}\n  来源: {source}")
    return "\n\n".join(parts)


def build_section_messages(
    parsed_tender: dict,
    section_key: str,
    similar_cases: list[dict] | None = None,
    budget_hint: str = "",
) -> tuple[str, str]:
    """构造单章生成所需的 (system, user) 消息, 供同步/流式两条路径复用."""
    if section_key not in SECTIONS:
        raise ValueError(f"未知章节: {section_key}, 可选: {list(SECTIONS)}")
    section = SECTIONS[section_key]
    tender_text = _summarize_tender_info(parsed_tender)
    cases_text = _summarize_cases(similar_cases or [])
    budget = budget_hint or parsed_tender.get("budget") or "(未提供)"
    user_msg = section["prompt"].format(
        tender_info=tender_text, cases=cases_text, budget=budget)
    system_msg = (
        "你是资深投标文件撰稿人. 根据招标要求和参考案例, "
        "撰写专业、可落地的投标章节草稿. "
        "严格遵守所有禁止事项: 不编造具体资质编号/财务数据."
    )
    return system_msg, user_msg


def generate_section(
    parsed_tender: dict,
    section_key: str,
    similar_cases: list[dict] | None = None,
    llm_client=None,
    budget_hint: str = "",
) -> str:
    """生成单个章节.

    Args:
        parsed_tender: document_parser.parse_file() 输出的 dict, 或用户直接给的招标信息
        section_key: technical / commercial / qualification / project_management / after_sales
        similar_cases: RAG 检索到的同类案例 (可选)
        llm_client: LLM 客户端, 默认从 llm_factory 获取
        budget_hint: 预算补充说明
    """
    if section_key not in SECTIONS:
        raise ValueError(f"未知章节: {section_key}, 可选: {list(SECTIONS)}")

    if llm_client is None:
        from src.clients.llm_factory import get_llm_client
        llm_client = get_llm_client()

    system_msg, user_msg = build_section_messages(
        parsed_tender, section_key, similar_cases, budget_hint)
    content = llm_client.chat([
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ], temperature=0.4)

    return f"## {SECTIONS[section_key]['title']}\n\n{content.strip()}"


def stream_section(
    parsed_tender: dict,
    section_key: str,
    similar_cases: list[dict] | None = None,
    llm_client=None,
    budget_hint: str = "",
):
    """流式生成单章正文 (不含标题, 标题由调用方用 SECTIONS[key]['title'] 拼接)."""
    if llm_client is None:
        from src.clients.llm_factory import get_llm_client
        llm_client = get_llm_client()
    system_msg, user_msg = build_section_messages(
        parsed_tender, section_key, similar_cases, budget_hint)
    yield from llm_client.chat_stream([
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ], temperature=0.4)


def generate_full_bid(
    parsed_tender: dict,
    similar_cases: list[dict] | None = None,
    llm_client=None,
    sections: list[str] | None = None,
) -> str:
    """生成完整投标书草稿 (所有章节)."""
    if sections is None:
        sections = list(SECTIONS.keys())

    parts: list[str] = [
        f"# 投标书草稿: {parsed_tender.get('project_name', '(未指定项目)')}",
        "",
        f"**项目编号**: {parsed_tender.get('project_code', '-')}  ",
        f"**采购人**: {parsed_tender.get('purchaser', '-')}  ",
        f"**预算**: {parsed_tender.get('budget', '-')}  ",
        f"**投标截止**: {parsed_tender.get('deadline', '-')}",
        "",
        "---",
        "",
    ]

    for key in sections:
        logger.info("  📝 生成章节: %s", SECTIONS[key]["title"])
        try:
            sec_text = generate_section(parsed_tender, key, similar_cases, llm_client)
        except Exception as e:
            logger.warning("  章节 %s 生成失败: %s", key, e)
            sec_text = f"## {SECTIONS[key]['title']}\n\n_本章生成失败, 请手动补充_\n"
        parts.append(sec_text)
        parts.append("")

    # 待补清单
    parts.extend([
        "---",
        "",
        "## 📋 待补清单 (所有占位符汇总)",
        "",
        "- [ ] [公司全称] — 公司正式名称",
        "- [ ] [公司地址] — 注册地址",
        "- [ ] [法定代表人] — 姓名 + 职务",
        "- [ ] [资质证书编号] — 按招标要求逐项填",
        "- [ ] [项目经理姓名/资质] — 项目经理简历",
        "- [ ] [参考值, 以实际测算为准] — 商务报价数字",
        "- [ ] [具体参数] — 技术参数响应表",
        "- [ ] [服务承诺, 以公司标准为准] — 售后条款",
    ])

    return "\n".join(parts)


def suggest_sections(parsed_tender: dict) -> list[str]:
    """根据招标要求, 智能推荐应覆盖哪些章节 (简单规则)."""
    qr = (parsed_tender.get("qualification_requirements") or [])
    sm = parsed_tender.get("subject_matter") or ""
    has_budget = bool(parsed_tender.get("budget"))

    rec = ["qualification"]  # 资格声明总是需要
    if any(k in (parsed_tender.get("qualification_requirements", []) if isinstance(qr, list) else [qr])
           or k in sm for k in ("技术", "系统", "软件", "设备", "工程", "服务")):
        rec.append("technical")
    if has_budget or any(k in sm for k in ("采购", "货物", "设备")):
        rec.append("commercial")
    if any(k in sm for k in ("项目", "工程", "实施", "建设")):
        rec.append("project_management")
    if any(k in sm for k in ("服务", "运维", "保障")):
        rec.append("after_sales")

    # 去重保序
    seen = set()
    result = []
    for r in rec:
        if r not in seen:
            seen.add(r)
            result.append(r)
    return result
