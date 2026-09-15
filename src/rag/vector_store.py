"""Qdrant Named Vectors 混合检索 + RRF + 问题分类 + 元数据透传"""
import logging
import time

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, SparseVectorParams, PointStruct,
    Prefetch, RrfQuery, Rrf,
)
from qdrant_client.http.exceptions import ResponseHandlingException

from src.config import settings

logger = logging.getLogger(__name__)

_KEYWORD_TERMS = ["法规", "招标", "投标", "采购", "合同", "质疑", "投诉",
                  "限额", "标准", "规定", "条件", "流程", "期限", "罚款", "责任"]
_CONCEPT_TERMS = ["什么", "如何", "为什么", "区别", "对比", "比较", "分析", "评估", "建议"]
MIN_KEYWORD_HITS = 2
MIN_CONCEPT_HITS = 2


def _classify_question(question: str) -> str:
    kw = sum(1 for t in _KEYWORD_TERMS if t in question)
    cp = sum(1 for t in _CONCEPT_TERMS if t in question)
    if kw >= MIN_KEYWORD_HITS:
        return "keyword"
    if cp >= MIN_CONCEPT_HITS and kw == 0:
        return "concept"
    return "mixed"


def _rrf_k_for(question: str) -> int:
    return {"keyword": 30, "concept": 90, "mixed": 60}[_classify_question(question)]


class VectorStore:
    def __init__(self):
        self._client = None

    def _get_client(self) -> QdrantClient:
        if self._client is None:
            self._client = QdrantClient(
                url=settings.qdrant_url, api_key=settings.qdrant_api_key,
                timeout=settings.qdrant_timeout, trust_env=False)
        return self._client

    def create_collection(self, force: bool = False) -> None:
        c = self._get_client()
        if force:
            try:
                c.delete_collection(settings.qdrant_collection)
            except Exception:
                pass
        c.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config={"dense": VectorParams(size=settings.qdrant_vector_size, distance=Distance.COSINE)},
            sparse_vectors_config={"sparse": SparseVectorParams()},
        )

    def upsert_points(self, points: list[dict], batch_size: int = 64) -> None:
        """写入 Qdrant, payload 支持元数据字段 (source_file, section_title, doc_type, chunk_id)."""
        c = self._get_client()
        for i in range(0, len(points), batch_size):
            batch = points[i:i + batch_size]
            qdrant_points = []
            for p in batch:
                payload = {
                    "question": p["question"],
                    "answer": p["answer"],
                }
                # 元数据: 有则存, 无则忽略
                for meta_key in ("source_file", "section_title", "doc_type", "chunk_id"):
                    if meta_key in p and p[meta_key]:
                        payload[meta_key] = p[meta_key]
                qdrant_points.append(PointStruct(
                    id=p["id"],
                    vector={"dense": p["dense"], "sparse": p["sparse"]},
                    payload=payload,
                ))
            c.upsert(
                collection_name=settings.qdrant_collection,
                points=qdrant_points)

    def collection_exists(self) -> bool:
        try:
            return self._get_client().collection_exists(settings.qdrant_collection)
        except Exception:
            return False

    def count(self) -> int:
        try:
            return self._get_client().count(settings.qdrant_collection).count
        except Exception:
            return 0

    def _retry_call(self, fn, retries: int = 2, delay: float = 1.0):
        for attempt in range(retries + 1):
            try:
                return fn()
            except ResponseHandlingException as e:
                if attempt == retries:
                    logger.warning("Qdrant 调用失败: %s", e)
                    return None
                time.sleep(delay)

    def hybrid_search(self, query_dense, query_sparse, limit: int,
                      dense_limit: int = 30, sparse_limit: int = 30,
                      question: str = "") -> list[dict]:
        k = _rrf_k_for(question)
        c = self._get_client()

        def _call():
            return c.query_points(
                collection_name=settings.qdrant_collection,
                prefetch=[
                    Prefetch(query=query_dense, using="dense", limit=dense_limit),
                    Prefetch(query=query_sparse, using="sparse", limit=sparse_limit),
                ],
                query=RrfQuery(rrf=Rrf(k=k)), limit=limit, with_payload=True)

        resp = self._retry_call(_call)
        if resp is None:
            return []
        results = []
        for h in resp.points:
            item = {
                "id": h.id,
                "score": h.score,
                "question": h.payload.get("question", ""),
                "answer": h.payload.get("answer", ""),
            }
            # 透传元数据
            for meta_key in ("source_file", "section_title", "doc_type", "chunk_id"):
                val = h.payload.get(meta_key)
                if val:
                    item[meta_key] = val
            results.append(item)
        return results


vector_store = VectorStore()
