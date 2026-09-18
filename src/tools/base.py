from __future__ import annotations
"""BaseTool + ToolRunner (并行/超时/异常隔离)"""
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context
from dataclasses import dataclass, field

from pydantic import BaseModel

logger = logging.getLogger(__name__)

TOOL_TIMEOUT_SECONDS = 30
# 个别工具单次耗时较长, 按工具名放宽
TOOL_TIMEOUT_OVERRIDES = {
    "generate_bid_draft": 180,
    # 混合检索含稀疏+稠密+rerank, LLM 并行发起多个时 30s 容易误杀
    "search_bidding_knowledge": 90,
}


class BaseTool(BaseModel):
    name: str
    description: str
    parameters: dict

    def to_openai_schema(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description,
            "parameters": self.parameters}}


@dataclass
class ToolResult:
    text: str
    sources: list = field(default_factory=list)
    name: str = ""


class ToolRunner:
    @staticmethod
    def run_parallel(tool_calls, question: str, executors: dict) -> list[ToolResult]:
        results: list[ToolResult] = []
        pending = {}

        def _run_one(call):
            name = call.function.name
            if name not in executors:
                return ToolResult(text=f"未知工具: {name}", name=name)
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                return ToolResult(text=f"参数解析失败: {call.function.arguments}", name=name)
            try:
                text, sources = executors[name](args, question)
                return ToolResult(text=text, sources=sources or [], name=name)
            except Exception as e:
                logger.warning("工具 %s 执行失败: %s", name, e)
                return ToolResult(text=f"执行失败: {e}", name=name)

        with ThreadPoolExecutor(max_workers=4) as pool:
            # 本轮调用中若有放宽超时的工具, 取最大值作为整轮等待上限
            call_names = {getattr(c.function, "name", "") for c in tool_calls}
            wait_timeout = max(
                [TOOL_TIMEOUT_SECONDS] +
                [v for n, v in TOOL_TIMEOUT_OVERRIDES.items() if n in call_names])
            # 每个调用复制独立上下文: Context 同一时刻只能被一个线程进入,
            # 并行工具调用不能共用同一个 Context 副本。
            # 传播 use_access_scope 设置的 ContextVar (当前用户/行级范围)
            for call in tool_calls:
                pending[pool.submit(copy_context().run, _run_one, call)] = call
            try:
                for fut in as_completed(pending, timeout=wait_timeout):
                    results.append(fut.result())
            except TimeoutError:
                for fut in pending:
                    if not fut.done():
                        results.append(ToolResult(
                            text=f"执行超时(>{wait_timeout}秒)",
                            name=pending[fut].function.name))
            finally:
                pool.shutdown(wait=False, cancel_futures=True)
        return results
