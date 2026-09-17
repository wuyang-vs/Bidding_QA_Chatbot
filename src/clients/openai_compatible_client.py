from __future__ import annotations
"""vLLM / Ollama 等 OpenAI 兼容端点"""
from openai import OpenAI
from src.http_client import build_httpx_client
from src.clients.base_client import BaseLLMClient


class OpenAICompatibleClient(BaseLLMClient):
    def __init__(self, provider: str, base_url: str, api_key: str, model: str):
        self._provider = provider
        self._model = model
        self._client = OpenAI(
            api_key=api_key, base_url=base_url,
            http_client=build_httpx_client(timeout=300.0), max_retries=0,
        )

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model_name(self) -> str:
        return self._model

    def chat(self, messages, **kwargs) -> str:
        temperature = kwargs.pop("temperature", 0.3)
        resp = self._client.chat.completions.create(
            model=self._model, messages=messages, temperature=temperature, **kwargs)
        content = resp.choices[0].message.content
        if not content:
            content = getattr(resp.choices[0].message, "reasoning_content", "") or ""
        return content

    def chat_stream(self, messages, **kwargs):
        temperature = kwargs.pop("temperature", 0.3)
        stream = self._client.chat.completions.create(
            model=self._model, messages=messages, temperature=temperature, stream=True, **kwargs)
        reasoning_buf, has_content = "", False
        for chunk in stream:
            delta = chunk.choices[0].delta
            c = getattr(delta, "content", None)
            r = getattr(delta, "reasoning_content", None)
            if r:
                reasoning_buf += r
            if c:
                has_content = True
                yield c
        if not has_content and reasoning_buf:
            yield reasoning_buf

    def chat_stream_thinking(self, messages, **kwargs):
        temperature = kwargs.pop("temperature", 0.3)
        stream = self._client.chat.completions.create(
            model=self._model, messages=messages, temperature=temperature, stream=True, **kwargs)
        for chunk in stream:
            delta = chunk.choices[0].delta
            r = getattr(delta, "reasoning_content", None)
            c = getattr(delta, "content", None)
            if r:
                yield ("thinking", r)
            if c:
                yield ("content", c)

    def chat_raw(self, messages, tools=None, **kwargs):
        params = {"model": self._model, "messages": messages, "temperature": 0.3}
        if tools:
            params["tools"] = tools
            params["tool_choice"] = kwargs.pop("tool_choice", "auto")
        params.update(kwargs)
        return self._client.chat.completions.create(**params)
