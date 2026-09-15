"""深度思考: thinking/content 分流 + 防泄漏 reset + 提示词回退"""
from unittest.mock import MagicMock

from src.agent.generation import GenerationMixin


class _Gen(GenerationMixin):
    pass


def test_deep_thinking_yields_thinking_and_content():
    """chat_stream_thinking 应按 (kind, text) 分流: thinking→thinking 事件, content→token"""
    gen = _Gen()
    llm = MagicMock()
    llm.chat_stream_thinking.return_value = iter([
        ("thinking", "分析中"),
        ("content", "答案"),
    ])
    events = list(gen._generate_deep([{"role": "user", "content": "Q"}], llm))
    types = [e[0] for e in events]
    assert "thinking" in types
    assert "token" in types


def test_deep_thinking_reset_on_tool_call_leak():
    """深度思考输出泄露工具调用标记时, 应触发 reset 并改走 _generate 重试"""
    gen = _Gen()
    llm = MagicMock()
    # content 含 <invoke 标记 → 触发 _looks_like_tool_call
    leak = '<invoke name="search_bidding_knowledge"><parameter name="query">x</parameter></invoke>'
    llm.chat_stream_thinking.return_value = iter([("content", leak)])
    # _generate 走 llm.chat; patch 为返回干净文本
    llm.chat.return_value = "干净答案"

    events = list(gen._generate_deep([{"role": "user", "content": "Q"}], llm))
    types = [e[0] for e in events]
    assert "reset" in types
    assert "token" in types


def test_deep_thinking_exception_fallback():
    """chat_stream_thinking 抛异常应走 _generate 非流式兜底"""
    gen = _Gen()
    llm = MagicMock()
    llm.chat_stream_thinking.side_effect = Exception("连接中断")
    llm.chat.return_value = "兜底答案"

    events = list(gen._generate_deep([{"role": "user", "content": "Q"}], llm))
    assert any(e[0] == "token" for e in events)
    assert events[-1] == ("token", {"content": "兜底答案"})


def test_generate_stream_normal_path():
    """非深度思考: 正常流式输出应产生 token 事件"""
    gen = _Gen()
    llm = MagicMock()
    # 输出长度 < STREAM_FLUSH_CHARS(80), 末尾 flush
    llm.chat_stream.return_value = iter(["短", "答", "案"])
    events = list(gen._generate_stream([{"role": "user", "content": "Q"}], llm))
    assert any(e[0] == "token" for e in events)


def test_generate_stream_leak_reset():
    """非深度思考流式途中检测到工具调用标记应 reset"""
    gen = _Gen()
    llm = MagicMock()
    leak = '{"name": "search_bidding_knowledge", "arguments": {}}'
    llm.chat_stream.return_value = iter([leak])
    llm.chat.return_value = "重试干净答案"

    events = list(gen._generate_stream([{"role": "user", "content": "Q"}], llm))
    assert any(e[0] == "reset" for e in events)
    assert any(e[0] == "token" for e in events)


def test_generate_retries_on_leak():
    """_generate 在返回工具调用标记时应重试 (chat 被调用 2 次)"""
    gen = _Gen()
    llm = MagicMock()
    llm.chat.side_effect = [
        '{"name": "search_bidding_knowledge", "arguments": {}}',  # 第1次泄露
        "干净答案",  # 第2次干净
    ]
    msgs = [{"role": "user", "content": "Q"}]
    out = gen._generate(msgs, llm, retries=3)
    assert out == "干净答案"
    # 泄露时应重试, chat 被调用 2 次
    assert llm.chat.call_count == 2


def test_generate_all_retries_exhausted():
    """3 次全部泄露, 应返回兜底错误信息"""
    gen = _Gen()
    llm = MagicMock()
    llm.chat.return_value = '{"name": "search_bidding_knowledge", "arguments": {}}'
    out = gen._generate([{"role": "user", "content": "Q"}], llm, retries=3)
    assert "技术问题" in out
