from __future__ import annotations
"""_sse / _pace_stream_chunks / _truncate_history / _compress_history"""
import json
import time

from src.config import settings


def _sse(event_type: str, **kwargs) -> str:
    payload = {"type": event_type, **kwargs}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _pace_stream_chunks(text: str):
    for i in range(0, len(text), 40):
        yield text[i:i + 40]
        time.sleep(0.02)


def _compress_content(content: str, max_len: int) -> str:
    """压缩单条消息 content: 前 N 字 + ⋯ + 后 N 字, 保留结构不丢."""
    if not content or len(content) <= max_len:
        return content
    head = max(max_len // 2 - 10, 40)
    tail = max(max_len // 2 - 5, 30)
    return content[:head] + "\u22ef (已压缩) \u22ef" + content[-tail:]


def _count_rounds(history: list[dict]) -> int:
    """统计完整 user→assistant 轮次数 (只计 user 消息数)."""
    return sum(1 for m in history if m.get("role") == "user")


def _compress_history(history: list[dict], keep_recent_rounds: int = 5) -> list[dict]:
    """轻量压缩历史: 超过阈值的旧消息 content 截断, 保留结构.

    策略:
      - 不调 LLM, 纯字符串处理, 零额外成本
      - 最近 keep_recent_rounds * 2 条完整保留 (即将被截断的那部分)
      - 更早的消息: content 超过阈值则头+尾拼接, 保留 role/tool_calls 等关键字段
      - tool 消息 (role=tool) 的 content 同样截断
      - user 消息通常很短, 只截断超长的
    """
    if not settings.history_compress_enabled or not history:
        return list(history) if history else []

    total_rounds = _count_rounds(history)
    compress_after = settings.history_compress_after_rounds
    if total_rounds <= compress_after:
        # 对话还不长, 全部保留
        return list(history)

    # 需要压缩: 把第 1 轮 → 第 (total - keep_recent_rounds) 轮之间的旧消息压缩
    keep_count = keep_recent_rounds * 2
    if len(history) <= keep_count:
        return list(history)

    result: list[dict] = []
    # 前面需要压缩的部分
    for msg in history[:-keep_count]:
        new_msg = dict(msg)
        content = new_msg.get("content")
        if isinstance(content, str) and len(content) > settings.history_compressed_content_max:
            new_msg["content"] = _compress_content(content, settings.history_compressed_content_max)
        result.append(new_msg)

    # 后面保留的完整部分
    result.extend(dict(m) for m in history[-keep_count:])
    return result


def _truncate_history(history: list[dict] | None, max_rounds: int = 5) -> list[dict]:
    """先压缩旧消息, 再截断到最近 max_rounds 轮.

    原地压缩 → 截断, 单入口全局生效.
    """
    if not history:
        return []

    # 第一步: 压缩 (对整条 history 做)
    compressed = _compress_history(history, keep_recent_rounds=max_rounds)

    # 第二步: 截断
    keep = max_rounds * 2
    if len(compressed) <= keep:
        return compressed
    truncated = compressed[-keep:]
    # 如果截断后第一条是 assistant, 说明配对被打断, 往前补一条 user
    if truncated and truncated[0].get("role") == "assistant" and len(compressed) > keep:
        truncated.insert(0, compressed[-keep - 1])
    return truncated
