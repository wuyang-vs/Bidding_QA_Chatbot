"""RAG 检索的行级访问范围 (按请求注入, ContextVar 线程/协程安全).

范围语义:
  None                 不限制 (admin/auditor, 或离线系统任务)
  ("public",)          仅公开分片 (匿名)
  ("owner", user_id)   公开分片 + 本人 owner_id 的内部分片 (purchaser/bidder)

向量库在 *召回前* 据此构造 Qdrant Filter (metadata 预过滤),
不做检索后的启发式截断, 避免有效召回被误删。
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

from src.auth.jwt import ROLE_ADMIN, ROLE_AUDITOR

logger = logging.getLogger(__name__)

_current_scope: ContextVar[tuple | None] = ContextVar(
    "rag_access_scope", default=None)

# 内部分片可见的角色 (本人文件); 其余角色一律仅见 public
_OWNER_ROLES = {"purchaser", "bidder"}


def scope_for_user(user: dict | None) -> tuple | None:
    """JWT payload (或 None) → 检索范围."""
    if user is None:
        return ("public",)
    role = user.get("role")
    if role in (ROLE_ADMIN, ROLE_AUDITOR):
        return None
    uid = user.get("id")
    if role in _OWNER_ROLES and uid is not None:
        return ("owner", int(uid))
    # 未知角色按最严处理
    return ("public",)


def get_current_scope() -> tuple | None:
    return _current_scope.get()


def scope_cache_key(scope: tuple | None) -> str:
    """lru_cache 键: 不同身份绝不共享检索缓存."""
    if scope is None:
        return "all"
    if scope[0] == "public":
        return "pub"
    return f"own:{scope[1]}"


@contextmanager
def use_access_scope(user: dict | None) -> Iterator[None]:
    """在 HTTP 请求处理期间设置该用户的检索范围, 退出时恢复."""
    token = _current_scope.set(scope_for_user(user))
    try:
        yield
    finally:
        _current_scope.reset(token)


def build_qdrant_filter(scope: tuple | None) -> Any:
    """范围 → qdrant_client.models.Filter; None 表示不过滤.

    依赖存量分片已回填 visibility (见 ingest.backfill_access_metadata):
      - FAQ/公开分片: visibility=public
      - 内部分片:   visibility=internal, owner_id=<uid>
    """
    if scope is None:
        return None
    from qdrant_client.models import Filter, FieldCondition, MatchValue

    if scope[0] == "public":
        return Filter(must=[
            FieldCondition(key="visibility", match=MatchValue(value="public"))])
    # owner: public OR owner_id = uid
    return Filter(should=[
        FieldCondition(key="visibility", match=MatchValue(value="public")),
        FieldCondition(key="owner_id", match=MatchValue(value=int(scope[1]))),
    ])
