from src.tools.rag_tools import _fmt_rag, _fmt_graph, _fmt_pg, _fmt_web


def test_fmt_rag_empty():
    assert "未检索" in _fmt_rag([])


def test_fmt_rag_normal():
    docs = [{"question": "Q", "answer": "A", "score": 0.87}]
    out = _fmt_rag(docs)
    assert "【资料1】" in out and "0.870" in out


def test_fmt_graph_empty():
    assert "未找到" in _fmt_graph([])


def test_fmt_pg_empty():
    assert "未查询到" in _fmt_pg([])


def test_fmt_web_empty():
    assert "未找到" in _fmt_web([])


def test_fmt_web_with_url():
    items = [{"question": "T", "answer": "A", "url": "https://x.com", "score": 0.5}]
    out = _fmt_web(items)
    assert "https://x.com" in out
