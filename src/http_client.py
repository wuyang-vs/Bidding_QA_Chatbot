from __future__ import annotations
import os, httpx, requests
def _proxy():
    return os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or None
def build_httpx_client(timeout=60.0):
    return httpx.Client(timeout=timeout, trust_env=False, proxy=_proxy())
def build_requests_session():
    s = requests.Session(); s.trust_env = False
    p = _proxy()
    if p: s.proxies = {"http": p, "https": p}
    return s
