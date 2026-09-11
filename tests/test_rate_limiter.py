import threading
import time

from src.rate_limiter import RateLimiter


def test_basic_quota():
    rl = RateLimiter(max_requests=3, window=60)
    assert rl.is_allowed("a") and rl.is_allowed("a") and rl.is_allowed("a")
    assert not rl.is_allowed("a")


def test_per_client_isolation():
    rl = RateLimiter(max_requests=1, window=60)
    assert rl.is_allowed("a")
    assert rl.is_allowed("b")
    assert not rl.is_allowed("a")


def test_window_expiry(monkeypatch):
    rl = RateLimiter(max_requests=1, window=60)
    assert rl.is_allowed("ip")

    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 61)
    assert rl.is_allowed("ip")


def test_thread_safety_exact_quota():
    rl = RateLimiter(max_requests=100, window=60)
    allowed = []
    lock = threading.Lock()

    def worker():
        if rl.is_allowed("ip"):
            with lock:
                allowed.append(1)

    threads = [threading.Thread(target=worker) for _ in range(150)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(allowed) == 100
