"""FastAPI 全部端点 + 限流中间件 + lifespan 初始化"""
import logging
import threading
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from src.config import settings
from src.logging_config import setup_logging
from src.rate_limiter import rate_limiter
from src.auth import get_current_user_required, get_current_user_optional

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
    # 初始化默认 admin 密码 (仅首次)
    try:
        from src.auth import hash_password
        rows = postgresql_client._run(
            "SELECT id, password_hash FROM users WHERE username='admin'")
        if rows and rows[0]["password_hash"].startswith("$2b$12$placeholder"):
            postgresql_client._run(
                "UPDATE users SET password_hash=:h WHERE id=:id",
                {"h": hash_password("admin123"), "id": rows[0]["id"]})
            logger.info("默认 admin 密码已初始化 (admin / admin123)")
    except Exception as e:
        logger.warning("默认 admin 初始化失败: %s", e)
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


# ==================== 鉴权端点 ====================

class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/auth/register")
def register(req: RegisterRequest):
    from src.auth import hash_password
    from src.database.postgresql_client import postgresql_client
    if len(req.username) < 3 or len(req.password) < 6:
        raise HTTPException(400, "用户名至少3位, 密码至少6位")
    if not postgresql_client.ready:
        raise HTTPException(503, "PostgreSQL 未连接")
    existing = postgresql_client._run(
        "SELECT id FROM users WHERE username=:u", {"u": req.username})
    if existing:
        raise HTTPException(409, "用户名已存在")
    postgresql_client._run(
        "INSERT INTO users (username, password_hash, role, display_name) VALUES (:u,:h,'auditor',:d)",
        {"u": req.username, "h": hash_password(req.password), "d": req.display_name or req.username})
    return {"status": "ok", "username": req.username}


@app.post("/auth/login")
def login(req: LoginRequest):
    from src.auth import verify_password, create_access_token
    from src.database.postgresql_client import postgresql_client
    if not postgresql_client.ready:
        raise HTTPException(503, "PostgreSQL 未连接")
    rows = postgresql_client._run(
        "SELECT id, username, password_hash, role, display_name FROM users WHERE username=:u",
        {"u": req.username})
    if not rows or not verify_password(req.password, rows[0]["password_hash"]):
        raise HTTPException(401, "用户名或密码错误")
    user = rows[0]
    token = create_access_token(user["id"], {
        "uid": user["id"],
        "username": user["username"],
        "role": user["role"],
        "display_name": user["display_name"],
    })
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user["id"],
            "username": user["username"],
            "role": user["role"],
            "display_name": user["display_name"],
        },
    }


@app.get("/auth/me")
def auth_me(user: dict = Depends(get_current_user_required)):
    return {"user": user}


# ==================== 业务端点 ====================

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


# ===================== Dashboard / Graph =====================

@app.get("/api/dashboard")
def dashboard():
    """数据看板聚合: 系统健康 + Agent 统计 + 知识库 + 图谱 + 数据库."""
    from src.agent.execution_log import get_stats as exec_stats
    from src.rag.pipeline import rag_pipeline

    # Agent 执行统计
    agent_stats = exec_stats()

    # 知识库
    kb_count = 0
    if rag_pipeline.ready:
        try:
            kb_count = rag_pipeline.vector_store.count()
        except Exception:
            pass

    # 图谱统计
    graph_stats = []
    from src.database.neo4j_client import neo4j_client
    if neo4j_client.ready:
        graph_stats = neo4j_client.query("graph_stats")

    # 数据库统计
    db_count = 0
    try:
        from src.database.postgresql_client import postgresql_client
        if postgresql_client.ready:
            rows = postgresql_client.query("SELECT COUNT(*) AS cnt FROM bidding_procurement")
            db_count = rows[0]["cnt"] if rows else 0
    except Exception:
        pass

    # 系统监控
    sys_metrics = {}
    try:
        from src.tools.system_monitor import system_monitor
        sys_metrics = system_monitor.snapshot()
    except Exception:
        pass

    return {
        "agent": agent_stats,
        "knowledge_base": {"points": kb_count, "ready": rag_pipeline.ready},
        "graph": {"stats": graph_stats, "ready": neo4j_client.ready},
        "database": {"rows": db_count, "ready": postgresql_client.ready if postgresql_client else False},
        "system": {
            "cpu": sys_metrics.get("current", {}).get("cpu_percent", 0),
            "memory": sys_metrics.get("current", {}).get("memory_percent", 0),
            "disk": sys_metrics.get("current", {}).get("disk_percent", 0),
        },
    }


