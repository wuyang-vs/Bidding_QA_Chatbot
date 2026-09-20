from __future__ import annotations
"""ReAct 多轮工具循环 + _clean_for_final + 来源合并/质量标签"""
import logging
import time

from src.agent.audit import audit_answer, build_citation_prompt_suffix
from src.agent.constants import MAX_TOOL_ROUNDS
from src.agent.evidence_gate import (
    NO_EVIDENCE_NOTICE, gate_decision, tool_provided_evidence,
)
from src.agent.tool_defense import (
    _looks_like_tool_call, _normalize_tool_content,
    _parse_text_tool_calls, to_fake_tool_calls,
)
from src.tools.base import ToolRunner
from src.tools.rag_tools import TOOL_EXECUTORS

logger = logging.getLogger(__name__)

_CAP_CONSTRAINT_TEXT = ("已达到工具调用轮次上限。必须立即基于以上所有工具结果直接回答，"
                        "禁止再调用任何工具。")

# 硬闸门: LLM 未取证直接作答时, 服务端强制其补一次检索
_FORCE_RETRIEVAL_TEXT = (
    "【服务端强制要求】你尚未调用任何检索工具，不得凭记忆或常识回答上述问题。"
    "请立即调用 search_bidding_knowledge 检索（必要时再用 search_postgresql / "
    "search_knowledge_graph 核实），拿到工具结果后再作答；若所有工具均返回空，"
    "再明确告知用户未检索到相关内容。"
)

# 复杂多跳问题特征词: 对比/枚举/跨域类问题首检易漏证据, 触发一次 query 改写重试
_COMPLEX_MULTI_HOP_WORDS = (
    "对比", "比较", "区别", "不同", "差异", "分别", "各自", "哪些",
    "和", "与", "及", "以及", "还是", "或者",
)


def _is_complex_multi_hop(question: str) -> bool:
    q = question or ""
    if len(q) < 12:
        return False
    hits = sum(1 for w in _COMPLEX_MULTI_HOP_WORDS if w in q)
    # 至少命中 1 个特征词且问题有一定长度, 或命中 2 个以上
    return hits >= 2 or (hits >= 1 and len(q) >= 20)


# 复杂多跳问题首检 gated 后的 query 改写重试提示
_COMPLEX_RETRY_TEXT = (
    "【服务端提示】上一轮检索未命中权威证据。该问题涉及多实体对比/跨域信息，"
    "请将问题拆成 2-3 个更具体的子问题，分别调用 search_bidding_knowledge / "
    "search_knowledge_graph / search_postgresql 检索后再综合作答；"
    "若仍无结果，再如实告知用户。"
)


