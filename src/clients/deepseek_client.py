"""DeepSeek (OpenAI 兼容协议)"""
import logging
from openai import OpenAI
from src.config import settings
from src.http_client import build_httpx_client
from src.clients.base_client import BaseLLMClient

logger = logging.getLogger(__name__)


class DeepSeekClient(BaseLLMClient):
    def __init__(self, model: str | None = None):
        self._model = model or settings.deepseek_model
        self._client = OpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            http_client=build_httpx_client(timeout=60.0),
            max_retries=1,
        )

    @property
    def provider(self) -> str:
        return "deepseek"

    @property
    def model_name(self) -> str:
        return self._model

    def chat(self, messages, **kwargs) -> str:
        resp = self._client.chat.completions.create(
            model=self._model, messages=messages, temperature=0.3, **kwargs)
        content = resp.choices[0].message.content
        if not content:
            content = getattr(resp.choices[0].message, "reasoning_content", "") or ""
        return content

    def chat_stream(self, messages, **kwargs):
        stream = self._client.chat.completions.create(
            model=self._model, messages=messages, temperature=0.3, stream=True, **kwargs)
        reasoning_buf = ""
        has_content = False
        for chunk in stream:
            delta = chunk.choices[0].delta
            content = getattr(delta, "content", None)
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                reasoning_buf += reasoning
            if content:
                has_content = True
                yield content
        if not has_content and reasoning_buf:
            yield reasoning_buf

    def chat_stream_thinking(self, messages, **kwargs):
        stream = self._client.chat.completions.create(
            model=self._model, messages=messages, temperature=0.3, stream=True, **kwargs)
        for chunk in stream:
            delta = chunk.choices[0].delta
            reasoning = getattr(delta, "reasoning_content", None)
            content = getattr(delta, "content", None)
            if reasoning:
                yield ("thinking", reasoning)
            if content:
                yield ("content", content)

    def chat_raw(self, messages, tools=None, **kwargs):
        params = {"model": self._model, "messages": messages, "temperature": 0.3}
        if tools:
            params["tools"] = tools
            if "tool_choice" in kwargs:
                params["tool_choice"] = kwargs.pop("tool_choice")
            else:
                params["tool_choice"] = "auto"
        params.update(kwargs)
        return self._client.chat.completions.create(**params)
