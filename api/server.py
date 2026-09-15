"""FastAPI 全部端点 + 限流中间件 + lifespan 初始化"""
import logging
import threading
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from src.config import settings
from src.logging_config import setup_logging
from src.rate_limiter import rate_limiter

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from src.rag.pipeline import rag_pipeline
    from src.agent.core import bidding_agent
    from src.database.neo4j_client import neo4j_client
    from src.database.postgresql_client import postgresql_client
    from src.web_search import web_search_client
    from src.mcp.web_search_exa import exa_search_client
    from src.rag.scheduler import start_auto_ingest, stop_auto_ingest
    from src.tools.system_monitor import system_monitor
    rag_pipeline.initialize()
    bidding_agent.initialize()
    neo4j_client.initialize()
    postgresql_client.initialize()
    web_search_client.initialize()
    exa_search_client.initialize()
    start_auto_ingest()
    system_monitor.start()
    logger.info("API 服务启动完成")
    yield
    system_monitor.stop()
    stop_auto_ingest()
    logger.info("API 服务已关闭")


app = FastAPI(title="Bidding QA Chatbot", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)


@app.middleware("http")
def rate_limit_middleware(request: Request, call_next):
    if request.url.path.startswith("/api/chat"):
        ip = request.client.host if request.client else "unknown"
        if not rate_limiter.is_allowed(ip):
            return JSONResponse({"detail": "请求过于频繁"}, status_code=429)
    return call_next(request)


class ChatRequest(BaseModel):
    question: str
    history: list[dict] | None = None
    web_search_enabled: bool = False
    provider: str = ""
    deep_thinking_enabled: bool = False


class AskRequest(BaseModel):
    question: str
    top_k: int = 5


class VisionRequest(BaseModel):
    image_base64: str
    prompt: str = "请详细描述这张图片的内容"


class SaveConvRequest(BaseModel):
    session_id: str
    title: str = ""
    messages: list = Field(default_factory=list)


