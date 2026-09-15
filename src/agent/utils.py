from __future__ import annotations
"""_sse / _pace_stream_chunks / _truncate_history"""
import json
import time


def _sse(event_type: str, **kwargs) -> str:
    payload = {"type": event_type, **kwargs}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _pace_stream_chunks(text: str):
    for i in range(0, len(text), 40):
        yield text[i:i + 40]
        time.sleep(0.02)


def _truncate_history(history: list[dict] | None, max_rounds: int = 5) -> list[dict]:
    if not history:
        return []
    keep = max_rounds * 2
    if len(history) <= keep:
        return list(history)
    truncated = list(history[-keep:])
    if truncated and truncated[0].get("role") == "assistant" and len(history) > keep:
        truncated.insert(0, history[-keep - 1])
    return truncated