@app.get("/api/graph/subgraph")
def graph_subgraph(keyword: str = "", limit: int = 30):
    """知识图谱子图: 返回 nodes + edges (d3.js force-directed 用).

    查询逻辑:
    1. keyword 为空 → 返回 TOP 标的物 + 关联采购人/供应商
    2. keyword 不为空 → 以 keyword 为中心, 返回 1 跳邻居
    """
    from src.database.neo4j_client import neo4j_client
    if not neo4j_client.ready:
        return {"nodes": [], "edges": [], "ready": False}

    nodes_set = {}  # name → {id, name, type}
    edges = []

    if not keyword:
        # 全量: TOP 标的物 + 关联实体
        rows = neo4j_client.query("top_traded")
        for r in rows:
            name = r.get("name", "")
            freq = r.get("freq", 0)
            if name and name not in nodes_set:
                nodes_set[name] = {"id": name, "name": name, "type": "SubjectMatter", "freq": freq}
            # 查该标的物的关联
            detail = neo4j_client.query("entity_detail", keyword=name)
            for d in detail:
                subject = d.get("subject", name)
                for p in d.get("purchasers", []):
                    if p not in nodes_set:
                        nodes_set[p] = {"id": p, "name": p, "type": "Purchaser"}
                    edges.append({"source": subject, "target": p, "relation": "PURCHASED_BY"})
                for s in d.get("suppliers", []):
                    if s not in nodes_set:
                        nodes_set[s] = {"id": s, "name": s, "type": "Supplier"}
                    edges.append({"source": subject, "target": s, "relation": "SUPPLIED_BY"})
            if len(nodes_set) >= limit:
                break
    else:
        # 以 keyword 为中心
        detail = neo4j_client.query("entity_detail", keyword=keyword)
        if detail:
            d = detail[0]
            subject = d.get("subject", keyword)
            nodes_set[subject] = {"id": subject, "name": subject, "type": "SubjectMatter"}
            for p in d.get("purchasers", []):
                if p not in nodes_set:
                    nodes_set[p] = {"id": p, "name": p, "type": "Purchaser"}
                edges.append({"source": subject, "target": p, "relation": "PURCHASED_BY"})
            for s in d.get("suppliers", []):
                if s not in nodes_set:
                    nodes_set[s] = {"id": s, "name": s, "type": "Supplier"}
                edges.append({"source": subject, "target": s, "relation": "SUPPLIED_BY"})

    return {
        "nodes": list(nodes_set.values())[:limit],
        "edges": edges,
        "ready": True,
    }


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
        # 保留用户原始文件名 (parse_file 默认填的是临时文件名)
        parsed["source_file"] = file.filename or parsed.get("source_file", "")
        parsed["source_path"] = ""

        db_id = None
        raw_text = parsed.get("raw_text") or ""
        if save_to_db and postgresql_client.ready:
            db_id = postgresql_client.save_document(parsed)
            parsed["db_id"] = db_id

        # 招标文件全文分片向量化 → Qdrant, 供混合检索问答引用
        indexed_chunks = 0
        if db_id and raw_text:
            try:
                from src.rag.ingest import ingest_tender_document
                indexed_chunks = ingest_tender_document(
                    db_id, raw_text,
                    source_file=parsed.get("source_file", ""),
                    project_name=parsed.get("project_name", ""))
            except Exception as ie:
                logger.warning("招标文件向量化失败 (不影响解析入库): %s", ie)
        parsed["vector_indexed_chunks"] = indexed_chunks

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


