from __future__ import annotations
"""标书生成 Agent 工具: 对话内"帮我写标书"闭环。

- list_bid_documents: 按当前身份列出可用于编标的招标文件 (行级过滤)
- generate_bid_draft: 指定 db_id 生成单个章节草稿 (行级权限 + RAG 同类案例)

两个工具的实质文本结果在硬闸门中等同"有依据"(证据来自本地招标文件),
见 src.agent.evidence_gate。
"""
import logging

from src.auth.access_scope import get_current_user
from src.tools.base import BaseTool
from src.tools.bid_generator import SECTIONS, generate_section
from src.tools.bid_service import row_to_tender
from src.tools.company_profile import get_profile
from src.tools.anomaly_catalog import get_anomaly_guidance, format_guidance_text
from src.tools.templates_catalog import recommend_templates, get_template
from src.tools.appeal_catalog import search_appeal_topics, format_appeal_text
from src.tools.guide_catalog import recognize_stage, format_guide_text

logger = logging.getLogger(__name__)

_SECTION_CHOICES = "/".join(SECTIONS.keys())


class ListBidDocuments(BaseTool):
    name: str = "list_bid_documents"
    description: str = (
        "列出当前账号可见、可用于编写投标文件的招标文件（返回文档id/文件名/项目名/预算/截止时间）。"
        "当用户要求写标书/生成投标章节但未提供 db_id 时，先调用本工具选定招标文件")
    parameters: dict = {
        "type": "object",
        "properties": {"keyword": {"type": "string", "description": "项目名/文件名关键词, 可留空"}},
        "required": [],
    }


class GenerateBidDraft(BaseTool):
    name: str = "generate_bid_draft"
    description: str = (
        "基于指定招标文件生成投标书中【一个章节】的 Markdown 草稿。"
        "db_id 就是文档数字编号 (用户说\"6号招标文件\"时 db_id=6, 直接调用本工具, 不要再调 list_bid_documents); "
        "编号不确定时才先调 list_bid_documents 查 id, 查到后【必须紧接着调用本工具】, 严禁自己代写章节。"
        f"section 可选: {_SECTION_CHOICES} (默认 technical 技术方案)。"
        "需要多章时按章节多次调用, 不要一次生成整本")
    parameters: dict = {
        "type": "object",
        "properties": {
            "db_id": {"type": "integer", "description": "招标文件 id (list_bid_documents 返回)"},
            "section": {"type": "string",
                        "enum": list(SECTIONS.keys()),
                        "description": "章节 key, 默认 technical"},
        },
        "required": ["db_id"],
    }


def _exec_list_bid_documents(args, question):
    from src.database.postgresql_client import postgresql_client
    user = get_current_user()
    if not postgresql_client.ready:
        return "PostgreSQL 未连接, 暂无法列出招标文件", []
    keyword = (args.get("keyword") or "").strip()
    items = postgresql_client.list_documents(keyword, user=user)
    if not items:
        tip = f"关键词「{keyword}」" if keyword else ""
        return f"未找到{tip}当前账号可见的招标文件, 可请用户先上传或更换关键词", []
    lines = [f"共 {len(items)} 份当前账号可见的招标文件:"]
    for x in items[:15]:
        lines.append(
            f"- id={x['id']} | {x.get('source_file') or '-'} | "
            f"项目: {x.get('project_name') or '(未解析项目名)'} | "
            f"预算: {x.get('budget') or '-'} | 截止: {x.get('deadline') or '-'}")
    lines.append("\n用户要求写标书/生成章节时, 你【必须】紧接着调用 generate_bid_draft "
                 "(db_id 用上面列出的 id, section 用用户指定或 technical), "
                 "不要根据本列表自己撰写章节内容。")
    return "\n".join(lines), []


