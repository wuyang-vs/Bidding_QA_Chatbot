from __future__ import annotations
"""工具定义 + TOOL_EXECUTORS + _fmt_* 格式化 + 联网重排"""
import logging

from src.rag.pipeline import rag_pipeline
from src.database.neo4j_client import neo4j_client
from src.database.postgresql_client import postgresql_client
from src.web_search import web_search_client
from src.rag.embedder import reranker
from src.tools.base import BaseTool

logger = logging.getLogger(__name__)


class SearchBiddingKnowledge(BaseTool):
    name: str = "search_bidding_knowledge"
    description: str = ("检索招投标知识库（含已上传的招标文件原文、法规库、流程与概念），"
                        "适用于查询具体项目的投标截止时间、预算金额、资质要求、废标条款、"
                        "评分办法，以及法规、流程、概念类问题")
    parameters: dict = {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "检索问题"}},
        "required": ["query"],
    }


class SearchKnowledgeGraph(BaseTool):
    name: str = "search_knowledge_graph"
    description: str = "查询知识图谱，适用于标的物/采购人/供应商关系、采购频次统计"
    parameters: dict = {
        "type": "object",
        "properties": {
            "keyword": {"type": "string"},
            "query_type": {"type": "string", "enum": [
                "search_entity", "items_by_entity", "top_traded",
                "entity_detail", "list_entities", "graph_stats"]},
        },
        "required": ["query_type"],
    }


class SearchPostgreSQL(BaseTool):
    name: str = "search_postgresql"
    description: str = "查询结构化采购数据库，适用于金额统计、时间范围、排名"
    parameters: dict = {
        "type": "object",
        "properties": {
            "query_type": {"type": "string", "enum": [
                "search_by_keyword", "filter_by_field", "aggregate_stats",
                "top_by_amount", "group_by_field", "time_range"]},
            "keyword": {"type": "string"},
            "field": {"type": "string"},
            "value": {"type": "string"},
        },
        "required": ["query_type"],
    }


class SearchWeb(BaseTool):
    name: str = "search_web"
    description: str = "联网搜索最新招投标公告与法规更新"
    parameters: dict = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }


class SearchExa(BaseTool):
    name: str = "search_exa"
    description: str = "Exa 语义搜索，适合深度内容"
    parameters: dict = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }


ALL_TOOLS = [SearchBiddingKnowledge(), SearchKnowledgeGraph(),
             SearchPostgreSQL(), SearchWeb(), SearchExa()]


def _fmt_rag(docs: list[dict]) -> str:
    if not docs:
        return "未检索到相关文档"
    lines = []
    for i, d in enumerate(docs, 1):
        src = d.get("source_file") or "知识库"
        tag = "招标文件" if d.get("doc_type") == "tender_document" else "知识库"
        lines.append(f"【资料{i}】(来源:{tag} {src})\n问: {d['question']}\n答: {d['answer']}\n相关度: {d.get('score', 0):.3f}")
    return "\n\n".join(lines)


def _fmt_graph(rows: list[dict]) -> str:
    if not rows:
        return "未找到相关图谱数据"
    return "\n".join(str(r) for r in rows[:20])


def _fmt_pg(rows: list[dict]) -> str:
    if not rows:
        return "未查询到数据"
    lines = []
    for r in rows[:20]:
        lines.append(" | ".join(f"{k}: {str(v)[:50]}" for k, v in r.items()))
    return "\n".join(lines)


def _fmt_web(items: list[dict]) -> str:
    if not items:
        return "未找到联网结果"
    lines = []
    for i, it in enumerate(items[:5], 1):
        lines.append(f"[{i}] {it.get('question', '')}\n{str(it.get('answer', ''))[:300]}\n来源: {it.get('url', '')}")
    return "\n\n".join(lines)


def _rerank_web_results(question: str, items: list[dict]) -> list[dict]:
    if len(items) < 2:
        return items
    try:
        docs = [{"answer": f"{it.get('question','')}\n{it.get('answer','')}", "_i": i}
                for i, it in enumerate(items)]
        reranked = reranker.rerank(question, docs, top_k=len(docs))
        ordered = [items[d["_i"]] for d in reranked]
        scores = [d["score"] for d in reranked]
        mn, mx = min(scores), max(scores)
        for it, s in zip(ordered, scores):
            if mx > mn:
                it["score"] = (s - mn) / (mx - mn)
            elif mx > 0:
                it["score"] = 1.0
            else:
                it["score"] = 0.0
        return ordered
    except Exception as e:
        logger.warning("联网重排失败: %s", e)
        return items


def _exec_rag(args, question):
    docs = rag_pipeline.search(args.get("query", question), top_k=5)
    return _fmt_rag(docs), docs


def _exec_graph(args, question):
    if not neo4j_client.ready:
        return "知识图谱未连接", []
    rows = neo4j_client.query(args.get("query_type", "graph_stats"),
                              keyword=args.get("keyword", ""))
    return _fmt_graph(rows), []


def _exec_pg(args, question):
    if not postgresql_client.ready:
        return "PostgreSQL 未连接", []
    rows = postgresql_client.query(args.get("query_type", "search_by_keyword"),
                                   keyword=args.get("keyword", ""),
                                   field=args.get("field", ""),
                                   value=args.get("value", ""))
    if isinstance(rows, dict) and not rows.get("success", True):
        return f"查询失败: {rows.get('error', '')}", []
    return _fmt_pg(rows if isinstance(rows, list) else []), []


def _exec_web(args, question):
    items = web_search_client.search(args.get("query", question))
    items = _rerank_web_results(question, items)
    return _fmt_web(items), items


def _exec_exa(args, question):
    from src.mcp.web_search_exa import exa_search_client
    items = exa_search_client.search(args.get("query", question))
    items = _rerank_web_results(question, items)
    return _fmt_web(items), items


TOOL_EXECUTORS = {
    "search_bidding_knowledge": _exec_rag,
    "search_knowledge_graph": _exec_graph,
    "search_postgresql": _exec_pg,
    "search_web": _exec_web,
    "search_exa": _exec_exa,
}

# 标书生成 Agent 工具 (对话内"帮我写标书"闭环); 延迟导入避免循环依赖
from src.tools.bid_agent_tools import BID_AGENT_TOOLS, BID_AGENT_EXECUTORS  # noqa: E402

ALL_TOOLS.extend(BID_AGENT_TOOLS)
TOOL_EXECUTORS.update(BID_AGENT_EXECUTORS)
