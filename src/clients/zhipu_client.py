from __future__ import annotations
"""智谱 GLM (zai-sdk)"""
from zai import ZhipuAiClient
from src.config import settings
from src.clients.base_client import BaseLLMClient


class ZhipuClient(BaseLLMClient):
    def __init__(self, model: str | None = None):
        self._model = model or settings.zhipu_model
        self._client = ZhipuAiClient(api_key=settings.zhipu_api_key)

    @property
    def provider(self) -> str:
        return "zhipu"

    @property
    def model_name(self) -> str:
        return self._model

    def chat(self, messages, **kwargs) -> str:
        resp = self._client.chat.completions.create(
            model=self._model, messages=messages, temperature=0.3, **kwargs)
        return resp.choices[0].message.content or ""

    def chat_stream(self, messages, **kwargs):
        resp = self._client.chat.completions.create(
            model=self._model, messages=messages, temperature=0.3, stream=True, **kwargs)
        for chunk in resp:
            c = chunk.choices[0].delta.content
            if c:
                yield c

    def chat_stream_thinking(self, messages, **kwargs):
        for c in self.chat_stream(messages, **kwargs):
            yield ("content", c)

    def chat_raw(self, messages, tools=None, **kwargs):
        params = {"model": self._model, "messages": messages, "temperature": 0.3}
        if tools:
            params["tools"] = tools
            params["tool_choice"] = kwargs.pop("tool_choice", "auto")
        params.update(kwargs)
        return self._client.chat.completions.create(**params)
