"""最终生成: 非流式/流式/深度思考/RAG 降级"""
import logging

from src.agent.constants import STREAM_FLUSH_CHARS, MAX_TOKENS_DEEP
from src.agent.tool_defense import _looks_like_tool_call
from src.agent.utils import _pace_stream_chunks

logger = logging.getLogger(__name__)

_CONSTRAINT_MSG = ("禁止输出 <tool_call>、JSON 函数调用或任何 XML 标签，"
                   "只输出纯文本回答。")


class GenerationMixin:
    def _generate_stream(self, messages, llm, deep_thinking: bool = False):
        if deep_thinking:
            yield from self._generate_deep(messages, llm)
            return
        pending = ""
        try:
            for text in llm.chat_stream(messages):
                pending += text
                if _looks_like_tool_call(pending):
                    yield ("reset", {})
                    messages = messages + [{"role": "user", "content": _CONSTRAINT_MSG}]
                    yield ("token", {"content": self._generate(messages, llm)})
                    return
                if len(pending) >= STREAM_FLUSH_CHARS:
                    for chunk in _pace_stream_chunks(pending):
                        yield ("token", {"content": chunk})
                    pending = ""
        except Exception as e:
            logger.error("流式生成失败: %s", e)
            yield ("token", {"content": self._generate(messages, llm)})
            return
        if pending:
            for chunk in _pace_stream_chunks(pending):
                yield ("token", {"content": chunk})
            pending = ""
        if _looks_like_tool_call(pending):
            yield ("reset", {})
            messages = messages + [{"role": "user", "content": _CONSTRAINT_MSG}]
            yield ("token", {"content": self._generate(messages, llm)})

    def _generate(self, messages, llm, retries: int = 3) -> str:
        for _ in range(retries):
            try:
                answer = llm.chat(messages)
            except Exception as e:
                logger.error("生成失败: %s", e)
                return "抱歉，生成回答时出现技术问题。"
            if answer and not _looks_like_tool_call(answer):
                return answer
            messages = messages + [{"role": "user", "content": _CONSTRAINT_MSG}]
        return "抱歉，生成回答时出现技术问题。"

    def _generate_deep(self, messages, llm):
        pending = ""
        try:
            for kind, text in llm.chat_stream_thinking(messages, max_tokens=MAX_TOKENS_DEEP):
                if kind == "thinking":
                    yield ("thinking", {"content": text})
                else:
                    pending += text
                    if _looks_like_tool_call(pending):
                        yield ("reset", {})
                        messages = messages + [{"role": "user", "content": _CONSTRAINT_MSG}]
                        yield ("token", {"content": self._generate(messages, llm)})
                        return
                    if len(pending) >= STREAM_FLUSH_CHARS:
                        for chunk in _pace_stream_chunks(pending):
                            yield ("token", {"content": chunk})
                        pending = ""
        except Exception as e:
            logger.error("深度思考流式失败: %s", e)
            yield ("token", {"content": self._generate(messages, llm)})
            return
        if pending:
            for chunk in _pace_stream_chunks(pending):
                yield ("token", {"content": chunk})

    def _fallback_rag(self, question, llm, messages):
        from src.rag.pipeline import rag_pipeline
        from src.agent.audit import audit_answer, build_citation_prompt_suffix
        yield ("status", {"content": "正在检索知识库..."})
        docs = rag_pipeline.search(question, top_k=5)
        context = "\n\n".join(f"【资料{i+1}】\n问: {d['question']}\n答: {d['answer']}"
                              for i, d in enumerate(docs))
        prompt = f"请严格基于以下资料回答问题：\n\n{context}\n\n问题: {question}\n回答:"
        yield ("status", {"content": "正在生成回答..."})
        answer_parts = []
        for evt in self._generate_stream(
                [{"role": "user", "content": prompt}], llm):
            if evt[0] == "token":
                answer_parts.append(evt[1].get("content", ""))
            yield evt
        full_answer = "".join(answer_parts)
        audit = audit_answer(full_answer, docs)
        yield ("done", {"sources": docs, "web_sources": [],
                        "tool_called": False, "tool_name": "",
                        "phase_times": [],
                        "audit": audit})
