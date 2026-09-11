from src.rag.vector_store import _classify_question, _rrf_k_for


def test_keyword():
    assert _classify_question("招标投标法规流程期限") == "keyword"


def test_concept():
    assert _classify_question("什么是区别如何对比") == "concept"


def test_concept_with_keyword_is_mixed():
    assert _classify_question("招标如何对比") == "mixed"


def test_empty_is_mixed():
    assert _classify_question("") == "mixed"


def test_rrf_k_mapping():
    assert _rrf_k_for("招标投标法规流程期限") == 30
    assert _rrf_k_for("什么是区别如何对比") == 90
    assert _rrf_k_for("随便") == 60
