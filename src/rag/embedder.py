"""Embedder (BGE + BM25) / Reranker (CrossEncoder)"""
import json
import logging
import math
import threading
from collections import Counter
from pathlib import Path

logger = logging.getLogger(__name__)

BGE_MODEL_NAME = "BAAI/bge-small-zh-v1.5"
RERANKER_MODEL_NAME = "BAAI/bge-reranker-base"
BGE_QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："
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
    def __init__(self):
        self._dense_model = None
        self._dense_lock = threading.Lock()
        self._sparse = SparseEncoder()

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
            logger.info("嵌入模型预热完成")
            return model

    def encode_query_dense(self, text: str) -> list[float]:
        return self._load_dense().encode(BGE_QUERY_PREFIX + text, normalize_embeddings=True).tolist()

    def encode_document_dense(self, text: str) -> list[float]:
        return self._load_dense().encode(text, normalize_embeddings=True).tolist()

    def fit_sparse(self, documents): self._sparse.fit(documents)
    def save_vocab(self): self._sparse.save()
    def load_vocab(self): return self._sparse.load()
    def encode_query_sparse(self, text): return self._sparse.encode(text)
    def encode_document_sparse(self, text): return self._sparse.encode(text)


class Reranker:
    def __init__(self):
        self._model = None
        self._lock = threading.Lock()

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
            logger.info("精排模型预热完成")
            return self._model

    def rerank(self, query: str, docs: list[dict], top_k: int) -> list[dict]:
        if len(docs) <= 1:
            return docs
        model = self._load()
        pairs = [(query, d.get("answer", "")) for d in docs]
        scores = model.predict(pairs)
        for d, s in zip(docs, scores):
            d["score"] = float(s)
        docs.sort(key=lambda d: -d["score"])
        return docs[:top_k]


embedder = Embedder()
reranker = Reranker()
