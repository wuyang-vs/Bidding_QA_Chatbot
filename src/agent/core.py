from __future__ import annotations
"""BiddingAgent 主体"""
import logging
import time

from src.clients.llm_factory import get_llm_client
from src.agent.constants import BASE_TOOL_NAMES, WEB_TOOL_NAMES
from src.agent.intent import (
    is_out_of_scope, is_vague_question,
    scope_rejection_message, vague_guidance_message,
    classify_domain, select_tools_for_domain,
)
from src.agent.prompts import SYSTEM_PROMPT
from src.agent.react_loop import ReActMixin
from src.agent.generation import GenerationMixin
from src.agent.skills import AVAILABLE_SKILLS, SKILLS_PROMPT, _match_skills
from src.agent.utils import _sse, _truncate_history
from src.agent.execution_log import ExecutionLogger
from src.tools.rag_tools import ALL_TOOLS

logger = logging.getLogger(__name__)


class BiddingAgent(ReActMixin, GenerationMixin):
    def __init__(self):
        self._ready = False
        self.llm = None

    def initialize(self) -> None:
        from src.rag.pipeline import rag_pipeline
        rag_pipeline.initialize()
        self.llm = get_llm_client()
        self._ready = rag_pipeline.ready
        logger.info("Agent 初始化完成, ready=%s", self._ready)

    @property
    def ready(self) -> bool:
        return self._ready

    def _build_context(self, question, history, web_search_enabled, deep_thinking):
        system = SYSTEM_PROMPT + "\n\n" + SKILLS_PROMPT
        if deep_thinking:
            system += "\n\n【深度思考已启用】先拆解问题，多角度分析，再给结论。"
        for name in _match_skills(question, history, AVAILABLE_SKILLS):
            system += f"\n\n【技能指令: {name}】\n{AVAILABLE_SKILLS[name]['body']}\n本次必须严格遵循以上流程与模板执行。"
        messages = [{"role": "system", "content": system}]
        messages.extend(_truncate_history(history))
        messages.append({"role": "user", "content": question})
        # 显式三业务线意图路由: 显著单域时裁剪 active_tools, 跨域/弱信号保守回退全集
        from src.config import settings
        active_names = list(BASE_TOOL_NAMES)
        if getattr(settings, "intent_routing_enabled", True):
            verdict = classify_domain(question, history)
            before = len(active_names)
            active_names = select_tools_for_domain(verdict["domain"], active_names)
            logger.info(
                "意图路由: domain=%s confident=%s inherited=%s scores=%s tools %d->%d",
                verdict["domain"], verdict["confident"], verdict["inherited"],
                verdict["scores"], before, len(active_names))
        if web_search_enabled:
            active_names += WEB_TOOL_NAMES
        active_tools = [t.to_openai_schema() for t in ALL_TOOLS if t.name in active_names]
        return messages, active_tools

    def _chat_events(self, question, history=None, web_search_enabled=False,
                     provider="", deep_thinking_enabled=False,
                     audit_user: dict | None = None, audit_ip: str = ""):
        if not self._ready:
            yield ("error", {"content": "知识库未就绪"})
            return

        exec_log = ExecutionLogger()
        exec_log.set_context(question, provider, web_search_enabled, deep_thinking_enabled)

        # 问答交互审计辅助 (失败降级, 永不阻断主流程)
        def _audit_chat(action_suffix: str, *, sources: int = 0, web_sources: int = 0,
                        gated: bool = False, answer_len: int = 0, tool_names: list | None = None,
                        elapsed_ms: int = 0):
            try:
                from src.tools.audit_log import record_audit
                uid = audit_user.get("id") if isinstance(audit_user, dict) else None
                uname = (audit_user.get("username") or audit_user.get("display_name")
                         or "anonymous") if isinstance(audit_user, dict) else "anonymous"
                # 只存工具名/统计量, 不存问题原文与回答原文
                detail = (f"q_len={len(question)} ans_len={answer_len} "
                          f"sources={sources} web={web_sources} gated={gated} "
                          f"elapsed_ms={elapsed_ms}")
                record_audit(user_id=uid, username=uname,
                             action=f"chat.{action_suffix}",
                             target_type="conversation",
                             changed_fields=list(tool_names or []),
                             ip=audit_ip, detail=detail)
            except Exception as e:
                logger.warning("[问答审计-异常] %s: %s", action_suffix, e)

        # ---- 前置意图检测 ----
        if is_out_of_scope(question, history):
            yield ("status", {"content": "问题超出领域范围"})
            ans = scope_rejection_message(question)
            yield ("token", {"content": ans})
            yield ("done", {"sources": [], "web_sources": [],
                            "tool_called": False, "tool_name": "",
                            "phase_times": [("前置检测", 0)], "gated": False})
            exec_log.set_status("out_of_scope")
            exec_log.add_phase("前置检测", 0)
            exec_log.set_result(ans, 0, 0, None)
            exec_log.finish()
            _audit_chat("out_of_scope", answer_len=len(ans))
            return
        if is_vague_question(question, history):
            yield ("status", {"content": "问题信息不足"})
            ans = vague_guidance_message(question)
            yield ("token", {"content": ans})
            yield ("done", {"sources": [], "web_sources": [],
                            "tool_called": False, "tool_name": "",
                            "phase_times": [("前置检测", 0)], "gated": False})
            exec_log.set_status("vague")
            exec_log.add_phase("前置检测", 0)
            exec_log.set_result(ans, 0, 0, None)
            exec_log.finish()
            _audit_chat("vague", answer_len=len(ans))
            return

        t0 = time.time()
        try:
            yield ("status", {"content": "正在初始化..."})
            if deep_thinking_enabled:
                yield ("status", {"content": "正在深度思考..."})
            llm = get_llm_client(provider, deep_thinking_enabled)
            messages, active_tools = self._build_context(
                question, history, web_search_enabled, deep_thinking_enabled)
            yield ("status", {"content": "正在检索与搜索..."})
            for evt_type, kwargs in self._chat_stream_tools(
                    messages, question, llm, active_tools, web_search_enabled,
                    exec_log=exec_log):
                if evt_type == "done":
                    kwargs["elapsed_ms"] = int((time.time() - t0) * 1000)
                    exec_log.set_result(
                        kwargs.get("answer", ""),
                        len(kwargs.get("sources", [])),
                        len(kwargs.get("web_sources", [])),
                        kwargs.get("audit"),
                    )
                    exec_log.elapsed_ms = kwargs["elapsed_ms"]
                    exec_log.finish()
                    # 供非流式 /api/chat 返回完整工具调用轨迹 (含多轮工具)
                    kwargs["exec_log"] = exec_log.to_dict()
                    # 问答交互审计: 提取实际调用的工具名
                    tool_names = [tc.get("name") for tc in
                                  (kwargs.get("exec_log", {}) or {}).get("tool_calls", [])
                                  if isinstance(tc, dict)]
                    _audit_chat(
                        "gated" if kwargs.get("gated") else "answer",
                        sources=len(kwargs.get("sources", []) or []),
                        web_sources=len(kwargs.get("web_sources", []) or []),
                        gated=bool(kwargs.get("gated")),
                        answer_len=len(kwargs.get("answer", "") or ""),
                        tool_names=tool_names,
                        elapsed_ms=kwargs["elapsed_ms"],
                    )
                yield (evt_type, kwargs)
        except Exception as e:
            logger.exception("Agent 处理异常")
            exec_log.set_status("error", str(e))
            exec_log.finish()
            yield ("error", {"content": "生成回答时出现异常，请稍后重试"})

    def chat_stream(self, question, history=None, web_search_enabled=False,
                    provider="", deep_thinking_enabled=False,
                    audit_user: dict | None = None, audit_ip: str = ""):
        yield ": " + " " * 2048 + "\n\n"
        for evt_type, kwargs in self._chat_events(
                question, history, web_search_enabled, provider, deep_thinking_enabled,
                audit_user=audit_user, audit_ip=audit_ip):
            yield _sse(evt_type, **kwargs)

    def chat(self, question, history=None, web_search_enabled=False,
             provider="", deep_thinking_enabled=False,
             audit_user: dict | None = None, audit_ip: str = "") -> dict:
        result = {"answer": "", "sources": [], "web_sources": [],
                  "tool_called": False, "tool_name": "", "gated": False,
                  "exec_log": {"tool_calls": []}}
        for evt_type, kwargs in self._chat_events(
                question, history, web_search_enabled, provider, deep_thinking_enabled,
                audit_user=audit_user, audit_ip=audit_ip):
            if evt_type == "token":
                result["answer"] += kwargs.get("content", "")
            elif evt_type == "done":
                result.update({k: kwargs.get(k) for k in
                               ("sources", "web_sources", "tool_called",
                                "tool_name", "gated", "exec_log")})
            elif evt_type == "error":
                result["answer"] = kwargs.get("content", "")
        return result


bidding_agent = BiddingAgent()
