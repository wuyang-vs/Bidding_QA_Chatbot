"""Tavily 客户端 (进程内缓存 TTL 600s / 上限 512 条)"""
import logging
import threading
import time

from src.config import settings

logger = logging.getLogger(__name__)

CACHE_TTL = 600
CACHE_MAX = 512


class WebSearchClient:
    def __init__(self):
        self._client = None
        self._cache: dict[str, tuple[float, list]] = {}
        self._lock = threading.Lock()

    def initialize(self) -> None:
        if not settings.tavily_api_key:
            logger.warning("TAVILY_API_KEY 未配置, 联网搜索不可用")
            return
        try:
            from tavily import TavilyClient
            self._client = TavilyClient(api_key=settings.tavily_api_key)
        except Exception as e:
            logger.warning("Tavily 初始化失败: %s", e)

    @property
    def ready(self) -> bool:
        return self._client is not None

    def search(self, query: str, depth: str = "basic", max_results: int = 5) -> list[dict]:
        if not self._client:
            return []
        key = query.strip().lower()
        now = time.time()
        with self._lock:
            if key in self._cache:
                ts, data = self._cache[key]
                if now - ts < CACHE_TTL:
                    return data
                del self._cache[key]
        try:
            resp = self._client.search(query, search_depth=depth,
                                       max_results=max_results, include_answer=True)
        except Exception as e:
            logger.warning("Tavily 搜索失败: %s", e)
            return []
        items = []
        if resp.get("answer"):
            items.append({"question": "Tavily 摘要（供参考，引用请核对原始链接）",
                          "answer": resp["answer"], "score": 0.0, "url": ""})
        for r in resp.get("results", []):
            items.append({"question": r.get("title", ""),
                          "answer": (r.get("content", "") or "")[:500],
                          "score": float(r.get("score", 0.0)),
                          "url": r.get("url", "")})
        with self._lock:
            if len(self._cache) >= CACHE_MAX:
                expired = [k for k, (ts, _) in self._cache.items() if now - ts >= CACHE_TTL]
                for k in expired:
                    del self._cache[k]
                if len(self._cache) >= CACHE_MAX:
                    oldest = sorted(self._cache.items(), key=lambda x: x[1][0])[:CACHE_MAX // 2]
                    for k, _ in oldest:
                        del self._cache[k]
            self._cache[key] = (now, items)
        return items


web_search_client = WebSearchClient()
