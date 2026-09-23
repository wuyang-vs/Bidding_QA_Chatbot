from __future__ import annotations
"""Embedder (BGE-M3 Dense + BM25 Sparse) / Reranker (bge-reranker-v2-m3 CrossEncoder)

支持远端推理服务 (vLLM: /v1/embeddings + /v1/rerank), 由 REMOTE_EMBED_BASE /
REMOTE_RERANK_BASE 配置; 远端失败自动回退本地 sentence-transformers 模型 (懒加载)。
"""
import json
import logging
import math
import threading
import time
from collections import Counter
from pathlib import Path

import httpx

from src.config import settings

logger = logging.getLogger(__name__)

# 升级: bge-small-zh-v1.5 → BAAI/bge-m3
# BGE-M3: 多语言, 1024 维, 支持 ColBERT (Late Interaction)
BGE_MODEL_NAME = "BAAI/bge-m3"
# BGE-M3 不需要 bge-small-zh 的长前缀, 空字符串即可
BGE_QUERY_PREFIX = ""
BGE_DOC_PREFIX = ""

# 升级: bge-reranker-base → BAAI/bge-reranker-v2-m3
RERANKER_MODEL_NAME = "BAAI/bge-reranker-v2-m3"

VOCAB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "vocab.json"


class SparseEncoder:
    def __init__(self, k1: float = 1.2):
        self.k1 = k1
        self.vocab: dict[str, int] = {}
        self.idf: list[float] = []

    def _tokenize(self, text: str) -> list[str]:
        import jieba
        return [t for t in jieba.lcut(text) if len(t) > 1 and t.strip()]

    def fit(self, documents: list[str]) -> None:
        df: Counter = Counter()
        tokenized = []
        for doc in documents:
            tokens = set(self._tokenize(doc))
            tokenized.append(tokens)
            for t in tokens:
                df[t] += 1
        sorted_tokens = sorted(df.keys(), key=lambda t: -df[t])
        self.vocab = {t: i for i, t in enumerate(sorted_tokens)}
        n = len(documents)
        self.idf = [0.0] * len(sorted_tokens)
        for t, i in self.vocab.items():
            d = df[t]
            self.idf[i] = math.log((n - d + 0.5) / (d + 0.5) + 1)

    def encode(self, text: str) -> dict:
        tokens = self._tokenize(text)
        if not tokens or not self.vocab:
            return {"indices": [], "values": []}
        tf = Counter(tokens)
        total = len(tokens)
        entries = []
        for token, count in tf.items():
            idx = self.vocab.get(token)
            if idx is None:
                continue
            tf_norm = count / total
            weight = self.idf[idx] * ((self.k1 + 1) * tf_norm) / (self.k1 + tf_norm)
            entries.append((idx, weight))
        entries.sort(key=lambda x: x[0])
        return {"indices": [e[0] for e in entries], "values": [e[1] for e in entries]}

    def save(self) -> None:
        VOCAB_PATH.parent.mkdir(parents=True, exist_ok=True)
        VOCAB_PATH.write_text(json.dumps(
            {"vocab": self.vocab, "idf": self.idf}, ensure_ascii=False), encoding="utf-8")

    def load(self) -> bool:
        if not VOCAB_PATH.exists():
            return False
        data = json.loads(VOCAB_PATH.read_text(encoding="utf-8"))
        self.vocab = data["vocab"]
        self.idf = data["idf"]
        return True


