from __future__ import annotations
"""BaseTool + ToolRunner (并行/超时/异常隔离)"""
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from pydantic import BaseModel

logger = logging.getLogger(__name__)

TOOL_TIMEOUT_SECONDS = 30


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
            for call in tool_calls:
                pending[pool.submit(_run_one, call)] = call
            try:
                for fut in as_completed(pending, timeout=TOOL_TIMEOUT_SECONDS):
                    results.append(fut.result())
            except TimeoutError:
                for fut in pending:
                    if not fut.done():
                        results.append(ToolResult(
                            text=f"执行超时(>{TOOL_TIMEOUT_SECONDS}秒)",
                            name=pending[fut].function.name))
            finally:
                pool.shutdown(wait=False, cancel_futures=True)
        return results
