from __future__ import annotations
"""LLM 客户端工厂 (带缓存)"""
import threading
from src.config import settings
from src.clients.base_client import BaseLLMClient
from src.clients.deepseek_client import DeepSeekClient
from src.clients.openai_compatible_client import OpenAICompatibleClient

_cache: dict[tuple, BaseLLMClient] = {}
_lock = threading.Lock()


def _thinking_model(provider: str) -> str:
    return {"deepseek": settings.deepseek_thinking_model,
            "zhipu": settings.zhipu_thinking_model}.get(provider, "")


def get_llm_client(provider: str = "", deep_thinking: bool = False) -> BaseLLMClient:
    provider = provider or settings.llm_provider
    model_override = _thinking_model(provider) if deep_thinking else ""
    key = (provider, model_override)
    with _lock:
        if key in _cache:
            return _cache[key]
        if provider == "deepseek":
            client = DeepSeekClient(model=model_override or None)
        elif provider == "zhipu":
            from src.clients.zhipu_client import ZhipuClient
            client = ZhipuClient(model=model_override or None)
        elif provider == "vllm":
            client = OpenAICompatibleClient("vllm", settings.vllm_base_url,
                                            settings.vllm_api_key, settings.vllm_model)
        elif provider == "ollama":
            client = OpenAICompatibleClient("ollama", settings.ollama_base_url,
                                            settings.ollama_api_key, settings.ollama_model)
        else:
            raise ValueError(f"未知 provider: {provider}")
        _cache[key] = client
        return client
