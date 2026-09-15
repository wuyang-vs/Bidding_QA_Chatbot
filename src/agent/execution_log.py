from __future__ import annotations
"""Agent 执行结构化日志 — JSONL 格式持久化, 支持查询和回溯.

每条记录包含:
  trace_id        - 唯一追踪 ID
  timestamp       - ISO 格式时间戳
  question        - 用户问题
  provider        - LLM provider
  web_search      - 是否启用联网搜索
  deep_thinking   - 是否深度思考
  phases          - 各阶段耗时 [{name, ms}]
  tool_calls      - 工具调用记录 [{round, name, sources_count, quality_tag, ms}]
  total_rounds    - ReAct 循环总轮数
  answer_snippet   - 回答摘要 (前 200 字)
  sources_count    - RAG 来源数
  web_sources_count - 联网来源数
  audit            - 审计结果摘要
  elapsed_ms       - 总耗时
  status           - ok / error / out_of_scope / vague
  error            - 错误信息 (status=error 时)
"""
import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone

_LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
_LOG_FILE = os.path.join(_LOG_DIR, "agent_executions.jsonl")
_LOCK = threading.Lock()
_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB 自动轮转


def _ensure_log_dir() -> None:
    os.makedirs(_LOG_DIR, exist_ok=True)


def _new_trace_id() -> str:
    return uuid.uuid4().hex[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ExecutionLogger:
    """单次 Agent 执行的上下文记录器."""

    def __init__(self):
        self.trace_id = _new_trace_id()
        self.start_time = time.time()
        self.timestamp = _now_iso()
        self.question = ""
        self.provider = ""
        self.web_search = False
        self.deep_thinking = False
        self.phases: list[dict] = []
        self.tool_calls: list[dict] = []
        self.total_rounds = 0
        self.answer_snippet = ""
        self.sources_count = 0
        self.web_sources_count = 0
        self.audit_summary: dict = {}
        self.elapsed_ms = 0
        self.status = "ok"
        self.error = ""

    def set_context(self, question: str, provider: str = "",
                    web_search: bool = False, deep_thinking: bool = False) -> None:
        self.question = question[:500]
        self.provider = provider
        self.web_search = web_search
        self.deep_thinking = deep_thinking

    def add_phase(self, name: str, ms: int) -> None:
        self.phases.append({"name": name, "ms": ms})

    def add_tool_call(self, round: int, name: str, sources_count: int,
                      quality_tag: str, ms: int) -> None:
        self.tool_calls.append({
            "round": round,
            "name": name,
            "sources_count": sources_count,
            "quality_tag": quality_tag[:60],
            "ms": ms,
        })

    def set_result(self, answer: str, sources_count: int,
                   web_sources_count: int, audit: dict = None) -> None:
        self.answer_snippet = answer[:200]
        self.sources_count = sources_count
        self.web_sources_count = web_sources_count
        if audit:
            self.audit_summary = {
                "faithfulness_score": audit.get("faithfulness_score", 0),
                "total_sentences": audit.get("total_sentences", 0),
                "hallucinated_count": audit.get("hallucinated_count", 0),
                "cited_sources": len(audit.get("cited_source_indices", [])),
            }

    def set_status(self, status: str, error: str = "") -> None:
        self.status = status
        if error:
            self.error = error[:500]

    def finish(self) -> None:
        self.elapsed_ms = int((time.time() - self.start_time) * 1000)
        _write_log(self.to_dict())

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "timestamp": self.timestamp,
            "question": self.question,
            "provider": self.provider,
            "web_search": self.web_search,
            "deep_thinking": self.deep_thinking,
            "phases": self.phases,
            "tool_calls": self.tool_calls,
            "total_rounds": self.total_rounds,
            "answer_snippet": self.answer_snippet,
            "sources_count": self.sources_count,
            "web_sources_count": self.web_sources_count,
            "audit": self.audit_summary,
            "elapsed_ms": self.elapsed_ms,
            "status": self.status,
            "error": self.error,
        }


def _write_log(record: dict) -> None:
    """写入 JSONL, 带文件大小轮转."""
    _ensure_log_dir()
    with _LOCK:
        # 检查文件大小, 超限则轮转
        if os.path.exists(_LOG_FILE) and os.path.getsize(_LOG_FILE) > _MAX_FILE_SIZE:
            rotated = _LOG_FILE.replace(".jsonl", f".{int(time.time())}.jsonl")
            try:
                os.rename(_LOG_FILE, rotated)
            except OSError:
                pass
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def query_executions(limit: int = 20, status: str = "",
                     trace_id: str = "") -> list[dict]:
    """查询最近的 Agent 执行记录."""
    if not os.path.exists(_LOG_FILE):
        return []
    results = []
    with _LOCK:
        with open(_LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    # 从后往前读, 取最近 limit 条
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if trace_id and rec.get("trace_id") != trace_id:
            continue
        if status and rec.get("status") != status:
            continue
        results.append(rec)
        if len(results) >= limit:
            break
    return results


def get_stats() -> dict:
    """汇总统计: 总请求数/各状态数/平均耗时/工具调用 TOP."""
    records = query_executions(limit=1000)
    if not records:
        return {"total": 0}
    from collections import Counter
    status_counts = Counter(r.get("status", "unknown") for r in records)
    elapsed_list = [r.get("elapsed_ms", 0) for r in records if r.get("elapsed_ms", 0) > 0]
    avg_elapsed = sum(elapsed_list) / len(elapsed_list) if elapsed_list else 0
    tool_counter: Counter = Counter()
    for r in records:
        for tc in r.get("tool_calls", []):
            tool_counter[tc.get("name", "unknown")] += 1
    return {
        "total": len(records),
        "status_breakdown": dict(status_counts),
        "avg_elapsed_ms": round(avg_elapsed),
        "tool_call_top": tool_counter.most_common(5),
        "log_file": _LOG_FILE,
    }