class RejectionCheckRequest(BaseModel):
    text: str = ""
    db_id: int | None = None
    bidder_status: str = ""  # 可选: 投标人自述情况, 提供时做废标风险自查


@app.post("/api/rejection/check")
def rejection_check(req: RejectionCheckRequest):
    """废标(否决投标)条款检查 — 提取废标条款清单, 可选结合投标人情况自查."""
    from src.tools.bid_rejection_checker import check_bid_rejection
    from src.clients.llm_factory import get_llm_client

    content: str | dict = req.text
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
    return check_bid_rejection(
        content,
        bidder_status=req.bidder_status or None,
        llm_client=llm,
    )


# ---------- 人工复核 (审计留痕) ----------

class ResponseCheckRequest(BaseModel):
    tender_text: str = ""
    tender_db_id: int | None = None
    bid_text: str = ""
    bid_db_id: int | None = None
    clause: str = ""  # 可选, 指定条款号如 "3.2"


@app.post("/api/scoring/table")
def scoring_table(req: dict):
    """评分辅助表 — 根据招标文件评分办法生成结构化打分表模板.

    Body: {"db_id": int}  取该招标文件的 scoring_criteria
    """
    from src.tools.scoring_table import generate_scoring_table
    from src.clients.llm_factory import get_llm_client
    from src.database.postgresql_client import postgresql_client

    db_id = req.get("db_id")
    scoring_text = req.get("scoring_text", "")
    if db_id is not None and postgresql_client.ready:
        rows = postgresql_client._run(
            "SELECT scoring_criteria FROM bidding_documents WHERE id = :id", {"id": db_id})
        if rows:
            scoring_text = rows[0].get("scoring_criteria") or scoring_text

    if not scoring_text:
        raise HTTPException(400, "未找到评分办法, 请提供 scoring_text 或确保文档含评分办法章节")

    llm = get_llm_client()
    return generate_scoring_table(scoring_text, llm_client=llm)


@app.post("/api/response/check")
def response_check(req: ResponseCheckRequest):
    """投标响应性检查 — 对照招标实质性条款, 判定投标逐条响应情况."""
    from src.tools.response_checker import check_response
    from src.clients.llm_factory import get_llm_client
    from src.database.postgresql_client import postgresql_client

    tender: str | dict = req.tender_text
    if req.tender_db_id is not None and postgresql_client.ready:
        rows = postgresql_client._run(
            "SELECT * FROM bidding_documents WHERE id = :id", {"id": req.tender_db_id})
        if rows:
            tender = rows[0]

    bid: str | dict = req.bid_text
    if req.bid_db_id is not None and postgresql_client.ready:
        rows = postgresql_client._run(
            "SELECT * FROM bidding_documents WHERE id = :id", {"id": req.bid_db_id})
        if rows:
            bid = rows[0]

    if not tender:
        raise HTTPException(400, "请提供 tender_text 或 tender_db_id")
    if not bid:
        raise HTTPException(400, "请提供 bid_text 或 bid_db_id")

    llm = get_llm_client()
    return check_response(
        tender, bid,
        clause=req.clause or None,
        llm_client=llm,
    )


class ReviewSubmitRequest(BaseModel):
    document_id: int
    review_type: str  # compliance | qualification | rejection | response
    verdict: str      # approved | rejected
    comment: str = ""
    reviewer: str = ""
    result_snapshot: dict | None = None


class BidCompareRequest(BaseModel):
    bids: list[dict]  # [{"bidder_name": str, "text": str}, ...]


@app.post("/api/bids/compare")
def bids_compare(req: BidCompareRequest):
    """多家投标对比 — 抽取多份投标关键字段并并排展示."""
    from src.tools.bid_comparator import compare_bids
    from src.clients.llm_factory import get_llm_client

    if not req.bids:
        raise HTTPException(400, "请提供至少一份投标文件")
    llm = get_llm_client()
    return compare_bids(req.bids, llm_client=llm)


@app.get("/api/workflow/presets")
def workflow_presets():
    from src.workflow.engine import list_presets
    return {"presets": list_presets()}


