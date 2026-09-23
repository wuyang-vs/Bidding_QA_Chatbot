from __future__ import annotations
"""RAGPipeline: Query 规划 + 多路 RRF 融合 + 精排 + 来源多样性 + LRU 缓存"""
import logging
import time
from functools import lru_cache

from src.rag.embedder import embedder, reranker
from src.rag.vector_store import vector_store
from src.rag.query_planner import plan_query
from src.rag.diversity import apply_source_diversity
from src.config import settings
from src.clients.llm_factory import get_llm_client

logger = logging.getLogger(__name__)


def _rrf_merge_multi(results_list: list[list[dict]], k: int = 60) -> list[dict]:
    """多路检索结果用 RRF 合并.
    
    每路 results 内部是 score 降序. RRF 分数 = Σ 1/(k + rank).
    """
    merged: dict = {}
    for results in results_list:
        for rank, d in enumerate(results, 1):
            # 用 (question, answer) 作为去重 key
            key = (d.get("question", ""), d.get("answer", ""))
            rrf_score = 1.0 / (k + rank)
            if key in merged:
                merged[key]["_rrf"] += rrf_score
            else:
                merged[key] = {**d, "_rrf": rrf_score}
    merged_list = sorted(merged.values(), key=lambda x: -x["_rrf"])
    for d in merged_list:
        d.pop("_rrf", None)
    return merged_list


@lru_cache(maxsize=256)
def _cached_search(question: str, top_k: int, scope_key: str = "all",
                   access_scope: tuple | None = None) -> tuple:
    t0 = time.perf_counter()
    dense = embedder.encode_query_dense(question)
    sparse = embedder.encode_query_sparse(question)
    t1 = time.perf_counter()
    recall_limit = max(top_k * 6, 30)
    # access_scope 由调用方按当前请求身份显式传入, scope_key 保证缓存不跨身份串用
    docs = vector_store.hybrid_search(
        dense, sparse, limit=recall_limit, question=question,
        access_scope=access_scope)
    t2 = time.perf_counter()
    docs = reranker.rerank(question, docs, top_k)
    t3 = time.perf_counter()
    logger.info("[RAG耗时] 单路: embed=%.0fms qdrant=%.0fms rerank=%.0fms | 共%d条",
                (t1 - t0) * 1000, (t2 - t1) * 1000, (t3 - t2) * 1000, len(docs))
    # 保留完整 dict (含 source_file/doc_type/db_id 等引用元数据)
    return tuple(docs)


class RAGPipeline:
    def __init__(self):
        self._ready = False
        self._llm = None

    def initialize(self) -> None:
        ok = embedder.load_vocab()
        if not ok:
            logger.warning("vocab.json 不存在, 请先运行 python main.py ingest")
            self._ready = False
            return
        if settings.remote_embed_base or settings.remote_rerank_base:
            # 远端模式: 不预加载本地大模型 (失败时才懒加载兜底)
            logger.info("RAG 远端推理: embeddings=%s rerank=%s",
                        settings.remote_embed_base or "(本地)",
                        settings.remote_rerank_base or "(本地)")
        else:
            embedder._load_dense()
            reranker._load()
        self._ready = True
        logger.info("RAG 流水线初始化完成 (BGE-M3 + reranker-v2-m3 + Query规划 + 多样性)")

    @property
    def ready(self): return self._ready

    def search(self, question: str, top_k: int = 5,
               history: list[dict] | None = None) -> list[dict]:
        """增强版检索: Query 规划 → 多路 RRF 融合 → 精排 → 来源多样性.

        行级隔离: 从请求级 ContextVar 读取访问范围 (匿名仅 public,
        purchaser/bidder 为 public+本人, admin/auditor 不限制).
        """
        from src.auth.access_scope import get_current_scope, scope_cache_key
        scope = get_current_scope()
        scope_key = scope_cache_key(scope)

        # 1. Query 规划: 会话补全 + 受控变体
        variants = plan_query(question, history, max_variants=settings.query_variants_max)
        logger.info("Query 规划: %d 个变体", len(variants))

        if len(variants) == 1:
            # 单路, 走缓存 (缓存键含身份范围, 返回完整 dict 保留引用元数据)
            hits_before = _cached_search.cache_info().hits
            result = [dict(d) for d in _cached_search(variants[0], top_k,
                                                      scope_key, scope)]
            if _cached_search.cache_info().hits > hits_before:
                logger.info("[RAG耗时] 缓存命中, 检索开销≈0")
            return result

        # 2. 多路并行检索
        recall_limit = max(top_k * 6, 30)
        all_results = []
        embed_ms = qdrant_ms = 0.0
        t_multi = time.perf_counter()
        for v in variants:
            tv0 = time.perf_counter()
            dense = embedder.encode_query_dense(v)
            sparse = embedder.encode_query_sparse(v)
            tv1 = time.perf_counter()
            results = vector_store.hybrid_search(
                dense, sparse, limit=recall_limit, question=v,
                access_scope=scope)
            tv2 = time.perf_counter()
            embed_ms += (tv1 - tv0) * 1000
            qdrant_ms += (tv2 - tv1) * 1000
            all_results.append(results)
            logger.info("  变体 '%s': %d 条", v[:30], len(results))

        # 3. RRF 融合多路结果
        merged = _rrf_merge_multi(all_results, k=60)
        logger.info("RRF 融合: %d 条", len(merged))

        # 4. CrossEncoder 精排
        tr0 = time.perf_counter()
        reranked = reranker.rerank(question, merged, top_k=top_k * 3)
        tr1 = time.perf_counter()

        # 5. 来源多样性
        td0 = time.perf_counter()
        diversified = apply_source_diversity(
            reranked, max_per_source=settings.source_diversity_max)
        td1 = time.perf_counter()
        logger.info("[RAG耗时] 多路(%d变体): embed=%.0fms qdrant=%.0fms "
                    "rerank=%.0fms diversity=%.0fms | 总计=%.0fms",
                    len(variants), embed_ms, qdrant_ms,
                    (tr1 - tr0) * 1000, (td1 - td0) * 1000,
                    (td1 - t_multi) * 1000)

        return diversified[:top_k]

    @staticmethod
    def clear_cache(): _cached_search.cache_clear()

    @staticmethod
    def cache_info(): return _cached_search.cache_info()

    def ask(self, question: str, top_k: int = 5) -> dict:
        docs = self.search(question, top_k)
        context = "\n\n".join(f"【资料{i+1}】\n问: {d.get('question','')}\n答: {d.get('answer','')}"
                              for i, d in enumerate(docs))
        if self._llm is None:
            self._llm = get_llm_client()
        prompt = (f"请严格基于以下资料回答问题，不要编造资料中没有的内容。\n\n"
                  f"{context}\n\n问题: {question}\n回答:")
        answer = self._llm.chat([{"role": "user", "content": prompt}])
        return {"answer": answer, "sources": docs}


rag_pipeline = RAGPipeline()
