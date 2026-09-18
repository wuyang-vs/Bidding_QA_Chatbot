# -*- coding: utf-8 -*-
"""RAG 检索行级隔离的离线确定性验证 (不经过 HTTP/LLM).

场景:
  - 公开文档 (db_id 999002): 任何身份可见
  - 内部文档 (db_id 999003, owner=TEST_UID): 仅 admin/auditor/owner 可见,
    匿名与其他登录用户检索时必须在召回层被过滤掉

验证点:
  1. ingest 写入 visibility/owner_id payload
  2. hybrid_search 按 access_scope 在 Qdrant 侧预过滤 (不是后置截断)
  3. ContextVar + pipeline.search 全链路一致
  4. lru_cache 不跨身份串结果
结束后清理两个测试 db_id 的全部分片.

用法: .venv\\Scripts\\python.exe tests\\eval\\test_retrieval_access.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

PUB_DB_ID = 999002
INT_DB_ID = 999003
TEST_UID = 880001      # 内部文档 owner (虚构 uid, Qdrant 无 FK)
OTHER_UID = 880002     # 另一个投标人/招标人

# 唯一性标记词, 语义无关也能靠 sparse/dense 命中本文档
PUB_MARKER = "鳜鱼公开条款核验词"
INT_MARKER = "鳙鱼内部条款核验词"


def _hit_ids(hits: list[dict]) -> set[int]:
    return {int(h["db_id"]) for h in hits if h.get("db_id") in (PUB_DB_ID, INT_DB_ID)}


def main() -> int:
    import warnings
    warnings.filterwarnings("ignore")

    from src.rag.ingest import ingest_tender_document, delete_tender_document
    from src.rag.vector_store import vector_store
    from src.rag.embedder import embedder
    from src.auth.access_scope import (
        scope_for_user, use_access_scope, get_current_scope)

    delete_tender_document(PUB_DB_ID)
    delete_tender_document(INT_DB_ID)

    pub_text = (f"{PUB_MARKER} 投标截止时间为2026年10月1日上午九点。\n" * 20)
    int_text = (f"{INT_MARKER} 本项目评标基准价下浮率及专家费标准为内部信息。\n" * 20)

    n1 = ingest_tender_document(
        PUB_DB_ID, pub_text, source_file="access_public_test.txt",
        project_name="公开隔离测试", visibility="public", owner_id=OTHER_UID)
    n2 = ingest_tender_document(
        INT_DB_ID, int_text, source_file="access_internal_test.txt",
        project_name="内部隔离测试", visibility="internal", owner_id=TEST_UID)
    assert n1 >= 1 and n2 >= 1, f"写入失败 {n1}/{n2}"

    # payload 字段检查
    c = vector_store._get_client()
    from src.config import settings
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    pts, _ = c.scroll(
        settings.qdrant_collection,
        scroll_filter=Filter(must=[
            FieldCondition(key="db_id", match=MatchValue(value=INT_DB_ID))]),
        limit=10, with_payload=True, with_vectors=False)
    assert pts and all(p.payload.get("visibility") == "internal"
                       and p.payload.get("owner_id") == TEST_UID for p in pts), \
        "内部分片 visibility/owner_id 未写入"

    def search(mode: str):
        q = ("内部 评标 基准价 下浮率 专家费" if mode == "internal"
             else "投标 截止 时间")
        dense = embedder.encode_query_dense(q)
        sparse = embedder.encode_query_sparse(q)
        return vector_store.hybrid_search(
            dense, sparse, limit=20, question=q)

    # --- 内部信息在各身份下的召回 ---
    # admin (scope=None): 内部文档可召回
    hits = search("internal")
    ids = _hit_ids(hits)
    assert INT_DB_ID in ids, f"admin 应见内部文档, 实际 {ids}"
    # 公开文档在无过滤下也可召回
    hits_pub = search("public")
    assert PUB_DB_ID in _hit_ids(hits_pub), "公开文档应可被无过滤检索"

    # 匿名 scope=("public",): 内部不可见
    with use_access_scope(None):
        assert get_current_scope() == ("public",)
        hits = search("internal")
        ids = _hit_ids(hits)
    assert INT_DB_ID not in ids, f"匿名召回了内部文档! {ids}"

    # owner: 内部可见
    owner = {"id": TEST_UID, "role": "bidder", "username": "owner"}
    with use_access_scope(owner):
        assert scope_for_user(owner) == ("owner", TEST_UID)
        hits = search("internal")
        ids = _hit_ids(hits)
    assert INT_DB_ID in ids, f"owner 应见本人内部文档, 实际 {ids}"

    # 其他 bidder/purchaser: 内部不可见
    other = {"id": OTHER_UID, "role": "purchaser", "username": "other"}
    with use_access_scope(other):
        hits = search("internal")
        ids = _hit_ids(hits)
    assert INT_DB_ID not in ids, f"其他用户不应召回内部文档! {ids}"

    # auditor: 不限制
    auditor = {"id": 999, "role": "auditor", "username": "aud"}
    with use_access_scope(auditor):
        hits = search("internal")
        ids = _hit_ids(hits)
    assert INT_DB_ID in ids, f"auditor 应见内部文档, 实际 {ids}"

    # --- pipeline 层: 缓存不跨身份串用 ---
    from src.rag.pipeline import rag_pipeline, _cached_search
    rag_pipeline._ready = True  # search 本身不依赖 ready 标志
    q_int = "评标基准价下浮率专家费标准"
    with use_access_scope(None):
        anon_docs = rag_pipeline.search(q_int, top_k=10)
    with use_access_scope(owner):
        owner_docs = rag_pipeline.search(q_int, top_k=10)
    assert all(d.get("db_id") != INT_DB_ID for d in anon_docs), \
        "pipeline 匿名路径泄漏内部文档"
    assert any(d.get("db_id") == INT_DB_ID for d in owner_docs), \
        "pipeline owner 路径应能命中本人内部文档"
    # 缓存桶确实按身份分开
    assert _cached_search.cache_info().currsize >= 2, "缓存未按身份分桶"

    delete_tender_document(PUB_DB_ID)
    delete_tender_document(INT_DB_ID)
    print(f"PASS: 公开 {n1} 片/内部 {n2} 片; 匿名仅public、owner可见本人、"
          f"他人不可见、admin/auditor全见; pipeline缓存分桶隔离; 已清理")
    return 0


if __name__ == "__main__":
    sys.exit(main())
