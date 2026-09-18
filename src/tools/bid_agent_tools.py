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
