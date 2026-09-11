import json

from src.agent.utils import _sse
from src.agent.core import BiddingAgent


def test_sse_frame_format():
    frame = _sse("token", content="你好")
    assert frame.startswith("data: ")
    assert frame.endswith("\n\n")
    payload = json.loads(frame[6:].strip())
    assert payload == {"type": "token", "content": "你好"}


def test_sse_ensure_ascii_false():
    frame = _sse("status", content="正在检索")
    assert "正在检索" in frame


def test_chat_collects_tokens(monkeypatch):
    agent = BiddingAgent()
    agent._ready = True

    def fake_events(*a, **kw):
        yield ("token", {"content": "你"})
        yield ("token", {"content": "好"})
        yield ("done", {"sources": [{"question": "q", "answer": "a"}],
                        "web_sources": [], "tool_called": True,
                        "tool_name": "search_web"})

    monkeypatch.setattr(agent, "_chat_events", fake_events)
    result = agent.chat("问题")
    assert result["answer"] == "你好"
    assert result["tool_name"] == "search_web"
