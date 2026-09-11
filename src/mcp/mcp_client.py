"""轻量 MCP 客户端 (stdio JSON-RPC 2.0)"""
import json
import logging
import queue
import subprocess
import threading
import time

logger = logging.getLogger(__name__)

RESPONSE_TIMEOUT = 60
RESTART_COOLDOWN = 30


class McpClient:
    def __init__(self, command: list[str], env: dict | None = None):
        self._command = command
        self._env = env or {}
        self._proc = None
        self._lock = threading.Lock()
        self._request_id = 0
        self._last_restart = 0.0

    def _start_locked(self) -> None:
        import os
        cmd = self._command
        if os.name == "nt" and cmd and cmd[0] == "npx":
            cmd = ["npx.cmd"] + cmd[1:]
        self._proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={**os.environ, **self._env}, text=True, bufsize=1,
        )

    def initialize(self) -> bool:
        with self._lock:
            if self._proc and self._proc.poll() is None:
                return True
            self._start_locked()
        return self._handshake()

    def _handshake(self) -> bool:
        try:
            self._send({"jsonrpc": "2.0", "id": self._next_id(), "method": "initialize",
                        "params": {"protocolVersion": "2024-11-05",
                                   "capabilities": {}, "clientInfo": {"name": "bidding-qa"}}})
            self._recv()
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            self._send({"jsonrpc": "2.0", "id": self._next_id(), "method": "tools/list"})
            self._recv()
            return True
        except Exception as e:
            logger.warning("MCP 握手失败: %s", e)
            self.close()
            return False

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _send(self, obj: dict) -> None:
        line = json.dumps(obj, ensure_ascii=False) + "\n"
        with self._lock:
            self._proc.stdin.write(line)
            self._proc.stdin.flush()

    def _recv(self) -> dict:
        q: queue.Queue = queue.Queue()

        def _reader():
            try:
                q.put(self._proc.stdout.readline())
            except Exception as e:
                q.put(e)

        t = threading.Thread(target=_reader, daemon=True)
        t.start()
        try:
            item = q.get(timeout=RESPONSE_TIMEOUT)
        except queue.Empty:
            raise TimeoutError("MCP 响应超时")
        if isinstance(item, Exception):
            raise item
        return json.loads(item)

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def call_tool(self, name: str, arguments: dict) -> dict:
        if not self.is_alive():
            now = time.time()
            if now - self._last_restart < RESTART_COOLDOWN:
                return {"success": False, "error": "MCP 服务不可用"}
            self._last_restart = now
            if not self.initialize():
                return {"success": False, "error": "MCP 重启失败"}
        self._send({"jsonrpc": "2.0", "id": self._next_id(), "method": "tools/call",
                    "params": {"name": name, "arguments": arguments}})
        try:
            return self._recv()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def close(self) -> None:
        if self._proc:
            try:
                self._proc.terminate()
            except Exception:
                pass
            self._proc = None
