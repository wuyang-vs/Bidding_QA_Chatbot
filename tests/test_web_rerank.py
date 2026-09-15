"""联网结果重排: 归一化 / 单条跳过 / 异常降级"""
import os
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from unittest.mock import MagicMock, patch

from src.tools.rag_tools import _rerank_web_results, _fmt_web


def test_rerank_single_item_skip():
    """< 2 条应跳过重排, 原样返回"""
    items = [{"question": "Q", "answer": "A"}]
    out = _rerank_web_results("q", items)
    assert out == items


def test_rerank_normalizes_scores():
    """多条结果, reranker 返回分数应被归一到 [0,1]"""
    items = [
        {"question": "Q1", "answer": "A1"},
        {"question": "Q2", "answer": "A2"},
        {"question": "Q3", "answer": "A3"},
    ]
    fake_reranked = [
        {"answer": "Q2\nA2", "_i": 1, "score": 0.9},
        {"answer": "Q1\nA1", "_i": 0, "score": 0.3},
        {"answer": "Q3\nA3", "_i": 2, "score": 0.6},
    ]
    with patch("src.tools.rag_tools.reranker") as mock_rr:
        mock_rr.rerank.return_value = fake_reranked
        out = _rerank_web_results("q", items)
    # 顺序应按 reranker 给的顺序
    assert [it["question"] for it in out] == ["Q2", "Q1", "Q3"]
    # 分数应归一到 [0,1]
    scores = [it["score"] for it in out]
    assert max(scores) <= 1.0
    assert min(scores) >= 0.0
    # 最高分应为 1.0
    assert scores[0] == 1.0


def test_rerank_exception_fallback():
    """reranker 抛异常应原样返回"""
    items = [{"question": "Q1", "answer": "A1"},
             {"question": "Q2", "answer": "A2"}]
    with patch("src.tools.rag_tools.reranker") as mock_rr:
        mock_rr.rerank.side_effect = RuntimeError("模型故障")
        out = _rerank_web_results("q", items)
    assert out == items


def test_rerank_uniform_scores():
    """所有分数相同时应避免除零, 走 mx>0 分支全部置 1.0"""
    items = [{"question": "Q1", "answer": "A1"},
             {"question": "Q2", "answer": "A2"}]
    fake = [
        {"answer": "Q1\nA1", "_i": 0, "score": 0.5},
        {"answer": "Q2\nA2", "_i": 1, "score": 0.5},
    ]
    with patch("src.tools.rag_tools.reranker") as mock_rr:
        mock_rr.rerank.return_value = fake
        out = _rerank_web_results("q", items)
    assert all(it["score"] == 1.0 for it in out)


def test_rerank_all_zero_scores():
    """全零分数应置 0.0"""
    items = [{"question": "Q1", "answer": "A1"},
             {"question": "Q2", "answer": "A2"}]
    fake = [
        {"answer": "Q1\nA1", "_i": 0, "score": 0.0},
        {"answer": "Q2\nA2", "_i": 1, "score": 0.0},
    ]
    with patch("src.tools.rag_tools.reranker") as mock_rr:
        mock_rr.rerank.return_value = fake
        out = _rerank_web_results("q", items)
    assert all(it["score"] == 0.0 for it in out)


def test_fmt_web_empty():
    assert _fmt_web([]) == "未找到联网结果"


def test_fmt_web_truncates():
    items = [{"question": f"Q{i}", "answer": "A" * 500, "url": "http://x"} for i in range(10)]
    out = _fmt_web(items)
    # _fmt_web 只保留前 5 条
    assert out.count("http://x") == 5