def _exec_generate_bid_draft(args, question):
    from src.database.postgresql_client import postgresql_client
    from src.rag.pipeline import rag_pipeline
    from src.clients.llm_factory import get_llm_client

    user = get_current_user()
    db_id = args.get("db_id")
    section = args.get("section") or "technical"
    if section not in SECTIONS:
        return f"未知章节: {section}, 可选 {_SECTION_CHOICES}", []
    if not isinstance(db_id, int):
        return ("参数 db_id 缺失或非整数, 请先调用 list_bid_documents 获取招标文件 id",
                [])
    if not postgresql_client.ready:
        return "PostgreSQL 未连接, 无法读取招标文件", []
    # 行级权限: 与 /api/bid/generate 同一判定, internal 文档对越权身份拒绝
    if not postgresql_client.can_read_document(user, db_id):
        return f"无权访问招标文件 id={db_id}, 该文档可能为他人内部文件", []
    rows = postgresql_client._run(
        "SELECT * FROM bidding_documents WHERE id = :id", {"id": db_id})
    if not rows:
        return f"未找到招标文件 id={db_id}", []
    tender = row_to_tender(rows[0])

    # RAG 同类案例: pipeline 内部自行读取当前请求的 access_scope, 不跨身份
    cases = []
    if rag_pipeline.ready and tender.get("subject_matter"):
        try:
            cases = rag_pipeline.search(
                f"{tender['subject_matter']} 采购 投标 技术方案", top_k=3)[:3]
        except Exception as e:
            logger.warning("标书工具-相似案例检索失败: %s", e)

    llm = get_llm_client()
    # 当前身份企业资料: 自动回填占位符 (未登录/无档案时 profile=None, 保留占位符)
    profile = get_profile(user["id"]) if user else None
    md, fill_info = generate_section(
        tender, section, cases, llm_client=llm, company_profile=profile)
    header = (f"已基于招标文件 id={db_id}"
              f"（{tender.get('project_name') or rows[0].get('source_file')}）"
              f"生成【{SECTIONS[section]['title']}】章节草稿，请原样输出以下 Markdown：\n\n")
    tail = ""
    if profile and fill_info.get("missing_company"):
        tail = ("\n\n（提示: 以下企业资料字段缺失, 占位符未能回填: "
                + "、".join(f"[{x}]" for x in fill_info["missing_company"][:6])
                + "，可在企业资料库补全后重新生成）")
    return header + md + tail, []


BID_AGENT_TOOLS = [ListBidDocuments(), GenerateBidDraft()]

BID_AGENT_EXECUTORS = {
    "list_bid_documents": _exec_list_bid_documents,
    "generate_bid_draft": _exec_generate_bid_draft,
}


# ============ R13: 异常预警问答解释 ============

class ExplainAnomaly(BaseTool):
    name: str = "explain_anomaly"
    description: str = (
        "解释某条异常预警的原因、影响、处置建议与法规依据。"
        "当用户询问报价异常/围串标线索/资格不符/废标等预警的含义或如何修改时，"
        "传入该异常的 code（如 SUM_MISMATCH / OVER_CONTROL_PRICE / jaccard_text）"
        "返回权威解释，不要自行编造。")
    parameters: dict = {
        "type": "object",
        "properties": {
            "code": {"type": "string",
                     "description": "异常编码，如 SUM_MISMATCH/CN_MISMATCH/OVER_CONTROL_PRICE/ROW_ARITHMETIC/jaccard_text/QUALIFICATION_FAIL/REJECTION_CLAUSE"},
        },
        "required": ["code"],
    }


def _exec_explain_anomaly(args, question):
    code = (args.get("code") or "").strip()
    if not code:
        return "请提供异常 code（如 SUM_MISMATCH、OVER_CONTROL_PRICE）", []
    entry = get_anomaly_guidance(code)
    if not entry:
        return (f"暂无 code={code} 的标准解释。已知异常编码: "
                f"SUM_MISMATCH/CN_MISMATCH/CN_UNPARSEABLE/OVER_CONTROL_PRICE/"
                f"ROW_ARITHMETIC/jaccard_text/identical_line_items/"
                f"metadata_author/QUALIFICATION_FAIL/REJECTION_CLAUSE/DEVIATION_MAJOR",
                [])
    return format_guidance_text(entry), []


BID_AGENT_TOOLS.append(ExplainAnomaly())
BID_AGENT_EXECUTORS["explain_anomaly"] = _exec_explain_anomaly


# ============ R14: 范本智能推荐 ============

class RecommendTemplate(BaseTool):
    name: str = "recommend_template"
    description: str = (
        "根据用户描述的项目类型或需求，智能推荐招标文件范本/合同范本/业务表单。"
        "当用户问\"XX项目用什么招标文件/合同/表单\"或索要范本时调用。"
        "query 填项目类型或关键词（如\"工程施工\"、\"货物采购\"、\"设计服务\"）。")
    parameters: dict = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "项目类型或需求关键词"},
            "category": {"type": "string",
                         "enum": ["招标文件", "合同范本", "业务表单"],
                         "description": "范本类别，可留空"},
            "top_k": {"type": "integer", "description": "返回数量, 默认5"},
        },
        "required": ["query"],
    }


