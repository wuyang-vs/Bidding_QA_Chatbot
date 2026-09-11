"""LLM 客户端基类"""
from abc import ABC, abstractmethod


class BaseLLMClient(ABC):
    @property
    @abstractmethod
    def provider(self) -> str: ...

    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @abstractmethod
    def chat(self, messages: list[dict], **kwargs) -> str: ...

    @abstractmethod
    def chat_stream(self, messages: list[dict], **kwargs): ...

    @abstractmethod
    def chat_stream_thinking(self, messages: list[dict], **kwargs):
        """产出 (kind, text), kind ∈ {thinking, content}"""

    @abstractmethod
    def chat_raw(self, messages: list[dict], tools: list | None = None, **kwargs):
        """返回原始响应对象 (Agent 读取 tool_calls)"""
