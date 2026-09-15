"""DeepSeekClient: chat/chat_stream/chat_raw/思考模型属性"""
import os
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from unittest.mock import MagicMock, patch

from src.clients.deepseek_client import DeepSeekClient


def _mk_chunk(content=None, reasoning=None):
    delta = MagicMock()
    delta.content = content
    delta.reasoning_content = reasoning
    choice = MagicMock()
    choice.delta = delta
    chunk = MagicMock()
    chunk.choices = [choice]
    return chunk


def _mk_chat_resp(content=None, reasoning=None):
    msg = MagicMock()
    msg.content = content
    msg.reasoning_content = reasoning
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def test_provider_and_model_default():
    """provider=deepseek, model 取 settings.deepseek_model"""
    with patch("src.clients.deepseek_client.OpenAI"):
        c = DeepSeekClient()
        assert c.provider == "deepseek"
        assert c.model_name  # 非空


def test_chat_prefers_content():
    with patch("src.clients.deepseek_client.OpenAI") as mock_oa:
        c = DeepSeekClient()
        c._client = MagicMock()
        c._client.chat.completions.create.return_value = _mk_chat_resp(content="A")
        assert c.chat([]) == "A"


def test_chat_fallback_to_reasoning():
    """content 为空时应回退取 reasoning_content"""
    with patch("src.clients.deepseek_client.OpenAI"):
        c = DeepSeekClient()
        c._client = MagicMock()
        c._client.chat.completions.create.return_value = _mk_chat_resp(content=None, reasoning="R")
        assert c.chat([]) == "R"


def test_chat_stream_yields_content():
    with patch("src.clients.deepseek_client.OpenAI"):
        c = DeepSeekClient()
        c._client = MagicMock()
        c._client.chat.completions.create.return_value = iter([
            _mk_chunk(content="A"),
            _mk_chunk(content="B"),
        ])
        out = list(c.chat_stream([]))
        assert "".join(out) == "AB"


def test_chat_stream_reasoning_only_fallback():
    """纯 reasoning 无 content, 末尾 yield 累积的 reasoning"""
    with patch("src.clients.deepseek_client.OpenAI"):
        c = DeepSeekClient()
        c._client = MagicMock()
        c._client.chat.completions.create.return_value = iter([
            _mk_chunk(content=None, reasoning="R"),
        ])
        out = list(c.chat_stream([]))
        assert out == ["R"]


def test_chat_stream_thinking_tags():
    """chat_stream_thinking 应产出 ("thinking", ...) / ("content", ...) 元组"""
    with patch("src.clients.deepseek_client.OpenAI"):
        c = DeepSeekClient()
        c._client = MagicMock()
        c._client.chat.completions.create.return_value = iter([
            _mk_chunk(content=None, reasoning="思"),
            _mk_chunk(content="答"),
        ])
        out = list(c.chat_stream_thinking([]))
        assert out == [("thinking", "思"), ("content", "答")]


def test_chat_raw_with_tools():
    """chat_raw 带 tools 应设置 tool_choice"""
    with patch("src.clients.deepseek_client.OpenAI"):
        c = DeepSeekClient()
        c._client = MagicMock()
        c._client.chat.completions.create.return_value = _mk_chat_resp(content="ok")
        c.chat_raw([], tools=[{"type": "function"}])
        call = c._client.chat.completions.create.call_args
        assert call.kwargs.get("tool_choice") == "auto"


def test_chat_raw_no_tools():
    """chat_raw 不带 tools 不应出现 tool_choice"""
    with patch("src.clients.deepseek_client.OpenAI"):
        c = DeepSeekClient()
        c._client = MagicMock()
        c._client.chat.completions.create.return_value = _mk_chat_resp(content="ok")
        c.chat_raw([])
        call = c._client.chat.completions.create.call_args
        assert "tool_choice" not in call.kwargs
