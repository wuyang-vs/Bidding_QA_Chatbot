"""FastAPI 全部端点 + 限流中间件 + lifespan 初始化"""
import logging
import threading
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
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
    rag_pipeline.initialize()
    bidding_agent.initialize()
    neo4j_client.initialize()
    postgresql_client.initialize()
    web_search_client.initialize()
    exa_search_client.initialize()
    logger.info("API 服务启动完成")
    yield


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
