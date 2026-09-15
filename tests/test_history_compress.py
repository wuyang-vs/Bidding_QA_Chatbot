"""对话历史压缩测试 — 覆盖 _compress_content / _compress_history / _truncate_history."""
from __future__ import annotations

import pytest

from src.agent.utils import _compress_content, _compress_history, _truncate_history


def _make_history(num_rounds: int, content_len: int = 500) -> list[dict]:
    """构造 num_rounds 轮 user→assistant 对, content 固定长度的重复字符串."""
    long_answer = "招投标采购相关内容。" + "A" * (content_len - 20)
    hist: list[dict] = []
    for i in range(1, num_rounds + 1):
        hist.append({"role": "user", "content": f"问题{i}: 什么是单一来源采购？"})
        hist.append({"role": "assistant", "content": f"回答{i}: {long_answer[:content_len]}"})
    return hist


class TestCompressContent:
    def test_short_content_unchanged(self):
        text = "短文本不压缩"
        assert _compress_content(text, 300) == text

    def test_long_content_truncated(self):
        text = "开头" + "X" * 500 + "结尾"
        result = _compress_content(text, 300)
        assert len(result) < len(text)
        assert "已压缩" in result
        assert result.startswith("开头")
        assert result.endswith("结尾")

    def test_empty_string(self):
        assert _compress_content("", 100) == ""

    def test_exact_boundary(self):
        text = "A" * 300
        assert _compress_content(text, 300) == text  # 刚好等于, 不压


class TestCompressHistory:
    def test_disabled_passthrough(self, monkeypatch):
        import src.agent.utils as u
        monkeypatch.setattr(u.settings, "history_compress_enabled", False)
        hist = _make_history(20)
        result = _compress_history(hist)
        # 不压缩, 条数不变
        assert len(result) == len(hist)
        # 内容也不变
        for orig, compressed in zip(hist, result):
            assert orig["content"] == compressed["content"]

    def test_below_threshold_no_compress(self, monkeypatch):
        """对话轮数低于 compress_after_rounds, 全部保留原样."""
        import src.agent.utils as u
        monkeypatch.setattr(u.settings, "history_compress_enabled", True)
        monkeypatch.setattr(u.settings, "history_compress_after_rounds", 20)
        monkeypatch.setattr(u.settings, "history_compressed_content_max", 100)

        hist = _make_history(5, content_len=500)
        result = _compress_history(hist, keep_recent_rounds=5)
        # 5 轮 < 20 阈值, 全部完整保留
        for orig, compressed in zip(hist, result):
            assert orig["content"] == compressed["content"]

    def test_old_messages_compressed_recent_kept(self, monkeypatch):
        """超过阈值的旧消息被压缩, 最近几轮完整."""
        import src.agent.utils as u
        monkeypatch.setattr(u.settings, "history_compress_enabled", True)
        monkeypatch.setattr(u.settings, "history_compress_after_rounds", 5)
        monkeypatch.setattr(u.settings, "history_compressed_content_max", 100)

        hist = _make_history(15, content_len=500)  # 15 轮, 超过 5 轮阈值
        # keep_recent_rounds=5 → 最后 10 条完整
        result = _compress_history(hist, keep_recent_rounds=5)

        assert len(result) == len(hist)  # 条数不变

        # 前 20 条 (10 轮) 应该被压缩
        for msg in result[:-10]:
            content = msg["content"]
            if msg["role"] == "assistant":  # 只有 assistant 有长内容
                assert "已压缩" in content or len(content) <= 100

        # 最后 10 条 (5 轮) 完整保留
        for msg in result[-10:]:
            orig_content = hist[hist.index(msg)]["content"] if msg in hist else None
            # 直接比较内容长度
            result_idx = result.index(msg)
            assert len(msg["content"]) == len(hist[result_idx]["content"])

    def test_compress_preserves_role_and_structure(self, monkeypatch):
        """压缩后 role 不变, 消息条数不变, 无丢失."""
        import src.agent.utils as u
        monkeypatch.setattr(u.settings, "history_compress_enabled", True)
        monkeypatch.setattr(u.settings, "history_compress_after_rounds", 3)
        monkeypatch.setattr(u.settings, "history_compressed_content_max", 100)

        hist = _make_history(10)
        result = _compress_history(hist, keep_recent_rounds=5)

        assert len(result) == len(hist)
        for orig, compressed in zip(hist, result):
            assert orig["role"] == compressed["role"]

    def test_none_history(self):
        assert _compress_history(None) == []

    def test_empty_history(self):
        assert _compress_history([]) == []


class TestTruncateHistory:
    def test_combination_compress_then_truncate(self, monkeypatch):
        """完整 20 轮: 先压缩前 15 轮, 再截断保留最后 5 轮."""
        import src.agent.utils as u
        monkeypatch.setattr(u.settings, "history_compress_enabled", True)
        monkeypatch.setattr(u.settings, "history_compress_after_rounds", 5)
        monkeypatch.setattr(u.settings, "history_compressed_content_max", 100)

        hist = _make_history(20, content_len=500)
        result = _truncate_history(hist, max_rounds=5)

        # 截断后最多 10 条 (5 轮)
        assert len(result) <= 11  # +1 可能的配对补齐

        # 全部 role 交替正确
        roles = [m["role"] for m in result]
        for i in range(len(roles) - 1):
            assert roles[i] != roles[i + 1]

    def test_disabled_compress_truncate_only(self, monkeypatch):
        """压缩关闭时, 退化为纯截断 (原有行为)."""
        import src.agent.utils as u
        monkeypatch.setattr(u.settings, "history_compress_enabled", False)

        hist = _make_history(20, content_len=1000)
        result = _truncate_history(hist, max_rounds=5)

        assert len(result) <= 11
        # 内容完整 (没有压缩标记)
        for msg in result:
            assert "已压缩" not in msg["content"]

    def test_short_history_no_truncate_needed(self):
        hist = _make_history(2)
        result = _truncate_history(hist, max_rounds=5)
        assert len(result) == 4

    def test_none_history(self):
        assert _truncate_history(None) == []

    def test_empty_history(self):
        assert _truncate_history([]) == []

    def test_truncate_preserves_role_structure(self, monkeypatch):
        """截断后第一条若为 assistant, 自动往前补 user."""
        import src.agent.utils as u
        monkeypatch.setattr(u.settings, "history_compress_enabled", False)

        hist = _make_history(10)  # 20 条
        result = _truncate_history(hist, max_rounds=3)
        # 截断后第一条应是 user (不会是 assistant 单独开头)
        assert result[0]["role"] == "user"