class WorkflowRunRequest(BaseModel):
    config: str | dict  # 预置 id 或完整配置 dict
    ctx: dict = {}


@app.post("/api/workflow/run")
def workflow_run(req: WorkflowRunRequest):
    """执行一个工作流 (预置 id 或完整 JSON 配置).

    body:
      config: "compliance_review" 或 {... 完整配置 ...}
      ctx: {db_id, bid_text, clause, qualification_text, ...}
    """
    from src.workflow.engine import run_workflow, PRESETS
    from src.database.postgresql_client import postgresql_client

    config = req.config
    # 自动从 db_id 补上下文
    ctx = dict(req.ctx)
    if ctx.get("db_id") and postgresql_client.ready:
        rows = postgresql_client._run(
            "SELECT scoring_criteria, qualification_requirements FROM bidding_documents WHERE id=:id",
            {"id": ctx["db_id"]})
        if rows:
            doc = rows[0]
            if doc.get("scoring_criteria") and not ctx.get("scoring_criteria"):
                ctx["scoring_criteria"] = doc["scoring_criteria"]
            if isinstance(doc.get("qualification_requirements"), list):
                ctx["qualification_requirements"] = "\n".join(doc["qualification_requirements"])
            elif doc.get("qualification_requirements"):
                ctx["qualification_requirements"] = str(doc["qualification_requirements"])

    return run_workflow(config, ctx=ctx, parallel=True)


@app.post("/api/reviews")
def submit_review(
    req: ReviewSubmitRequest,
    user: dict | None = Depends(get_current_user_optional),
):
    """提交人工复核结论 (确认通过/驳回 + 备注), 留痕入库."""
    from src.database.postgresql_client import postgresql_client

    if not postgresql_client.ready:
        raise HTTPException(503, "PostgreSQL 未连接, 无法保存复核记录")
    if req.review_type not in ("compliance", "qualification", "rejection", "response", "scoring"):
        raise HTTPException(400, f"非法 review_type: {req.review_type}")
    if req.verdict not in ("approved", "rejected"):
        raise HTTPException(400, f"非法 verdict: {req.verdict}")

    review_id = postgresql_client.save_review(
        document_id=req.document_id,
        review_type=req.review_type,
        verdict=req.verdict,
        comment=req.comment,
        reviewer=req.reviewer or (user["display_name"] if user else ""),
        result_snapshot=req.result_snapshot,
        user_id=user["id"] if user else None,
    )
    logger.info("人工复核已记录 doc=%s type=%s verdict=%s reviewer=%s id=%s",
                req.document_id, req.review_type, req.verdict, req.reviewer, review_id)
    return {"id": review_id, "status": "saved"}


@app.get("/api/reviews")
def list_reviews(document_id: int | None = None, review_type: str | None = None):
    """查询人工复核历史 (可按文档/类型过滤)."""
    from src.database.postgresql_client import postgresql_client
    if not postgresql_client.ready:
        return {"items": [], "warning": "PostgreSQL 未连接"}
    return {"items": postgresql_client.list_reviews(document_id, review_type)}


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


# ─── 多 Agent 协作 ────────────────────────────────────────────────

class MultiAgentRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000,
                          description="用户问题")
    provider: str = Field(default="", description="LLM provider, 留空用默认")
    deep_thinking: bool = Field(default=False, description="是否使用深度思考模型")


@app.post("/api/multi-agent/run")
def multi_agent_run(req: MultiAgentRequest):
    """多 Agent 协作: 主管调度法规/案例/价格专家, 写作专家综合."""
    from src.agent.multi_agent import run_multi_agent_workflow
    import threading

    # 限频
    client_ip = getattr(req, "_client_ip", "unknown")
    ok, info = rate_limiter.acquire(client_ip, limit=10, window=60)
    if not ok:
        raise HTTPException(status_code=429, detail=f"限流: {info}")

    result = run_multi_agent_workflow(
        question=req.question,
        provider=req.provider,
        deep_thinking=req.deep_thinking,
    )
    return result
