"""三业务线显式意图分类路由离线单测 (确定性, 无 LLM/HTTP)."""
from __future__ import annotations

from src.agent.constants import BASE_TOOL_NAMES
from src.agent.intent import (
    classify_domain, select_tools_for_domain,
    REGULATION_TOOLS, ENTERPRISE_TOOLS,
)


# ---------- 分类 ----------

def test_regulation_strong_single_domain():
    for q in [
        "政府采购法规定的质疑期限是多少天？",
        "对中标结果有异议，怎么投诉？法律依据是什么？",
        "招标人这样收保证金违法吗，依据招标投标法哪一条？",
        "推荐一份建设工程施工合同示范文本",
    ]:
        v = classify_domain(q)
        assert v["domain"] == "regulation", f"{q} -> {v}"
        assert v["confident"] is True


def test_tender_strong_single_domain():
    for q in [
        "帮我写一份技术方案标书章节",
        "投标文件封面和投标函怎么做？",
        "开唱标时在线解密失败怎么办",
        "帮我生成整本投标文件并做对照表",
    ]:
        v = classify_domain(q)
        assert v["domain"] == "tender", f"{q} -> {v}"
        assert v["confident"] is True


def test_enterprise_strong_single_domain():
    for q in [
        "我们公司的营业执照和资质证书怎么维护到企业资料里？",
        "我司安全生产许可证到期了怎么更新证照信息？",
        "企业的银行账户信息在公司档案哪里填？",
    ]:
        v = classify_domain(q)
        assert v["domain"] == "enterprise", f"{q} -> {v}"
        assert v["confident"] is True


def test_cross_domain_tie_falls_back_general():
    # 两个域都有强信号且分差小 → general 不收窄, 保留全部工具
    # (既要写标书又涉及企业主体/投诉救济, 单域子集都会丢工具)
    for q in [
        "帮我写标书的时候我们公司被投诉了该怎么办？",
        "我司营业执照资料和投标文件标书都要准备吗？",
    ]:
        v = classify_domain(q)
        assert v["domain"] == "general", f"{q} -> {v}"
        assert v["confident"] is False


def test_incidental_other_domain_words_do_not_override_intent():
    # "我们公司/供应商"是修饰语, 真实意图是法规救济 → regulation
    for q in [
        "我们公司想投诉采购人，法律允许吗？",
        "供应商对废标结果有异议可以投诉吗？",
    ]:
        v = classify_domain(q)
        assert v["domain"] == "regulation", f"{q} -> {v}"


def test_weak_signal_falls_back_general():
    # 仅弱信号(通用事实查询) → general
    for q in [
        "投标保证金一般不超过多少？",
        "这个项目的预算是多少？",
    ]:
        v = classify_domain(q)
        assert v["domain"] == "general", f"{q} -> {v}"


def test_empty_and_greeting_general():
    assert classify_domain("你好")["domain"] == "general"
    assert classify_domain("")["domain"] == "general"


def test_history_inheritance_for_followup():
    # 追问本身无域信号 → 继承最近一条用户消息的域
    history = [{"role": "user", "content": "政府采购法规定的质疑期限是几天？"}]
    v = classify_domain("那从哪天开始算呢？", history)
    assert v["domain"] == "regulation"
    assert v["inherited"] is True
    # 无历史不继承
    assert classify_domain("那从哪天开始算呢？")["domain"] == "general"
    # 当前问题自带强信号时不继承
    v2 = classify_domain("帮我写标书", history)
    assert v2["domain"] == "tender"
    assert v2["inherited"] is False


# ---------- 工具裁剪 ----------

def test_regulation_subset_keeps_kb_and_appeal():
    names = select_tools_for_domain("regulation", BASE_TOOL_NAMES)
    assert "search_bidding_knowledge" in names  # 跨域底座恒保留
    assert "consult_appeal" in names
    assert "recommend_template" in names
    # 裁掉标书生成/检测/结构化检索
    assert "generate_bid_draft" not in names
    assert "list_bid_documents" not in names
    assert "explain_anomaly" not in names
    assert "search_postgresql" not in names
    assert "search_knowledge_graph" not in names


def test_enterprise_subset_excludes_appeal_and_anomaly():
    names = select_tools_for_domain("enterprise", BASE_TOOL_NAMES)
    assert "search_bidding_knowledge" in names
    assert "search_knowledge_graph" in names   # 供应商/采购人关系
    assert "generate_bid_draft" in names       # 企业资料回填标书
    assert "consult_appeal" not in names
    assert "explain_anomaly" not in names


def test_tender_and_general_keep_full_set():
    assert select_tools_for_domain("tender", BASE_TOOL_NAMES) == BASE_TOOL_NAMES
    assert select_tools_for_domain("general", BASE_TOOL_NAMES) == BASE_TOOL_NAMES
    assert select_tools_for_domain("unknown", BASE_TOOL_NAMES) == BASE_TOOL_NAMES


def test_cross_cutting_tool_always_present():
    for d in ("regulation", "enterprise", "tender", "general"):
        names = select_tools_for_domain(d, BASE_TOOL_NAMES)
        assert "search_bidding_knowledge" in names
        assert len(names) >= 1


def test_order_preserved_and_no_duplicates():
    for d in ("regulation", "enterprise"):
        names = select_tools_for_domain(d, BASE_TOOL_NAMES)
        assert names == [n for n in BASE_TOOL_NAMES if n in names]
        assert len(names) == len(set(names))


def test_subset_constants_include_cross_cutting():
    assert "search_bidding_knowledge" in REGULATION_TOOLS
    assert "search_bidding_knowledge" in ENTERPRISE_TOOLS