class ReActMixin:
    def _chat_stream_tools(self, messages, question, llm, active_tools, web_search_enabled, exec_log=None):
        tool_msgs_start = len(messages)
        all_sources, web_sources, last_tool = [], [], ""
        answer = ""
        phase_times = []
        t0 = time.time()
        t_first = None
        t_tools = None
        # ---- 硬闸门证据跟踪 ----
        from src.config import settings
        gate_enabled = settings.evidence_gate_enabled
        tool_attempted = False       # 是否真实执行过任一证据工具
        evidence_found = False       # 是否拿到过实质证据(分片/来源/结构化数据)
        evidence_texts: list[str] = []  # 证据原文(用于问题特征词覆盖校验)
        forced_retry_used = False    # 已强制补检索一次
        complex_retry_used = False   # 复杂多跳问题已 query 改写重试一次

        for round_idx in range(1, MAX_TOOL_ROUNDS + 1):
            if exec_log:
                exec_log.total_rounds = round_idx
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
                if exec_log:
                    exec_log.add_phase("首轮分析", int((t_first - t0) * 1000))

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
                t_tool_start = time.time()
                results = ToolRunner.run_parallel(tool_calls, question, TOOL_EXECUTORS)
                t_tool_end = time.time()
                for tc, r in zip(tool_calls, results):
                    text = self._validate_result(r.name, r.text, r.sources)
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": text})
                    if r.name in ("search_web", "search_exa"):
                        web_sources.extend(r.sources)
                    else:
                        all_sources.extend(r.sources)
                    last_tool = r.name
                    if gate_enabled and r.name in TOOL_EXECUTORS:
                        tool_attempted = True
                        if tool_provided_evidence(r.name, r.sources, r.text):
                            evidence_found = True
                            evidence_texts.append(r.text or "")
                    if exec_log:
                        exec_log.add_tool_call(
                            round_idx, r.name, len(r.sources), text[:60],
                            int((t_tool_end - t_tool_start) * 1000))
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
                        if gate_enabled and r.name in TOOL_EXECUTORS:
                            tool_attempted = True
                            if tool_provided_evidence(r.name, r.sources, r.text):
                                evidence_found = True
                                evidence_texts.append(r.text or "")
                    continue

            if raw and not _looks_like_tool_call(raw):
                if gate_enabled:
                    decision = gate_decision(
                        question, tool_attempted, evidence_found, forced_retry_used,
                        evidence_texts=evidence_texts)
                    if decision == "force_retrieval":
                        # M2-01 类波动: LLM 未取证就作答 → 丢弃答案, 强制补检索一次
                        forced_retry_used = True
                        logger.info("硬闸门: LLM 未调用检索工具直接作答, 强制补检索")
                        yield ("status", {"content": "正在强制调用知识库核实..."})
                        messages.append({"role": "assistant",
                                         "content": _normalize_tool_content(raw) or "我需要先核实资料。"})
                        messages.append({"role": "user", "content": _FORCE_RETRIEVAL_TEXT})
                        continue
                    if decision == "refuse":
                        # 无权威证据 → 丢弃无据答案, 走固定话术硬拒
                        logger.info("硬闸门: 无证据作答被拦截, 返回固定话术")
                        answer = ""
                        break
                answer = raw
                break
            messages.append({"role": "user", "content": _CAP_CONSTRAINT_TEXT})
            break
        else:
            messages.append({"role": "user", "content": _CAP_CONSTRAINT_TEXT})

        if t_tools:
            phase_times.append(("检索与搜索", int((t_tools - t_first) * 1000)))
            if exec_log:
                exec_log.add_phase("检索与搜索", int((t_tools - t_first) * 1000))

        if answer:
            from src.agent.utils import _pace_stream_chunks
            # 硬闸门开启时, 能走到这里说明有证据或属寒暄, 不再加"缺乏依据"软警告;
            # 闸门关闭时保留旧的软约束行为
            if (not gate_enabled) and last_tool and not all_sources and not web_sources:
                answer = ("【注意: 所有检索工具均未返回有效结果, "
                          "以下回答可能缺乏依据, 请谨慎参考】\n\n") + answer
            # 审计
            merged = self._merge_sources(all_sources)
            audit = audit_answer(answer, merged)
            for chunk in _pace_stream_chunks(answer):
                yield ("token", {"content": chunk})
            yield ("done", {"sources": merged,
                            "web_sources": self._merge_sources(web_sources),
                            "tool_called": bool(last_tool), "tool_name": last_tool,
                            "phase_times": phase_times,
                            "audit": audit, "gated": False,
                            "answer": answer})
            return

        # ---- 硬闸门: answer 为空且仍无权威证据 → 固定话术, 不调用 LLM 生成 ----
        if gate_enabled and gate_decision(
                question, tool_attempted, evidence_found,
                forced_retry_used, evidence_texts=evidence_texts) == "refuse":
            # 复杂多跳问题首检易漏证据: 允许一次 query 改写重试 (仅一次, 不无限循环)
            if (not complex_retry_used) and _is_complex_multi_hop(question):
                complex_retry_used = True
                logger.info("硬闸门: 复杂多跳问题首检无证据, 触发 query 改写重试")
                yield ("status", {"content": "正在拆分问题重新检索..."})
                messages.append({"role": "user", "content": _COMPLEX_RETRY_TEXT})
                try:
                    retry_resp = llm.chat_raw(messages, tools=active_tools)
                    retry_msg = retry_resp.choices[0].message
                    retry_tc = getattr(retry_msg, "tool_calls", None)
                    if retry_tc:
                        retry_content = _normalize_tool_content(
                            getattr(retry_msg, "content", "") or "")
                        messages.append({"role": "assistant", "content": retry_content,
                                         "tool_calls": [tc.model_dump() if hasattr(tc, "model_dump") else tc
                                                        for tc in retry_tc]})
                        retry_results = ToolRunner.run_parallel(
                            retry_tc, question, TOOL_EXECUTORS)
                        for tc, r in zip(retry_tc, retry_results):
                            text = self._validate_result(r.name, r.text, r.sources)
                            messages.append({"role": "tool", "tool_call_id": tc.id,
                                             "content": text})
                            if r.name in ("search_web", "search_exa"):
                                if r.sources:
                                    web_sources.extend(r.sources)
                            else:
                                if r.sources:
                                    all_sources.extend(r.sources)
                            last_tool = r.name
                            tool_attempted = True
                            if tool_provided_evidence(r.name, r.sources, r.text):
                                evidence_found = True
                                evidence_texts.append(r.text or "")
                except Exception as e:
                    logger.warning("复杂多跳重试失败, 维持拒答: %s", e)
                # 重试后重新评估证据门 (仅以 gate_decision 为准, evidence_found 仅表示有来源不代表覆盖特征)
                if gate_decision(
                        question, tool_attempted, evidence_found,
                        forced_retry_used, evidence_texts=evidence_texts) != "refuse":
                    # 重试拿到合格证据: 交给后续 final_messages 生成回答
                    final_messages = self._clean_for_final(messages, question, tool_msgs_start)
                else:
                    # 重试仍无合格证据: 走拒答
                    final_messages = None
            else:
                final_messages = None

            if final_messages is None:
                from src.agent.utils import _pace_stream_chunks
                if exec_log:
                    exec_log.set_status("no_evidence")
                logger.info("硬闸门: 检索无证据, 返回固定拒答话术 (tool_attempted=%s)",
                            tool_attempted)
                yield ("status", {"content": "知识库未命中，按受控原则不予自由作答"})
                notice = NO_EVIDENCE_NOTICE
                phase_times.append(("硬闸门拦截", 0))
                if exec_log:
                    exec_log.add_phase("硬闸门拦截", 0)
                audit = audit_answer(notice, [])
                for chunk in _pace_stream_chunks(notice):
                    yield ("token", {"content": chunk})
                yield ("done", {"sources": [], "web_sources": [],
                                "tool_called": tool_attempted, "tool_name": last_tool,
                                "phase_times": phase_times, "audit": audit,
                                "gated": True, "answer": notice})
                return
        else:
            final_messages = self._clean_for_final(messages, question, tool_msgs_start)

        # 闸门关闭时的旧软约束: 工具全空 → 注入提示词要求 LLM 说未找到
        if (not gate_enabled) and last_tool and not all_sources and not web_sources:
            final_messages.append({
                "role": "system",
                "content": ("所有检索工具均未返回有效结果。"
                            "你必须明确告知用户「未找到相关信息」，"
                            "绝对不能编造、猜测或凭常识回答。")
            })

        # 引用溯源: 给 LLM 注入资料编号, 让它标注 [资料N]
        merged_sources = self._merge_sources(all_sources)
        citation_suffix = build_citation_prompt_suffix(merged_sources)
        if citation_suffix:
            final_messages.append({"role": "system", "content": citation_suffix})

        yield ("status", {"content": "正在生成回答..."})
        t_gen = time.time()
        # 收集完整答案用于审计 (流式消费同时拼接)
        answer_parts = []
        for evt in self._generate_stream(final_messages, llm):
            if evt[0] == "token":
                answer_parts.append(evt[1].get("content", ""))
            yield evt
        full_answer = "".join(answer_parts)
        phase_times.append(("生成回答", int((time.time() - t_gen) * 1000)))
        if exec_log:
            exec_log.add_phase("生成回答", int((time.time() - t_gen) * 1000))

        # 审计完整答案
        audit = audit_answer(full_answer, merged_sources)
        yield ("done", {"sources": merged_sources,
                        "web_sources": self._merge_sources(web_sources),
                        "tool_called": bool(last_tool), "tool_name": last_tool,
                        "phase_times": phase_times,
                        "audit": audit, "gated": False,
                        "answer": full_answer})

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
