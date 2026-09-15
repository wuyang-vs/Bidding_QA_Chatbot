"""ReAct 多轮工具循环 + _clean_for_final + 来源合并/质量标签"""
import logging
import time

from src.agent.constants import MAX_TOOL_ROUNDS
from src.agent.tool_defense import (
    _looks_like_tool_call, _normalize_tool_content,
    _parse_text_tool_calls, to_fake_tool_calls,
)
from src.tools.base import ToolRunner
from src.tools.rag_tools import TOOL_EXECUTORS

logger = logging.getLogger(__name__)

_CAP_CONSTRAINT_TEXT = ("已达到工具调用轮次上限。必须立即基于以上所有工具结果直接回答，"
                        "禁止再调用任何工具。")


class ReActMixin:
    def _chat_stream_tools(self, messages, question, llm, active_tools, web_search_enabled):
        tool_msgs_start = len(messages)
        all_sources, web_sources, last_tool = [], [], ""
        answer = ""
        phase_times = []
        t0 = time.time()
        t_first = None
        t_tools = None

        for round_idx in range(1, MAX_TOOL_ROUNDS + 1):
            if round_idx > 1:
                yield ("status", {"content": "正在分析检索结果..."})
            try:
                response = llm.chat_raw(messages, tools=active_tools)
            except Exception as e:
                logger.error("LLM 调用失败: %s", e)
                if round_idx == 1:
                    yield from self._fallback_rag(question, llm, messages)
                    return
                messages.append({"role": "user", "content": _CAP_CONSTRAINT_TEXT})
                break

            if t_first is None:
                t_first = time.time()
                phase_times.append(("首轮分析", int((t_first - t0) * 1000)))

            choice = response.choices[0]
            msg = choice.message
            tool_calls = getattr(msg, "tool_calls", None)

            if tool_calls:
                content = _normalize_tool_content(getattr(msg, "content", "") or "")
                messages.append({"role": "assistant", "content": content,
                                 "tool_calls": [tc.model_dump() if hasattr(tc, "model_dump") else tc
                                                for tc in tool_calls]})
                status = "正在检索与搜索..." if round_idx == 1 else f"正在补充检索（第{round_idx}轮）..."
                yield ("status", {"content": status})
                results = ToolRunner.run_parallel(tool_calls, question, TOOL_EXECUTORS)
                for tc, r in zip(tool_calls, results):
                    text = self._validate_result(r.name, r.text, r.sources)
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": text})
                    if r.name in ("search_web", "search_exa"):
                        web_sources.extend(r.sources)
                    else:
                        all_sources.extend(r.sources)
                    last_tool = r.name
                t_tools = time.time()
                continue

            raw = getattr(msg, "content", "") or getattr(msg, "reasoning_content", "") or ""
            parsed = _parse_text_tool_calls(raw)
            if parsed:
                valid = [c for c in parsed if c["name"] in TOOL_EXECUTORS]
                if valid:
                    fake = to_fake_tool_calls(valid)
                    results = ToolRunner.run_parallel(fake, question, TOOL_EXECUTORS)
                    for r in results:
                        messages.append({"role": "user",
                                         "content": f"工具 {r.name} 返回：\n{r.text}\n\n请判断信息是否足够，足够则直接回答。"})
                        if r.name in ("search_web", "search_exa"):
                            web_sources.extend(r.sources)
                        else:
                            all_sources.extend(r.sources)
                        last_tool = r.name
                    continue

            if raw and not _looks_like_tool_call(raw):
                answer = raw
                break
            messages.append({"role": "user", "content": _CAP_CONSTRAINT_TEXT})
            break
        else:
            messages.append({"role": "user", "content": _CAP_CONSTRAINT_TEXT})

        if t_tools:
            phase_times.append(("检索与搜索", int((t_tools - t_first) * 1000)))

        if answer:
            from src.agent.utils import _pace_stream_chunks
            # LLM 直接给了答案, 但如果调过工具且工具全空, 追加诚实约束
            if last_tool and not all_sources and not web_sources:
                answer = ("【注意: 所有检索工具均未返回有效结果, "
                          "以下回答可能缺乏依据, 请谨慎参考】\n\n") + answer
            for chunk in _pace_stream_chunks(answer):
                yield ("token", {"content": chunk})
            yield ("done", {"sources": self._merge_sources(all_sources),
                            "web_sources": self._merge_sources(web_sources),
                            "tool_called": bool(last_tool), "tool_name": last_tool,
                            "phase_times": phase_times})
            return

        final_messages = self._clean_for_final(messages, question, tool_msgs_start)

        # 所有工具返回空 → 注入诚实约束, 禁止编造
        if last_tool and not all_sources and not web_sources:
            final_messages.append({
                "role": "system",
                "content": ("所有检索工具均未返回有效结果。"
                            "你必须明确告知用户「未找到相关信息」，"
                            "绝对不能编造、猜测或凭常识回答。")
            })

        yield ("status", {"content": "正在生成回答..."})
        t_gen = time.time()
        yield from self._generate_stream(final_messages, llm)
        phase_times.append(("生成回答", int((time.time() - t_gen) * 1000)))
        yield ("done", {"sources": self._merge_sources(all_sources),
                        "web_sources": self._merge_sources(web_sources),
                        "tool_called": bool(last_tool), "tool_name": last_tool,
                        "phase_times": phase_times})

    @staticmethod
    def _merge_sources(sources: list[dict]) -> list[dict]:
        seen, out = set(), []
        for s in sources:
            key = (s.get("question", ""), s.get("answer", ""))
            if key not in seen:
                seen.add(key)
                out.append(s)
        return out

    @staticmethod
    def _validate_result(name: str, text: str, sources: list) -> str:
        has_data = bool(text) and not any(k in text for k in ("未找到", "未返回", "失败"))
        tag = ""
        if name == "search_bidding_knowledge":
            if not sources:
                tag = "⚠️ 未检索到相关文档"
            else:
                avg = sum(s.get("score", 0) for s in sources) / len(sources)
                tag = "✅ 检索质量良好" if avg >= 0.5 else f"⚠️ 相关性偏低（{len(sources)}条，均分{avg:.2f}）"
        elif name in ("search_knowledge_graph", "search_postgresql", "search_web", "search_exa"):
            if not has_data:
                tag = "⚠️ 工具返回空结果"
        return f"{tag}\n{text}" if tag else text

    @staticmethod
    def _clean_for_final(messages, question, tool_msgs_start):
        system = messages[0]
        tail = messages[tool_msgs_start:]
        rebuilt = [system, {"role": "user", "content": question}]
        for m in tail:
            if isinstance(m, dict):
                rebuilt.append(m)
        rebuilt.append({"role": "system", "content":
                        "只能使用上面工具返回的检索结果，禁止编造。只输出纯文本回答。"})
        return rebuilt
