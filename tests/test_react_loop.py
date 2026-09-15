"""ReAct 循环: 轮次上限 / 文本工具调用解析 / 来源合并 / 最终消息清理"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.agent.react_loop import ReActMixin
from src.agent.generation import GenerationMixin
from src.agent.constants import MAX_TOOL_ROUNDS


class _ReAct(ReActMixin, GenerationMixin):
    pass


def _mk_tool_call(name, args, tc_id="tc1"):
    return SimpleNamespace(id=tc_id,
                           function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def _mk_response(content=None, tool_calls=None, reasoning=None):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls,
                          reasoning_content=reasoning)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def test_max_rounds_constraint():
    """LLM 始终返回 tool_calls, 第 MAX_TOOL_ROUNDS+1 轮应触发 for...else 上限约束"""
    react = _ReAct()
    llm = MagicMock()
    # 每轮都返回新 tool_call
    tc = _mk_tool_call("search_bidding_knowledge", {"query": "招标"})
    llm.chat_raw.return_value = _mk_response(tool_calls=[tc])

    # 工具返回空, 避免无限外部状态
    runner = MagicMock()
    runner.run_parallel.return_value = [SimpleNamespace(
        name="search_bidding_knowledge", text="未找到", sources=[])]
    import src.tools.base as base_mod
    orig = base_mod.ToolRunner.run_parallel
    base_mod.ToolRunner.run_parallel = staticmethod(lambda *a, **k: runner.run_parallel(*a, **k))

    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "Q"}]
    events = list(react._chat_stream_tools(messages, "Q", llm,
                                           ["search_bidding_knowledge"], False))
    base_mod.ToolRunner.run_parallel = orig

    # 应包含上限约束消息
    constraint_added = any(
        "上限" in m.get("content", "") for m in messages if m.get("role") == "user")
    assert constraint_added


def test_text_tool_call_parsing_path():
    """LLM 返回纯文本工具调用 (无 tool_calls 字段), 应走 _parse_text_tool_calls 分支"""
    react = _ReAct()
    llm = MagicMock()
    raw = '<invoke name="search_bidding_knowledge"><parameter name="query">招投标流程</parameter></invoke>'
    llm.chat_raw.return_value = _mk_response(content=raw, tool_calls=None)

    import src.tools.base as base_mod
    fake_results = [SimpleNamespace(
        name="search_bidding_knowledge", text="结果", sources=[])]
    orig = base_mod.ToolRunner.run_parallel
    base_mod.ToolRunner.run_parallel = staticmethod(lambda *a, **k: fake_results)

    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "Q"}]
    events = list(react._chat_stream_tools(messages, "Q", llm,
                                           ["search_bidding_knowledge"], False))
    base_mod.ToolRunner.run_parallel = orig

    # 应在 messages 里追加工具返回的 user 消息
    assert any("工具 search_bidding_knowledge 返回" in m.get("content", "")
               for m in messages if m.get("role") == "user")


def test_direct_answer_short_circuit():
    """LLM 直接返回非工具调用文本, 应短路输出 answer"""
    react = _ReAct()
    llm = MagicMock()
    llm.chat_raw.return_value = _mk_response(content="直接答案", tool_calls=None)

    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "Q"}]
    events = list(react._chat_stream_tools(messages, "Q", llm, [], False))
    types = [e[0] for e in events]
    assert "token" in types
    assert "done" in types


def test_llm_failure_first_round_fallback():
    """首轮 LLM 异常应触发 _fallback_rag 路径"""
    react = _ReAct()
    llm = MagicMock()
    llm.chat_raw.side_effect = Exception("网络故障")

    # fallback_rag 会调 rag_pipeline.search; patch 掉
    import src.agent.generation as gen_mod
    orig_search = None
    try:
        from src.rag.pipeline import rag_pipeline
        orig_search = rag_pipeline.search
        rag_pipeline.search = lambda q, top_k=5: []
    except Exception:
        pass
    # patch _generate_stream 防止真调 LLM
    orig_gen = gen_mod.GenerationMixin._generate_stream
    gen_mod.GenerationMixin._generate_stream = lambda self, msgs, llm, **kw: iter([("token", {"content": "兜底"})])

    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "Q"}]
    events = list(react._chat_stream_tools(messages, "Q", llm, [], False))

    gen_mod.GenerationMixin._generate_stream = orig_gen
    if orig_search is not None:
        rag_pipeline.search = orig_search

    assert any(e[0] == "done" for e in events)


def test_merge_sources_dedup():
    """_merge_sources 按 (question, answer) 去重"""
    srcs = [
        {"question": "Q1", "answer": "A1"},
        {"question": "Q1", "answer": "A1"},
        {"question": "Q2", "answer": "A2"},
    ]
    out = _ReAct._merge_sources(srcs)
    assert len(out) == 2


def test_validate_result_quality_tag():
    """search_bidding_knowledge 平均分>=0.5 应标 ✅"""
    sources = [{"score": 0.6}, {"score": 0.8}]
    out = _ReAct._validate_result("search_bidding_knowledge", "内容", sources)
    assert "✅" in out

    sources_low = [{"score": 0.1}, {"score": 0.2}]
    out_low = _ReAct._validate_result("search_bidding_knowledge", "内容", sources_low)
    assert "⚠️" in out_low

    out_empty = _ReAct._validate_result("search_bidding_knowledge", "内容", [])
    assert "⚠️ 未检索到" in out_empty


def test_clean_for_final_structure():
    """_clean_for_final 应重建为 [system, user(原问题), *工具尾, system约束]"""
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "Q"},
        {"role": "assistant", "content": "", "tool_calls": []},
        {"role": "tool", "tool_call_id": "1", "content": "结果"},
    ]
    out = _ReAct._clean_for_final(messages, "Q", 2)
    assert out[0] == {"role": "system", "content": "sys"}
    assert out[1] == {"role": "user", "content": "Q"}
    assert out[-1]["role"] == "system"
    assert "禁止编造" in out[-1]["content"]
