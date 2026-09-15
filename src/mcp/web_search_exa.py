from __future__ import annotations
"""Exa MCP 封装 (后台启动, 未就绪仅 Tavily)"""
import logging
import re
import threading

from src.config import settings
from src.mcp.mcp_client import McpClient

logger = logging.getLogger(__name__)


class ExaMcpClient:
    def __init__(self):
        self._client = None
        self._lock = threading.Lock()
        self._started = False

    def initialize(self) -> None:
        if not settings.exa_api_key:
            return
        with self._lock:
            if self._started:
                return
            self._started = True
        threading.Thread(target=self._start_background, daemon=True).start()

    def _start_background(self) -> None:
        try:
            client = McpClient(["npx", "-y", "exa-mcp-server"],
                               env={"EXA_API_KEY": settings.exa_api_key})
            if client.initialize():
                self._client = client
                logger.info("Exa MCP 就绪")
        except Exception as e:
            logger.warning("Exa MCP 启动失败: %s", e)

    @property
    def ready(self) -> bool:
        return self._client is not None and self._client.is_alive()

    def search(self, query: str) -> list[dict]:
        if not self.ready:
            return []
        resp = self._client.call_tool("web_search_exa", {"query": query, "numResults": 5})
        if not resp.get("success", True) and "error" in resp:
            logger.warning("Exa 搜索失败: %s", resp["error"])
            return []
        content = resp.get("result", {}).get("content", [])
        items = []
        for c in content:
            text = c.get("text", "") if isinstance(c, dict) else str(c)
            if isinstance(c, dict) and "resource" in c:
                uri = c["resource"].get("uri", "")
                items.append({"question": text[:80],
                              "answer": c["resource"].get("text", "")[:500],
                              "score": 0.0, "url": uri})
                continue
            m = re.match(r"Title:\s*(.*?)\n.*?URL:\s*(\S+)", text, re.S)
            if m:
                items.append({"question": m.group(1).strip(),
                              "answer": text[:500], "score": 0.0, "url": m.group(2)})
        return items


exa_search_client = ExaMcpClient()