class FeedbackRequest(BaseModel):
    session_id: str
    question: str
    answer: str
    rating: Literal["up", "down"]


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest):
    if not req.question.strip():
        raise HTTPException(400, "问题不能为空")
    from src.agent.core import bidding_agent
    if not bidding_agent.ready:
        raise HTTPException(503, "知识库未就绪")

    def _gen():
        yield from bidding_agent.chat_stream(
            req.question, req.history, req.web_search_enabled,
            req.provider, req.deep_thinking_enabled)

    return StreamingResponse(_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.post("/api/chat")
def chat(req: ChatRequest):
    from src.agent.core import bidding_agent
    if not bidding_agent.ready:
        raise HTTPException(503, "知识库未就绪")
    return bidding_agent.chat(req.question, req.history,
                              req.web_search_enabled, req.provider,
                              req.deep_thinking_enabled)


@app.post("/api/ask")
def ask(req: AskRequest):
    from src.rag.pipeline import rag_pipeline
    if not rag_pipeline.ready:
        raise HTTPException(503, "知识库未就绪")
    return rag_pipeline.ask(req.question, req.top_k)


MAX_IMAGE_BASE64_CHARS = 4_000_000


@app.post("/api/vision")
def vision(req: VisionRequest):
    if len(req.image_base64) > MAX_IMAGE_BASE64_CHARS:
        raise HTTPException(413, "图片过大")
    from src.clients.vision_client import vision_client
    if not vision_client.ready:
        raise HTTPException(503, "视觉服务未就绪")
    return vision_client.analyze(req.image_base64, req.prompt)


@app.post("/api/conversations")
def save_conversation(req: SaveConvRequest):
    from src.database.postgresql_client import postgresql_client, PostgreSQLQueryError
    try:
        postgresql_client.save_conversation(req.session_id, req.title, req.messages)
        return {"status": "ok"}
    except PostgreSQLQueryError:
        raise HTTPException(503, "会话保存失败，请检查数据库连接")


@app.get("/api/conversations")
def list_conversations(q: str = ""):
    from src.database.postgresql_client import postgresql_client, PostgreSQLQueryError
    try:
        return postgresql_client.list_conversations(q)
    except PostgreSQLQueryError:
        raise HTTPException(503, "会话列表读取失败")


@app.get("/api/conversations/{session_id}")
def load_conversation(session_id: str):
    from src.database.postgresql_client import postgresql_client, PostgreSQLQueryError
    try:
        return {"session_id": session_id,
                "messages": postgresql_client.load_conversation(session_id)}
    except PostgreSQLQueryError:
        raise HTTPException(503, "会话加载失败")


@app.delete("/api/conversations")
def delete_all():
    from src.database.postgresql_client import postgresql_client, PostgreSQLQueryError
    try:
        postgresql_client.delete_all_conversations()
        return {"status": "ok"}
    except PostgreSQLQueryError:
        raise HTTPException(503, "删除失败")


@app.delete("/api/conversations/{session_id}")
def delete_conversation(session_id: str):
    from src.database.postgresql_client import postgresql_client, PostgreSQLQueryError
    try:
        postgresql_client.delete_conversation(session_id)
        return {"status": "ok"}
    except PostgreSQLQueryError:
        raise HTTPException(503, "删除失败")


@app.post("/api/feedback")
def feedback(req: FeedbackRequest):
    from src.database.postgresql_client import postgresql_client, PostgreSQLQueryError
    try:
        postgresql_client.save_feedback(req.session_id, req.question, req.answer, req.rating)
        return {"status": "ok"}
    except PostgreSQLQueryError:
        raise HTTPException(503, "反馈保存失败")


_health_cache = {"time": 0.0, "data": None}
_health_lock = threading.Lock()


@app.get("/api/health")
def health():
    with _health_lock:
        if time.time() - _health_cache["time"] < 30 and _health_cache["data"]:
            return _health_cache["data"]
    from src.rag.pipeline import rag_pipeline
    from src.agent.core import bidding_agent
    from src.rag.vector_store import vector_store
    from src.database.neo4j_client import neo4j_client
    from src.database.postgresql_client import postgresql_client

    data = {
        "ready": rag_pipeline.ready,
        "agent_ready": bidding_agent.ready,
        "graph_ready": neo4j_client.ready,
        "pg_ready": postgresql_client.ready,
        "points_count": vector_store.count(),
        "latencies": {},
    }
    with _health_lock:
        _health_cache["time"] = time.time()
        _health_cache["data"] = data
    return data


@app.get("/api/system/metrics")
def system_metrics():
    """系统监控快照: CPU / 内存 / 磁盘 / GPU (可选) + 60s 趋势."""
    from src.tools.system_monitor import system_monitor
    return system_monitor.snapshot()


@app.get("/api/agent/executions")
def agent_executions(limit: int = 20, status: str = "", trace_id: str = ""):
    """查询 Agent 执行记录 (结构化日志)."""
    from src.agent.execution_log import query_executions
    return {"executions": query_executions(limit=limit, status=status, trace_id=trace_id)}


@app.get("/api/agent/executions/stats")
def agent_execution_stats():
    """Agent 执行统计: 总数/状态分布/平均耗时/工具调用 TOP."""
    from src.agent.execution_log import get_stats
    return get_stats()


@app.post("/api/knowledge/reload")
def knowledge_reload():
    """手动触发知识库自动扫描 + 增量导入."""
    from src.rag.scheduler import get_scheduler
    s = get_scheduler()
    if s is None:
        return {"status": "disabled", "message": "自动更新未启用 (AUTO_INGEST_ENABLED=false)"}
    if s.is_importing:
        return {"status": "busy", "message": "正在导入中, 请稍后再试"}
    result = s.trigger_now()
    return {"status": "ok", **result}


@app.get("/api/knowledge/status")
def knowledge_status():
    """知识库自动更新状态."""
    from src.rag.scheduler import get_scheduler
    from src.config import settings
    s = get_scheduler()
    return {
        "enabled": settings.auto_ingest_enabled,
        "running": s.is_running if s else False,
        "importing": s.is_importing if s else False,
        "interval_min": settings.auto_ingest_interval_min,
        "data_dir": settings.auto_ingest_data_dir,
        "tracked_files": len(s._state) if s else 0,
    }


@app.post("/api/document/upload")
def document_upload(file: UploadFile, save_to_db: bool = True):
    """上传招标文件 → 自动解析 → 返回结构化字段.

    支持: .pdf, .docx, .txt, .md
    save_to_db=false 时只解析不入库 (调试用).
    """
    import tempfile, os
    from src.tools.document_parser import parse_file
    from src.database.postgresql_client import postgresql_client  # noqa: F401

    allowed = {".pdf", ".docx", ".txt", ".md"}
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in allowed:
        raise HTTPException(400, f"不支持的格式 {ext}, 允许: {sorted(allowed)}")

    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(file.file.read())
            tmp_path = tmp.name
        parsed = parse_file(tmp_path)
        os.unlink(tmp_path)

        db_id = None
        if save_to_db and postgresql_client.ready:
            db_id = postgresql_client.save_document(parsed)
            parsed["db_id"] = db_id

        # 脱敏: 原始文本前 2000 字已在 raw_text_preview, 不返回更多
        parsed.pop("raw_text", None)
        return parsed
    except Exception as e:
        logger.exception("文档解析失败")
        raise HTTPException(500, f"解析失败: {e}")


@app.get("/api/documents")
def list_documents(q: str = ""):
    """已解析文档列表 (支持关键词搜索)."""
    from src.database.postgresql_client import postgresql_client
    if not postgresql_client.ready:
        return {"items": [], "warning": "PostgreSQL 未连接"}
    return {"items": postgresql_client.list_documents(q)}


class BidGenerateRequest(BaseModel):
    project_name: str = ""
    purchaser: str = ""
    subject_matter: str = ""
    budget: str = ""
    qualification_requirements: list[str] = Field(default_factory=list)
    db_id: int | None = None        # 已解析文档的 id (优先)
    sections: list[str] | None = None  # 指定章节, 空=自动推荐
    include_similar_cases: bool = True


@app.post("/api/bid/generate")
def bid_generate(req: BidGenerateRequest):
    """根据招标要求生成投标书草稿."""
    from src.tools.bid_generator import (
        generate_full_bid, suggest_sections, SECTIONS, _summarize_tender_info,
    )
    from src.clients.llm_factory import get_llm_client
    from src.rag.pipeline import rag_pipeline

    # 1. 组装招标信息 (优先从 DB 取, 否则用请求体)
    tender = {}
    if req.db_id is not None:
        from src.database.postgresql_client import postgresql_client
        if postgresql_client.ready:
            rows = postgresql_client._run(
                "SELECT * FROM bidding_documents WHERE id = :id", {"id": req.db_id})
            if rows:
                row = rows[0]
                tender = {
                    "project_name": row.get("project_name") or "",
                    "project_code": row.get("project_code") or "",
                    "purchaser": row.get("purchaser") or "",
                    "subject_matter": row.get("subject_matter") or "",
                    "budget": row.get("budget") or "",
                    "qualification_requirements": row.get("qualification_requirements") or [],
                    "scoring_criteria": row.get("scoring_criteria") or "",
                    "deadline": row.get("deadline") or "",
                }
    if not tender:
        tender = {
            "project_name": req.project_name,
            "purchaser": req.purchaser,
            "subject_matter": req.subject_matter,
            "budget": req.budget,
            "qualification_requirements": req.qualification_requirements,
        }

    # 2. RAG 检索相似案例
    cases = []
    if req.include_similar_cases and rag_pipeline.ready and tender.get("subject_matter"):
        try:
            results = rag_pipeline.search(
                f"{tender.get('subject_matter', '')} 采购 投标 技术方案", top_k=3)
            cases = results[:3]
        except Exception as e:
            logger.warning("相似案例检索失败: %s", e)

    # 3. 确定章节
    section_keys = req.sections or suggest_sections(tender)
    # 校验
    section_keys = [k for k in section_keys if k in SECTIONS]
    if not section_keys:
        section_keys = list(SECTIONS.keys())

    # 4. 生成
    llm = get_llm_client()
    md = generate_full_bid(tender, cases, llm_client=llm, sections=section_keys)

    return {
        "project_name": tender.get("project_name", ""),
        "sections_generated": [SECTIONS[k]["title"] for k in section_keys],
        "similar_cases_found": len(cases),
        "markdown": md,
    }


class ComplianceCheckRequest(BaseModel):
    text: str = ""
    db_id: int | None = None  # 已解析文档


@app.post("/api/compliance/check")
def compliance_check(req: ComplianceCheckRequest):
    """合规性检查 — 扫描招标文件是否存在排他性/不合理条款."""
    from src.tools.compliance_checker import check_compliance
    from src.clients.llm_factory import get_llm_client

    content = req.text
    if req.db_id is not None:
        from src.database.postgresql_client import postgresql_client
        if postgresql_client.ready:
            rows = postgresql_client._run(
                "SELECT * FROM bidding_documents WHERE id = :id", {"id": req.db_id})
            if rows:
                content = rows[0]

    if not content:
        raise HTTPException(400, "请提供 text 或 db_id")

    llm = get_llm_client()
    result = check_compliance(content, llm_client=llm)
    return result


class QualificationCheckRequest(BaseModel):
    tender_requirements: list[str] = Field(default_factory=list)
    company_qualifications: list[str] = Field(default_factory=list)
    db_id: int | None = None  # 优先从已解析文档取资质要求


@app.post("/api/qualification/check")
def qualification_check(req: QualificationCheckRequest):
    """资格审查 — 招标文件资质要求 vs 企业资质清单.

    三种模式:
      1. db_id 提供 → 自动从 bidding_documents 取 qualification_requirements
      2. tender_requirements 直接传 → 使用传入的列表
      3. 两者都有 → db_id 优先
    company_qualifications 必须由用户提供.
    """
    from src.tools.qualification_checker import check_qualification
    from src.clients.llm_factory import get_llm_client

    tender_reqs = list(req.tender_requirements)
    if req.db_id is not None:
        from src.database.postgresql_client import postgresql_client
        if postgresql_client.ready:
            rows = postgresql_client._run(
                "SELECT qualification_requirements FROM bidding_documents WHERE id = :id",
                {"id": req.db_id})
            if rows and rows[0].get("qualification_requirements"):
                tender_reqs = rows[0]["qualification_requirements"] or tender_reqs

    llm = get_llm_client()
    result = check_qualification(
        tender_requirements=tender_reqs,
        company_qualifications=req.company_qualifications,
        llm_client=llm,
    )
    return result


class PriceAnalyzeRequest(BaseModel):
    subject_matter: str
    granularity: str = "month"  # month / year


@app.post("/api/price/analyze")
def price_analyze(req: PriceAnalyzeRequest):
    """价格对标分析 — 历史中标价格分布 + 趋势 + LLM 解读."""
    from src.tools.price_analyzer import analyze_price
    from src.clients.llm_factory import get_llm_client
    llm = get_llm_client()
    return analyze_price(req.subject_matter, llm_client=llm)


class CompetitorAnalyzeRequest(BaseModel):
    subject_matter: str
    top_n: int = 10


@app.post("/api/competitors/analyze")
def competitor_analyze(req: CompetitorAnalyzeRequest):
    """竞争对手分析 — 中标供应商 TOP N + 图谱竞品覆盖 + 市场集中度."""
    from src.tools.competitor_analyzer import analyze_competitors
    from src.clients.llm_factory import get_llm_client
    llm = get_llm_client()
    return analyze_competitors(req.subject_matter, top_n=req.top_n, llm_client=llm)


@app.get("/api/deadlines")
def deadlines(within_days: int = 7, include_expired: bool = True):
    """截止日期监控 — 临近截止的投标项目预警."""
    from src.tools.deadline_monitor import monitor
    return {"alerts": monitor.check(within_days=within_days, include_expired=include_expired)}


@app.get("/api/deadlines/summary")
def deadlines_summary():
    """截止日期汇总统计."""
    from src.tools.deadline_monitor import monitor
    return monitor.summary()


@app.post("/api/export/docx")
def export_docx(req: BidGenerateRequest):
    """导出投标书为 Word 文件.

    如果请求体里没有 markdown, 则先调用 bid_generate 生成再导出.
    也可以在 BidGenerateRequest 里加 markdown 字段直接导出.
    """
    from src.tools.bid_generator import generate_full_bid, suggest_sections, SECTIONS
    from src.tools.report_export import markdown_to_docx
    from src.clients.llm_factory import get_llm_client
    from src.rag.pipeline import rag_pipeline
    from fastapi.responses import Response

    # 组装 tender 信息 (复用 bid_generate 逻辑)
    tender = {}
    if req.db_id is not None:
        from src.database.postgresql_client import postgresql_client
        if postgresql_client.ready:
            rows = postgresql_client._run(
                "SELECT * FROM bidding_documents WHERE id = :id", {"id": req.db_id})
            if rows:
                row = rows[0]
                tender = {
                    "project_name": row.get("project_name") or "",
                    "project_code": row.get("project_code") or "",
                    "purchaser": row.get("purchaser") or "",
                    "subject_matter": row.get("subject_matter") or "",
                    "budget": row.get("budget") or "",
                    "qualification_requirements": row.get("qualification_requirements") or [],
                    "deadline": row.get("deadline") or "",
                }
    if not tender:
        tender = {
            "project_name": req.project_name,
            "purchaser": req.purchaser,
            "subject_matter": req.subject_matter,
            "budget": req.budget,
            "qualification_requirements": req.qualification_requirements,
        }

    # RAG 案例
    cases = []
    if req.include_similar_cases and rag_pipeline.ready and tender.get("subject_matter"):
        try:
            results = rag_pipeline.search(
                f"{tender.get('subject_matter', '')} 采购 投标 技术方案", top_k=3)
            cases = results[:3]
        except Exception:
            pass

    section_keys = req.sections or suggest_sections(tender)
    section_keys = [k for k in section_keys if k in SECTIONS] or list(SECTIONS.keys())

    llm = get_llm_client()
    md = generate_full_bid(tender, cases, llm_client=llm, sections=section_keys)

    data = markdown_to_docx(md, title=tender.get("project_name") or "投标书草稿")
    filename = f"投标书_{tender.get('project_name', '草稿')}.docx".replace("/", "_")

    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