def _exec_recommend_template(args, question):
    query = (args.get("query") or "").strip()
    category = (args.get("category") or "").strip() or None
    top_k = args.get("top_k") or 5
    if not query:
        return "请提供项目类型或需求关键词（如\"工程施工\"、\"政府采购货物\"）", []
    results = recommend_templates(query, category=category, top_k=top_k)
    if not results:
        return f"未匹配到「{query}」相关范本，可尝试更通用的关键词或不限定 category", []
    lines = [f"为你推荐 {len(results)} 份相关范本:"]
    for r in results:
        lines.append(
            f"- [{r['id']}] {r['name']}（类别: {r['category']}，匹配度 {r['score']}）\n"
            f"  摘要: {r['summary']}\n"
            f"  章节: {'、'.join(r.get('sections', [])[:3])}{'...' if len(r.get('sections', [])) > 3 else ''}\n"
            f"  来源: {r.get('source_url', '-')}")
    lines.append("\n如需某份范本的完整章节清单，告知其 id（如 TPL-BID-001）。")
    return "\n".join(lines), []


BID_AGENT_TOOLS.append(RecommendTemplate())
BID_AGENT_EXECUTORS["recommend_template"] = _exec_recommend_template


# ============ R15: 异议投诉咨询 ============

class ConsultAppeal(BaseTool):
    name: str = "consult_appeal"
    description: str = (
        "咨询招标投标异议/投诉、政府采购质疑/投诉的渠道、时限、材料、流程与法律依据。"
        "当用户问\"对中标结果不服怎么办/投诉找哪个部门/异议几天内提/投诉书怎么写/"
        "质疑和投诉区别/不予受理/恶意投诉后果\"等问题时调用。"
        "query 填用户问题原文或关键词（如\"中标候选人公示有异议\"、\"政府采购质疑\"）。")
    parameters: dict = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "用户的问题或关键词，如\"对评标结果有异议怎么办\""},
            "top_k": {"type": "integer", "description": "返回主题数, 默认3"},
        },
        "required": ["query"],
    }


def _exec_consult_appeal(args, question):
    query = (args.get("query") or "").strip()
    top_k = args.get("top_k") or 3
    if not query:
        return "请描述你要咨询的问题，例如\"对中标候选人公示有异议怎么办\"", []
    results = search_appeal_topics(query, top_k=top_k)
    if not results:
        return ("未匹配到对应的异议投诉主题。可直接询问：对招标文件/开标/中标结果的异议、"
                "投诉渠道与时限、投诉书材料、不予受理情形、政府采购质疑等。", [])
    blocks = [f"为你找到 {len(results)} 个相关指引（按相关度排序）:"]
    for i, r in enumerate(results, 1):
        blocks.append(f"\n===== 指引 {i}：{r['title']}（code={r['code']}，相关度 {r['score']}）=====")
        blocks.append(format_appeal_text(r))
    blocks.append("\n提示：具体项目还须以招标文件载明的监督部门和当地公共资源交易平台要求为准。")
    return "\n".join(blocks), []


BID_AGENT_TOOLS.append(ConsultAppeal())
BID_AGENT_EXECUTORS["consult_appeal"] = _exec_consult_appeal


# ============ R16: 操作智能引导 ============

class GuideOperation(BaseTool):
    name: str = "guide_operation"
    description: str = (
        "识别用户在电子交易平台上的操作阶段，给出针对性分步指引。"
        "覆盖投标人（注册账号/实名认证/CA办理/下载标书/上传投标文件/开标解密/评标澄清）、"
        "招标人（项目登记/招标文件编制/公告发布/开评标组织/定标公示）、"
        "评标专家（抽取回避/签到/评审打分/签署报告）。"
        "当用户问\"怎么注册/CA怎么用/标书怎么上传/解密失败怎么办/专家怎么评标/"
        "公告怎么发布\"等操作类问题时调用，query 用用户问题原文。")
    parameters: dict = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "用户的操作问题原文，如\"投标文件上传失败怎么办\"、\"开标怎么在线解密\""},
        },
        "required": ["query"],
    }


def _exec_guide_operation(args, question):
    query = (args.get("query") or "").strip()
    if not query:
        return "请描述你正在进行的操作，例如\"投标文件怎么上传\"、\"CA 证书怎么办理\"", []
    rec = recognize_stage(query)
    if not rec:
        return ("暂未识别出对应的操作流程。支持的指引包括：账号注册与实名认证、"
                "CA 数字证书办理、投标文件制作与上传、开标解密、评标澄清（投标人）；"
                "项目登记与公告发布（招标人）；专家抽取、评审打分与签署报告（评标专家）。", [])
    return format_guide_text(rec), []


BID_AGENT_TOOLS.append(GuideOperation())
BID_AGENT_EXECUTORS["guide_operation"] = _exec_guide_operation
