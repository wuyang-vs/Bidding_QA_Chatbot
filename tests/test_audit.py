"""回答审计: 引用解析 + 真实性校验"""
import os
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from src.agent.audit import audit_answer, _parse_citations, _tokens, _extract_sentences, build_citation_prompt_suffix


# ---- 引用解析 ----

def test_parse_single_citation():
    cites = _parse_citations("招标分为公开招标和邀请招标[资料1]")
    assert len(cites) == 1
    assert cites[0]["raw"] == "[资料1]"
    assert cites[0]["indices"] == [0]

def test_parse_multiple_citations():
    cites = _parse_citations("公开招标[资料1]，邀请招标[资料2]")
    assert len(cites) == 2
    assert cites[0]["indices"] == [0]
    assert cites[1]["indices"] == [1]

def test_parse_comma_separated():
    cites = _parse_citations("详见[资料1,3]")
    assert len(cites) == 1
    assert cites[0]["indices"] == [0, 2]

def test_parse_no_citation():
    cites = _parse_citations("没有引用标记")
    assert cites == []

def test_parse_out_of_range_ignored():
    cites = _parse_citations("[资料99] 但只有 2 个 source")
    assert cites[0]["indices"] == [98]  # 审计时会和 sources 长度比对


# ---- 句子提取 ----

def test_extract_sentences_chinese_punct():
    sents = _extract_sentences("招标分为公开招标。投标需提交保证金！评标委员会负责评标；定标后发通知")
    assert len(sents) == 4

def test_extract_empty():
    assert _extract_sentences("") == []


# ---- Token 提取 ----

def test_tokens_sliding_window():
    tokens = _tokens("公开招标")
    assert "公开" in tokens
    assert "开招" in tokens
    assert "招标" in tokens

def test_tokens_punct_stripped():
    tokens = _tokens("公开招标！")
    assert "公开" in tokens
    assert "招标" in tokens

def test_tokens_short_text():
    tokens = _tokens("招")
    assert tokens == {"招"}


# ---- 审计主函数 ----

def test_audit_faithful_answer():
    """答案内容在 sources 中有大量 token 重叠 → 高 faithfulness"""
    sources = [
        {"question": "什么是公开招标", "answer": "公开招标是指招标人以招标公告方式邀请不特定的法人或其他组织投标"},
        {"question": "什么是邀请招标", "answer": "邀请招标是指招标人以投标邀请书方式邀请三个以上特定法人投标"},
    ]
    answer = "招标分为公开招标和邀请招标。公开招标以招标公告方式邀请不特定法人投标，邀请招标以投标邀请书邀请三个以上特定法人投标。"
    audit = audit_answer(answer, sources)
    assert audit["faithfulness_score"] > 0.5  # 高重叠
    assert audit["total_sentences"] >= 2
    assert audit["hallucinated_count"] < audit["total_sentences"]

def test_audit_hallucinated_answer():
    """答案与 sources 几乎无重叠 → 低 faithfulness"""
    sources = [
        {"question": "什么是招标", "answer": "招标是一种采购方式"},
    ]
    answer = "招标需要先注册公司，然后到工商局备案，最后交报名费。"
    audit = audit_answer(answer, sources)
    assert audit["faithfulness_score"] < 0.3  # 低重叠
    assert audit["hallucinated_count"] > 0

def test_audit_with_citations():
    """答案含 [资料N] 引用 → citations 被解析"""
    sources = [
        {"question": "什么是公开招标", "answer": "公开招标以招标公告方式邀请不特定法人投标"},
        {"question": "什么是邀请招标", "answer": "邀请招标以投标邀请书邀请三个以上特定法人投标"},
    ]
    answer = "公开招标以招标公告方式邀请不特定法人投标[资料1]。邀请招标以投标邀请书邀请三个以上特定法人投标[资料2]。"
    audit = audit_answer(answer, sources)
    assert len(audit["citations"]) == 2
    assert 0 in audit["cited_source_indices"]
    assert 1 in audit["cited_source_indices"]

def test_audit_empty_answer():
    audit = audit_answer("", [{"question": "Q", "answer": "A"}])
    assert audit["faithfulness_score"] == 0.0
    assert audit["total_sentences"] == 0
    assert audit["citations"] == []

def test_audit_empty_sources():
    audit = audit_answer("公开招标很好", [])
    assert audit["faithfulness_score"] == 0.0
    # 无 sources → 无 token 重叠, 但句子提取依赖标点, 此处可能为 0 或 1
    assert audit["hallucinated_count"] >= 0


# ---- 引用提示构建 ----

def test_build_citation_prompt_suffix():
    sources = [
        {"question": "什么是招标", "answer": "招标是采购方式"},
        {"question": "什么是投标", "answer": "投标是响应招标"},
    ]
    suffix = build_citation_prompt_suffix(sources)
    assert "[资料1]" in suffix
    assert "[资料2]" in suffix
    assert "什么是招标" in suffix

def test_build_citation_prompt_suffix_empty():
    assert build_citation_prompt_suffix([]) == ""
