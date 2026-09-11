"""BiddingAgent 主体"""
import logging
import time

from src.clients.llm_factory import get_llm_client
from src.agent.constants import BASE_TOOL_NAMES, WEB_TOOL_NAMES
from src.agent.prompts import SYSTEM_PROMPT
from src.agent.react_loop import ReActMixin
from src.agent.generation import GenerationMixin
from src.agent.skills import AVAILABLE_SKILLS, SKILLS_PROMPT, _match_skills
from src.agent.utils import _sse, _truncate_history
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
        active_names = list(BASE_TOOL_NAMES)
        if web_search_enabled:
            active_names += WEB_TOOL_NAMES
        active_tools = [t.to_openai_schema() for t in ALL_TOOLS if t.name in active_names]
        return messages, active_tools

    def _chat_events(self, question, history=None, web_search_enabled=False,
                     provider="", deep_thinking_enabled=False):
        if not self._ready:
            yield ("error", {"content": "知识库未就绪"})
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
                    messages, question, llm, active_tools, web_search_enabled):
                if evt_type == "done":
                    kwargs["elapsed_ms"] = int((time.time() - t0) * 1000)
                yield (evt_type, kwargs)
        except Exception:
            logger.exception("Agent 处理异常")
            yield ("error", {"content": "生成回答时出现异常，请稍后重试"})

    def chat_stream(self, question, history=None, web_search_enabled=False,
                    provider="", deep_thinking_enabled=False):
        yield ": " + " " * 2048 + "\n\n"
        for evt_type, kwargs in self._chat_events(
                question, history, web_search_enabled, provider, deep_thinking_enabled):
            yield _sse(evt_type, **kwargs)

    def chat(self, question, history=None, web_search_enabled=False,
             provider="", deep_thinking_enabled=False) -> dict:
        result = {"answer": "", "sources": [], "web_sources": [],
                  "tool_called": False, "tool_name": ""}
        for evt_type, kwargs in self._chat_events(
                question, history, web_search_enabled, provider, deep_thinking_enabled):
            if evt_type == "token":
                result["answer"] += kwargs.get("content", "")
            elif evt_type == "done":
                result.update({k: kwargs.get(k) for k in
                               ("sources", "web_sources", "tool_called", "tool_name")})
            elif evt_type == "error":
                result["answer"] = kwargs.get("content", "")
        return result


bidding_agent = BiddingAgent()
