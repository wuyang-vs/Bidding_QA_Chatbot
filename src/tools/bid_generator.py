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
import re
from datetime import date
from typing import Any

from src.tools.company_profile import (
    apply_profile_placeholders, fill_placeholders_stream, profile_prompt_block,
    unfilled_notice,
)

logger = logging.getLogger(__name__)


def _strip_code_fence(text: str) -> str:
    """领域模型偶尔把整段正文包进 ```markdown 代码围栏, 剥掉以保证 Markdown 正常渲染."""
    m = re.match(r"^```(?:markdown|md)?\s*\n(.*?)\n?```\s*$", text, re.DOTALL)
    return m.group(1) if m else text


def _ensure_bidder_identity(body: str, company_profile: dict | None, fill_info: dict) -> str:
    """企业资料已提供但 LLM 正文未引用公司名时的确定性身份注入 (BID-04 根因兜底).

    领域模型会忽略企业资料块且不写占位符, 导致回填链路完全落空.
    此时在首个标题行之后插入"投标人：公司全称", 保证标书正文始终体现投标人主体;
    并把"公司全称"计入 fill_info.filled, 与占位符回填行为对齐.
    """
    from src.tools.company_profile import _norm
    p = _norm(company_profile)
    name = (p.get("company_name") or "").strip()
    if not name:
        return body
    body = _strip_code_fence(body)
    if name in body:
        return body
    lines = body.splitlines()
    insert_at = 0
    for i, ln in enumerate(lines[:5]):
        if ln.lstrip().startswith("#"):
            insert_at = i + 1
            break
    lines.insert(insert_at, f"\n投标人：{name}\n")
    filled = fill_info.setdefault("filled", [])
    if "公司全称" not in filled:
        filled.append("公司全称")
    return "\n".join(lines)


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
    company_profile: dict | None = None,
) -> tuple[str, str]:
    """构造单章生成所需的 (system, user) 消息, 供同步/流式两条路径复用。"""
    if section_key not in SECTIONS:
        raise ValueError(f"未知章节: {section_key}, 可选: {list(SECTIONS)}")
    section = SECTIONS[section_key]
    tender_text = _summarize_tender_info(parsed_tender)
    cases_text = _summarize_cases(similar_cases or [])
    budget = budget_hint or parsed_tender.get("budget") or "(未提供)"
    user_msg = section["prompt"].format(
        tender_info=tender_text, cases=cases_text, budget=budget)
    profile_block = profile_prompt_block(company_profile)
    if profile_block:
        user_msg += "\n\n" + profile_block
    system_msg = (
        "你是资深投标文件撰稿人. 根据招标要求和参考案例, "
        "撰写专业、可落地的投标章节草稿. "
        "严格遵守所有禁止事项: 不编造具体资质编号/财务数据. "
        "若提供了投标人企业资料, 必须直接使用真实公司全称/姓名/编号, "
        "不得把 [公司全称]/[法定代表人] 等已给资料的占位符写进正文."
    )
    return system_msg, user_msg


def generate_section(
    parsed_tender: dict,
    section_key: str,
    similar_cases: list[dict] | None = None,
    llm_client=None,
    budget_hint: str = "",
    company_profile: dict | None = None,
) -> tuple[str, dict]:
    """生成单个章节并做企业资料占位符回填。

    Returns:
        (markdown, fill_info)  fill_info 见 apply_profile_placeholders
    """
    if section_key not in SECTIONS:
        raise ValueError(f"未知章节: {section_key}, 可选: {list(SECTIONS)}")

    if llm_client is None:
        from src.clients.llm_factory import get_llm_client
        llm_client = get_llm_client()

    system_msg, user_msg = build_section_messages(
        parsed_tender, section_key, similar_cases, budget_hint, company_profile)
    content = llm_client.chat([
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ], temperature=0.4)

    body, fill_info = apply_profile_placeholders(content.strip(), company_profile)
    body = _ensure_bidder_identity(body, company_profile, fill_info)
    md = f"## {SECTIONS[section_key]['title']}\n\n{body}"
    return md, fill_info


