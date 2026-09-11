import threading, time
WINDOW_SECONDS = 60
MAX_REQUESTS = 30

class RateLimiter:
    def __init__(self, max_requests=MAX_REQUESTS, window=WINDOW_SECONDS):
        self.max_requests = max_requests
        self.window = window
        self._clients = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.time()

    def is_allowed(self, client_id):
        now = time.time()
        ws = now - self.window
        with self._lock:
            self._cleanup(now)
            ts = [t for t in self._clients.get(client_id, []) if t > ws]
            if len(ts) >= self.max_requests:
                self._clients[client_id] = ts
                return False
            ts.append(now)
            self._clients[client_id] = ts
            return True

    def _cleanup(self, now):
        if now - self._last_cleanup < 300: return
        ws = now - self.window
        for k in [k for k, v in self._clients.items() if not any(t > ws for t in v)]:
            del self._clients[k]
        self._last_cleanup = now

rate_limiter = RateLimiter()