class Embedder:
    # 远端失败后的熔断窗口: 该时间内直接走本地, 避免每个请求都吃超时
    REMOTE_COOLDOWN_S = 60.0

    def __init__(self):
        self._dense_model = None
        self._dense_lock = threading.Lock()
        self._sparse = SparseEncoder()
        self._remote_down_until = 0.0

    def _encode_remote(self, texts: list[str]) -> list[list[float]] | None:
        """调远端 Infinity /v1/embeddings; 失败返回 None 并熔断 60s."""
        base = settings.remote_embed_base
        if not base or time.monotonic() < self._remote_down_until:
            return None
        try:
            resp = httpx.post(
                base.rstrip("/") + "/v1/embeddings",
                json={"model": BGE_MODEL_NAME, "input": texts},
                timeout=settings.remote_embed_timeout)
            resp.raise_for_status()
            items = resp.json()["data"]
            vecs: list[list[float] | None] = [None] * len(items)
            for item in items:
                vecs[item["index"]] = item["embedding"]
            out = []
            for v in vecs:
                if v is None:
                    return None
                # 与本地 normalize_embeddings=True 保持同一向量空间
                norm = math.sqrt(sum(x * x for x in v)) or 1.0
                out.append([x / norm for x in v])
            return out
        except Exception as e:
            self._remote_down_until = time.monotonic() + self.REMOTE_COOLDOWN_S
            logger.warning("远端 embeddings 调用失败 (%.0fs 内走本地): %s",
                           self.REMOTE_COOLDOWN_S, e)
            return None

    def _load_dense(self):
        if self._dense_model is not None:
            return self._dense_model
        with self._dense_lock:
            if self._dense_model is not None:
                return self._dense_model
            from sentence_transformers import SentenceTransformer
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            try:
                model = SentenceTransformer(BGE_MODEL_NAME, device=device)
            except (torch.OutOfMemoryError, AssertionError):
                logger.warning("GPU 不可用或 OOM, 降级 CPU")
                model = SentenceTransformer(BGE_MODEL_NAME, device="cpu")
            self._dense_model = model
            logger.info("嵌入模型预热完成: %s (dim=%d)", BGE_MODEL_NAME,
                        model.get_sentence_embedding_dimension())
            return model

    def encode_query_dense(self, text: str) -> list[float]:
        vecs = self._encode_remote([BGE_QUERY_PREFIX + text])
        if vecs is not None:
            return vecs[0]
        return self._load_dense().encode(BGE_QUERY_PREFIX + text, normalize_embeddings=True).tolist()

    def encode_document_dense(self, text: str) -> list[float]:
        vecs = self._encode_remote([BGE_DOC_PREFIX + text])
        if vecs is not None:
            return vecs[0]
        return self._load_dense().encode(BGE_DOC_PREFIX + text, normalize_embeddings=True).tolist()

    def fit_sparse(self, documents): self._sparse.fit(documents)
    def save_vocab(self): self._sparse.save()
    def load_vocab(self): return self._sparse.load()
    def encode_query_sparse(self, text): return self._sparse.encode(text)
    def encode_document_sparse(self, text): return self._sparse.encode(text)


class Reranker:
    REMOTE_COOLDOWN_S = 60.0

    def __init__(self):
        self._model = None
        self._lock = threading.Lock()
        self._remote_down_until = 0.0

    def _rerank_remote(self, query: str, docs: list[dict]) -> list[dict] | None:
        """调远端 vLLM /v1/rerank, 返回按分数降序的 docs; 失败返回 None 并熔断."""
        base = settings.remote_rerank_base
        if not base or time.monotonic() < self._remote_down_until:
            return None
        try:
            resp = httpx.post(
                base.rstrip("/") + "/v1/rerank",
                json={"model": RERANKER_MODEL_NAME, "query": query,
                      "documents": [d.get("question", "") + " " + d.get("answer", "")
                                    for d in docs]},
                timeout=settings.remote_embed_timeout)
            resp.raise_for_status()
            results = resp.json()["results"]
            scored: list[dict] = []
            for r in results:
                d = docs[r["index"]]
                d["score"] = float(r["relevance_score"])
                scored.append(d)
            scored.sort(key=lambda d: -d["score"])
            return scored
        except Exception as e:
            self._remote_down_until = time.monotonic() + self.REMOTE_COOLDOWN_S
            logger.warning("远端 rerank 调用失败 (%.0fs 内走本地): %s",
                           self.REMOTE_COOLDOWN_S, e)
            return None

    def _load(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            from sentence_transformers import CrossEncoder
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            try:
                self._model = CrossEncoder(RERANKER_MODEL_NAME, device=device)
            except (torch.OutOfMemoryError, AssertionError):
                self._model = CrossEncoder(RERANKER_MODEL_NAME, device="cpu")
            logger.info("精排模型预热完成: %s", RERANKER_MODEL_NAME)
            return self._model

    def rerank(self, query: str, docs: list[dict], top_k: int) -> list[dict]:
        if len(docs) <= 1:
            return docs
        remote = self._rerank_remote(query, docs)
        if remote is not None:
            return remote[:top_k]
        model = self._load()
        pairs = [(query, d.get("question", "") + " " + d.get("answer", "")) for d in docs]
        scores = model.predict(pairs)
        for d, s in zip(docs, scores):
            d["score"] = float(s)
        docs.sort(key=lambda d: -d["score"])
        return docs[:top_k]


embedder = Embedder()
reranker = Reranker()
