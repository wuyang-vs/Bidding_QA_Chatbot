# -*- coding: utf-8 -*-
"""把已入库但未向量化的存量招标文件补建 Qdrant 索引 (一次性回填)."""
import io, os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from src.database.postgresql_client import postgresql_client
from src.rag.ingest import ingest_tender_document
from src.rag.vector_store import vector_store

postgresql_client.initialize()
rows = postgresql_client._run(
    "SELECT id, source_file, project_name, raw_text, text_length "
    "FROM bidding_documents ORDER BY id")
print(f"存量文档 {len(rows)} 份, 回填前 Qdrant 点数: {vector_store.count()}")
total = 0
for r in rows:
    text = r.get("raw_text") or ""
    if not text:
        print(f"  #{r['id']} {r.get('source_file','')}: 无 raw_text, 跳过")
        continue
    n = ingest_tender_document(r["id"], text,
                               source_file=r.get("source_file") or "",
                               project_name=r.get("project_name") or "")
    total += n
    print(f"  #{r['id']} {r.get('source_file','')[:40]}: {n} 分片")
print(f"回填完成, 新增 {total} 分片, Qdrant 总点数: {vector_store.count()}")