def stream_section(
    parsed_tender: dict,
    section_key: str,
    similar_cases: list[dict] | None = None,
    llm_client=None,
    budget_hint: str = "",
    company_profile: dict | None = None,
):
    """流式生成单章正文 (占位符实时回填, 不含章节标题)。"""
    if llm_client is None:
        from src.clients.llm_factory import get_llm_client
        llm_client = get_llm_client()
    system_msg, user_msg = build_section_messages(
        parsed_tender, section_key, similar_cases, budget_hint, company_profile)
    raw = llm_client.chat_stream([
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ], temperature=0.4)
    yield from fill_placeholders_stream(raw, company_profile)


def build_cover(tender: dict, company_profile: dict | None = None) -> str:
    """整本投标书封面 + 编制信息。"""
    from src.tools.company_profile import _norm
    p = _norm(company_profile)
    project = tender.get("project_name") or "(未指定项目)"
    today = date.today().isoformat()
    lines = [
        f"# {project}",
        "",
        "# 投 标 文 件",
        "",
        "",
        f"**投标人（盖章）**：{p.get('company_name') or '[公司全称]'}  ",
        f"**法定代表人或授权代表**：{p.get('legal_person') or '[法定代表人]'}  ",
        f"**项目编号**：{tender.get('project_code') or '-'}  ",
        f"**采购人**：{tender.get('purchaser') or '-'}  ",
        f"**投标截止时间**：{tender.get('deadline') or '-'}  ",
        f"**编制日期**：{today}",
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


def build_toc(section_keys: list[str]) -> str:
    lines = ["## 目 录", ""]
    for i, key in enumerate(section_keys, 1):
        lines.append(f"{i}. {SECTIONS[key]['title']}")
    lines += ["", "---", ""]
    return "\n".join(lines)


def assemble_full_bid(tender: dict, section_mds: list[tuple[str, str]],
                      company_profile: dict | None = None,
                      matrix_md: str = "") -> tuple[str, dict]:
    """把各章 Markdown 合为整本; 汇总占位符回填情况并追加待补清单。

    Args:
        section_mds: [(section_key, markdown), ...] 已生成并回填的章节
        matrix_md: 逐条响应对照表 Markdown (可选, 作为附录)
    Returns:
        (整本 markdown, fill_info 聚合)
    """
    keys = [k for k, _ in section_mds]
    parts = [build_cover(tender, company_profile), build_toc(keys)]
    for _, md in section_mds:
        parts.append(md)
        parts.append("")
    if matrix_md:
        parts.append("---")
        parts.append("")
        parts.append(matrix_md)
        parts.append("")
    # 整本层面扫描残留占位符并生成待补清单
    from src.tools.company_profile import apply_profile_placeholders
    full_so_far = "\n".join(parts)
    _, info = apply_profile_placeholders(full_so_far, company_profile)
    notice = unfilled_notice(info)
    if notice:
        parts.append(notice)
    return "\n".join(parts), info


def generate_full_bid(
    parsed_tender: dict,
    similar_cases: list[dict] | None = None,
    llm_client=None,
    sections: list[str] | None = None,
    company_profile: dict | None = None,
) -> tuple[str, dict]:
    """生成完整投标书草稿 (所有章节, 同步)。

    Returns:
        (整本 markdown, 聚合 fill_info)
    """
    if sections is None:
        sections = list(SECTIONS.keys())

    section_mds: list[tuple[str, str]] = []
    for key in sections:
        logger.info("  📝 生成章节: %s", SECTIONS[key]["title"])
        try:
            sec_text, _info = generate_section(
                parsed_tender, key, similar_cases, llm_client,
                company_profile=company_profile)
        except Exception as e:
            logger.warning("  章节 %s 生成失败: %s", key, e)
            sec_text = f"## {SECTIONS[key]['title']}\n\n_本章生成失败, 请手动补充_\n"
        section_mds.append((key, sec_text))

    return assemble_full_bid(parsed_tender, section_mds, company_profile)


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
