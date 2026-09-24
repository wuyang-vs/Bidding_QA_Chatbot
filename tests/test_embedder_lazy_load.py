"""Embedder / Reranker 懒加载双检锁 + GPU OOM 降级"""
import os
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from unittest.mock import MagicMock, patch

from src.rag.embedder import Embedder, Reranker, SparseEncoder


def test_embedder_lazy_load_single_init():
    """_load_dense 只应初始化一次 (双检锁)"""
    emb = Embedder()
    fake_model = MagicMock()
    fake_model.encode.return_value = MagicMock(tolist=lambda: [0.1])

    with patch("sentence_transformers.SentenceTransformer", return_value=fake_model) as mock_st:
        with patch("torch.cuda.is_available", return_value=False):
            emb._load_dense()
            emb._load_dense()
            emb._load_dense()
    assert mock_st.call_count == 1


def test_embedder_gpu_oom_fallback_cpu():
    """GPU OOM / AssertionError 应回退 CPU"""
    emb = Embedder()
    fake_model = MagicMock()

    call_count = [0]
    def _st(name, device=None):
        call_count[0] += 1
        if device == "cuda":
            raise AssertionError("no cuda")
        return fake_model

    with patch("sentence_transformers.SentenceTransformer", side_effect=_st):
        with patch("torch.cuda.is_available", return_value=True):
            emb._load_dense()
    # 应已回退到 CPU, _dense_model 非 None
    assert emb._dense_model is fake_model
    # 应被调用 2 次: cuda 失败 + cpu 回退
    assert call_count[0] == 2


def test_reranker_lazy_load_single_init():
    """Reranker _load 双检锁"""
    rr = Reranker()
    fake_model = MagicMock()
    fake_model.predict.return_value = [0.9]

    with patch("sentence_transformers.CrossEncoder", return_value=fake_model) as mock_ce:
        with patch("torch.cuda.is_available", return_value=False):
            rr._load()
            rr._load()
    assert mock_ce.call_count == 1


def test_reranker_skip_single_doc():
    """docs <= 1 应直接返回, 不加载模型"""
    rr = Reranker()
    with patch.object(rr, "_load") as mock_load:
        out = rr.rerank("q", [{"answer": "a"}], top_k=5)
        mock_load.assert_not_called()
    assert out == [{"answer": "a"}]


def test_reranker_sorts_by_score():
    """多文档应按 score 降序 (屏蔽远端 rerank, 保证本地模型路径封闭可测)"""
    rr = Reranker()
    fake_model = MagicMock()
    fake_model.predict.return_value = [0.1, 0.9, 0.5]
    rr._model = fake_model

    docs = [{"answer": "a"}, {"answer": "b"}, {"answer": "c"}]
    with patch.object(rr, "_rerank_remote", return_value=None):
        out = rr.rerank("q", docs, top_k=2)
    assert len(out) == 2
    assert out[0]["score"] >= out[1]["score"]
    # 预测分数最高的应排第一
    assert out[0]["answer"] == "b"


def test_sparse_encoder_empty_vocab():
    """vocab 为空时 encode 应返回空 indices/values"""
    sp = SparseEncoder()
    sp.vocab = {}
    sp.idf = []
    out = sp.encode("任意文本")
    assert out == {"indices": [], "values": []}


def test_sparse_encoder_save_load(tmp_path, monkeypatch):
    """save→load 往返应保留 vocab/idf"""
    sp = SparseEncoder()
    # 构造最小词表
    sp.vocab = {"招标": 0, "投标": 1}
    sp.idf = [1.5, 2.0]

    import src.rag.embedder as emb_mod
    monkeypatch.setattr(emb_mod, "VOCAB_PATH", tmp_path / "vocab.json")

    sp.save()
    assert (tmp_path / "vocab.json").exists()

    sp2 = SparseEncoder()
    assert sp2.load() is True
    assert sp2.vocab == {"招标": 0, "投标": 1}
    assert sp2.idf == [1.5, 2.0]


def test_sparse_encoder_load_missing_file(tmp_path, monkeypatch):
    import src.rag.embedder as emb_mod
    monkeypatch.setattr(emb_mod, "VOCAB_PATH", tmp_path / "nope.json")
    sp = SparseEncoder()
    assert sp.load() is False
