# -*- coding: utf-8 -*-
"""页码/包件元数据切分的离线确定性验证 (不经过 HTTP/LLM).

验证:
  1. ingest_tender_document 按 pages 切分后, 每个分片 payload 带正确 page_no
  2. chunk_id 含页码; package/bidder_name 写入 payload
  3. 检索结果透传 page_no (hybrid_search)
结束后清理测试 db_id 的全部分片.

用法: .venv\\Scripts\\python.exe tests\\eval\\test_page_chunking.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

TEST_DB_ID = 999001  # 专用测试段, 与业务数据隔离


def main() -> int:
    import warnings
    warnings.filterwarnings("ignore")

    from src.rag.ingest import ingest_tender_document, delete_tender_document
    from src.rag.vector_store import vector_store
    from src.rag.embedder import embedder
    from qdrant_client.models import Filter, FieldCondition, MatchValue

    delete_tender_document(TEST_DB_ID)  # 清残留

    pages = [
        {"page_no": 1, "text": "第一页: 投标截止时间为2026年9月1日。" * 30},
        {"page_no": 2, "text": "第二页: 评分办法采用综合评分法价格分四十分。" * 30},
        {"page_no": 3, "text": "第三页: 废标条款规定未密封投标文件将被拒收。" * 30},
    ]
    raw = "\n".join(p["text"] for p in pages)
    n = ingest_tender_document(
        TEST_DB_ID, raw, source_file="eval_page_test.txt",
        project_name="页码切分自测", pages=pages,
        package="第2包", bidder_name="自测投标人")
    assert n >= 3, f"分片数异常: {n}"

    # 直接按 payload 滚动取出全部测试分片
    c = vector_store._get_client()
    from src.config import settings
    pts, _ = c.scroll(
        settings.qdrant_collection,
        scroll_filter=Filter(must=[
            FieldCondition(key="db_id", match=MatchValue(value=TEST_DB_ID))]),
        limit=100, with_payload=True, with_vectors=False)
    assert pts, "未找到测试分片"

    page_nos = sorted({p.payload.get("page_no") for p in pts})
    assert page_nos == [1, 2, 3], f"page_no 集合错误: {page_nos}"

    for p in pts:
        pl = p.payload
        assert pl.get("package") == "第2包", f"package 未写入: {pl.get('package')}"
        assert pl.get("bidder_name") == "自测投标人", "bidder_name 未写入"
        assert f"p{pl['page_no']}" in pl.get("chunk_id", ""), \
            f"chunk_id 未含页码: {pl.get('chunk_id')}"

    # 检索透传 page_no: 语义查询应命中文档且返回字段含 page_no
    if embedder:
        dense = embedder.encode_query_dense("废标 未密封 拒收")
        sparse = embedder.encode_query_sparse("废标 未密封 拒收")
        hits = vector_store.hybrid_search(dense, sparse, limit=10)
        mine = [h for h in hits if h.get("db_id") == TEST_DB_ID]
        assert mine, "测试文档未被检索命中"
        assert all("page_no" in h for h in mine), "检索结果未透传 page_no"
        p3 = [h for h in mine if h.get("page_no") == 3]
        assert p3, f"应命中第3页废标条款, 实际页码: {[h.get('page_no') for h in mine]}"

    deleted = delete_tender_document(TEST_DB_ID)
    print(f"PASS: {n} 分片, page_no={page_nos}, package/bidder_name 已写入, "
          f"检索透传页码且第3页废标条款命中; 清理 {deleted} 分片")
    return 0


if __name__ == "__main__":
    sys.exit(main())
