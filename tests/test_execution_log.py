"""Agent 执行结构化日志测试"""
import json
import os
import tempfile
from unittest.mock import patch
from src.agent.execution_log import (
    ExecutionLogger,
    _write_log,
    query_executions,
    get_stats,
    _LOG_FILE,
)


class TestExecutionLogger:
    def test_new_trace_id(self):
        log = ExecutionLogger()
        assert len(log.trace_id) == 12
        assert log.trace_id != ExecutionLogger().trace_id

    def test_set_context(self):
        log = ExecutionLogger()
        log.set_context("什么是公开招标？", "deepseek", True, False)
        assert log.question == "什么是公开招标？"
        assert log.provider == "deepseek"
        assert log.web_search is True
        assert log.deep_thinking is False

    def test_add_phase(self):
        log = ExecutionLogger()
        log.add_phase("首轮分析", 120)
        log.add_phase("检索与搜索", 300)
        assert len(log.phases) == 2
        assert log.phases[0] == {"name": "首轮分析", "ms": 120}
        assert log.phases[1] == {"name": "检索与搜索", "ms": 300}

    def test_add_tool_call(self):
        log = ExecutionLogger()
        log.add_tool_call(1, "search_bidding_knowledge", 5, "✅ 检索质量良好", 150)
        assert len(log.tool_calls) == 1
        tc = log.tool_calls[0]
        assert tc["round"] == 1
        assert tc["name"] == "search_bidding_knowledge"
        assert tc["sources_count"] == 5
        assert tc["ms"] == 150

    def test_set_result(self):
        log = ExecutionLogger()
        audit = {
            "faithfulness_score": 0.85,
            "total_sentences": 10,
            "hallucinated_count": 1,
            "cited_source_indices": [0, 1, 2],
        }
        log.set_result("这是回答内容", 3, 2, audit)
        assert log.answer_snippet == "这是回答内容"
        assert log.sources_count == 3
        assert log.web_sources_count == 2
        assert log.audit_summary["faithfulness_score"] == 0.85
        assert log.audit_summary["hallucinated_count"] == 1
        assert log.audit_summary["cited_sources"] == 3

    def test_set_status(self):
        log = ExecutionLogger()
        log.set_status("error", "LLM 超时")
        assert log.status == "error"
        assert log.error == "LLM 超时"

    def test_to_dict(self):
        log = ExecutionLogger()
        log.set_context("测试问题", "deepseek")
        log.add_phase("首轮分析", 100)
        log.set_status("ok")
        d = log.to_dict()
        assert "trace_id" in d
        assert d["question"] == "测试问题"
        assert d["provider"] == "deepseek"
        assert d["status"] == "ok"
        assert len(d["phases"]) == 1
        assert d["phases"][0]["name"] == "首轮分析"

    def test_finish_writes_jsonl(self, tmp_path):
        log_file = tmp_path / "test_exec.jsonl"
        log = ExecutionLogger()
        log.set_context("测试", "deepseek")
        log.add_phase("首轮分析", 50)
        log.set_status("ok")
        with patch("src.agent.execution_log._LOG_FILE", str(log_file)):
            log.finish()
        assert log_file.exists()
        line = log_file.read_text(encoding="utf-8").strip()
        rec = json.loads(line)
        assert rec["trace_id"] == log.trace_id
        assert rec["question"] == "测试"
        assert rec["status"] == "ok"
        assert rec["elapsed_ms"] >= 0


class TestQueryExecutions:
    def test_query_empty(self, tmp_path):
        with patch("src.agent.execution_log._LOG_FILE", str(tmp_path / "nonexist.jsonl")):
            results = query_executions()
        assert results == []

    def test_query_records(self, tmp_path):
        log_file = tmp_path / "exec.jsonl"
        with patch("src.agent.execution_log._LOG_FILE", str(log_file)):
            for i in range(5):
                log = ExecutionLogger()
                log.set_context(f"问题{i}", "deepseek")
                log.set_status("ok" if i < 3 else "error")
                log.finish()
            results = query_executions(limit=3)
        assert len(results) == 3
        # 从后往前, 最新在前
        assert results[0]["question"] == "问题4"

    def test_query_by_status(self, tmp_path):
        log_file = tmp_path / "exec.jsonl"
        with patch("src.agent.execution_log._LOG_FILE", str(log_file)):
            for i in range(4):
                log = ExecutionLogger()
                log.set_context(f"问题{i}", "deepseek")
                log.set_status("ok" if i < 2 else "error")
                log.finish()
            results = query_executions(limit=10, status="error")
        assert len(results) == 2
        assert all(r["status"] == "error" for r in results)

    def test_query_by_trace_id(self, tmp_path):
        log_file = tmp_path / "exec.jsonl"
        with patch("src.agent.execution_log._LOG_FILE", str(log_file)):
            log1 = ExecutionLogger()
            log1.set_context("问题1", "deepseek")
            log1.finish()
            log2 = ExecutionLogger()
            log2.set_context("问题2", "deepseek")
            log2.finish()
            results = query_executions(trace_id=log1.trace_id)
        assert len(results) == 1
        assert results[0]["trace_id"] == log1.trace_id
        assert results[0]["question"] == "问题1"


class TestGetStats:
    def test_stats_empty(self, tmp_path):
        with patch("src.agent.execution_log._LOG_FILE", str(tmp_path / "nonexist.jsonl")):
            stats = get_stats()
        assert stats["total"] == 0

    def test_stats_with_data(self, tmp_path):
        log_file = tmp_path / "exec.jsonl"
        with patch("src.agent.execution_log._LOG_FILE", str(log_file)):
            for i in range(5):
                log = ExecutionLogger()
                log.set_context(f"问题{i}", "deepseek")
                log.set_status("ok" if i < 3 else "error")
                log.add_tool_call(1, "search_bidding_knowledge", 3, "✅", 100)
                log.finish()
            stats = get_stats()
        assert stats["total"] == 5
        assert "ok" in stats["status_breakdown"]
        assert "error" in stats["status_breakdown"]
        assert stats["status_breakdown"]["ok"] == 3
        assert stats["status_breakdown"]["error"] == 2
        assert stats["avg_elapsed_ms"] >= 0
        assert len(stats["tool_call_top"]) >= 1
        assert stats["tool_call_top"][0][0] == "search_bidding_knowledge"
