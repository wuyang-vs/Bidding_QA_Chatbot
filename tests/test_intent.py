"""意图检测: 超范围拒答 / 模糊问题引导 / 空结果诚实约束"""
import os
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from src.agent.intent import (
    is_out_of_scope, is_vague_question,
    scope_rejection_message, vague_guidance_message,
    DOMAIN_KEYWORDS,
)


# ---- 超范围检测 ----

def test_medical_is_out_of_scope():
    assert is_out_of_scope("感冒了吃什么药") is True

def test_education_is_out_of_scope():
    assert is_out_of_scope("高考怎么复习数学") is True

def test_contract_law_general_is_out_of_scope():
    """通用合同法问题 (非招投标) → 超范围"""
    assert is_out_of_scope("合同违约怎么赔偿") is True

def test_bidding_keyword_in_scope():
    assert is_out_of_scope("招标流程是什么") is False

def test_procurement_in_scope():
    assert is_out_of_scope("政府采购的方式有哪些") is False

def test_zhongbiao_in_scope():
    assert is_out_of_scope("中标通知书什么时候发") is False

def test_empty_question_is_out_of_scope():
    assert is_out_of_scope("") is True
    assert is_out_of_scope("   ") is True

def test_out_of_scope_with_domain_history():
    """当前问题超范围, 但历史有招投标上下文 → 不短路 (让 LLM 判断)"""
    history = [{"role": "user", "content": "招标流程是什么"}]
    assert is_out_of_scope("合同违约怎么赔偿", history) is False

def test_out_of_scope_without_history():
    """同样的超范围问题, 无历史 → 超范围"""
    assert is_out_of_scope("合同违约怎么赔偿", []) is True


# ---- 模糊问题检测 ----

def test_too_short_is_vague():
    assert is_vague_question("怎么办") is True

def test_pure_pronoun_is_vague():
    assert is_vague_question("这个怎么样") is True

def test_why_without_entity_is_vague():
    assert is_vague_question("为什么会这样") is True

def test_bidding_question_not_vague():
    assert is_vague_question("招投标的公开招标流程是什么") is False

def test_short_but_has_domain_not_vague():
    """即使短, 但含招投标关键词 → 不算模糊"""
    assert is_vague_question("招标流程") is False
    assert is_vague_question("中标时间") is False

def test_empty_is_vague():
    assert is_vague_question("") is True

def test_pronoun_with_domain_history_not_vague():
    """有历史上下文 + 指代 → 不算模糊 (承接上文)"""
    history = [{"role": "user", "content": "招标流程是什么"}]
    assert is_vague_question("那开标呢", history) is False


# ---- 模板消息 ----

def test_scope_rejection_mentions_bidding():
    msg = scope_rejection_message("感冒吃什么药")
    assert "招投标" in msg
    assert "不属于" in msg

def test_vague_guidance_asks_for_more():
    msg = vague_guidance_message("怎么办")
    assert "补充" in msg or "具体" in msg


# ---- 空结果约束 (react_loop) ----

def test_empty_sources_triggers_honesty_constraint():
    """调过工具但 all_sources+web_sources 都空 → 应注入诚实约束"""
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch
    from src.agent.react_loop import ReActMixin
    from src.agent.generation import GenerationMixin

    class _Agent(ReActMixin, GenerationMixin):
        pass

    agent = _Agent()
    llm = MagicMock()
    # 第一轮 LLM 返回 tool_call
    tc = SimpleNamespace(id="tc1", function=SimpleNamespace(
        name="search_bidding_knowledge", arguments='{"query":"x"}'))
    llm.chat_raw.return_value = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=None, tool_calls=[tc]))])

    # 工具返回空结果 (sources 空)
    import src.tools.base as base_mod
    orig_runner = base_mod.ToolRunner.run_parallel
    base_mod.ToolRunner.run_parallel = staticmethod(lambda *a, **k: [
        SimpleNamespace(name="search_bidding_knowledge",
                        text="未检索到相关文档", sources=[])])

    # patch _generate_stream 捕获传入的 messages
    captured = {}
    def _fake_generate_stream(self, msgs, llm, **kw):
        captured["msgs"] = msgs
        yield ("token", {"content": "未找到相关信息"})

    with patch.object(_Agent, "_generate_stream", _fake_generate_stream):
        messages = [{"role": "system", "content": "sys"},
                    {"role": "user", "content": "Q"}]
        events = list(agent._chat_stream_tools(
            messages, "Q", llm, ["search_bidding_knowledge"], False))

    base_mod.ToolRunner.run_parallel = orig_runner

    # 检查 final_messages 里是否注入了诚实约束
    final_msgs = captured.get("msgs", [])
    honesty_msgs = [m for m in final_msgs
                    if isinstance(m, dict)
                    and m.get("role") == "system"
                    and "未返回有效结果" in m.get("content", "")]
    assert len(honesty_msgs) >= 1, f"未找到诚实约束, final_msgs 最后几条: {final_msgs[-3:]}"
