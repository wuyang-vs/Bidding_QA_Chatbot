"""RAGPipeline: 混合检索 + 精排 + LLM 生成 (LRU 缓存)"""
import logging
from functools import lru_cache

from src.rag.embedder import embedder, reranker
from src.rag.vector_store import vector_store
from src.clients.llm_factory import get_llm_client

logger = logging.getLogger(__name__)


@lru_cache(maxsize=128)
def _cached_search(question: str, top_k: int) -> tuple:
    dense = embedder.encode_query_dense(question)
    sparse = embedder.encode_query_sparse(question)
    recall_limit = max(top_k * 6, 30)
    docs = vector_store.hybrid_search(dense, sparse, limit=recall_limit, question=question)
    docs = reranker.rerank(question, docs, top_k)
    return tuple((d["question"], d["answer"], d["score"]) for d in docs)


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
        embedder._load_dense()
        reranker._load()
        self._ready = True
        logger.info("RAG 流水线初始化完成")

    @property
    def ready(self): return self._ready

    def search(self, question: str, top_k: int = 5) -> list[dict]:
        return [{"question": q, "answer": a, "score": s}
                for q, a, s in _cached_search(question, top_k)]

    @staticmethod
    def clear_cache(): _cached_search.cache_clear()

    @staticmethod
    def cache_info(): return _cached_search.cache_info()

    def ask(self, question: str, top_k: int = 5) -> dict:
        docs = self.search(question, top_k)
        context = "\n\n".join(f"【资料{i+1}】\n问: {d['question']}\n答: {d['answer']}"
                              for i, d in enumerate(docs))
        if self._llm is None:
            self._llm = get_llm_client()
        prompt = (f"请严格基于以下资料回答问题，不要编造资料中没有的内容。\n\n"
                  f"{context}\n\n问题: {question}\n回答:")
        answer = self._llm.chat([{"role": "user", "content": prompt}])
        return {"answer": answer, "sources": docs}


rag_pipeline = RAGPipeline()
