# -*- coding: utf-8 -*-
"""数据库结构/数据证据采集."""
import io, json, sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from src.database.postgresql_client import postgresql_client

postgresql_client.initialize()
ev = {}

# 1. 表清单
rows = postgresql_client._run("""
    SELECT tablename FROM pg_tables
    WHERE schemaname='public' ORDER BY tablename
""")
ev["tables"] = [r["tablename"] for r in rows]

# 2. users
rows = postgresql_client._run("SELECT id, username, role, display_name, created_at FROM users ORDER BY id")
ev["users"] = [{"id": r["id"], "username": r["username"], "role": r["role"],
                "display_name": r["display_name"]} for r in rows]

# 3. 文档数
rows = postgresql_client._run("SELECT COUNT(*) AS c FROM bidding_documents")
ev["documents_count"] = rows[0]["c"]

# 4. 复核记录
rows = postgresql_client._run("""
    SELECT id, document_id, review_type, verdict, reviewer, user_id, created_at
    FROM document_reviews ORDER BY id DESC LIMIT 10
""")
ev["reviews_total"] = postgresql_client._run("SELECT COUNT(*) AS c FROM document_reviews")[0]["c"]
ev["reviews_latest"] = [{"id": r["id"], "type": r["review_type"], "verdict": r["verdict"],
                          "reviewer": r["reviewer"], "user_id": r["user_id"]} for r in rows]

# 5. document_reviews 列结构 (验证 user_id 外键)
rows = postgresql_client._run("""
    SELECT column_name, data_type FROM information_schema.columns
    WHERE table_name='document_reviews' ORDER BY ordinal_position
""")
ev["reviews_columns"] = [r["column_name"] for r in rows]

# 6. 测试文档关键字段
rows = postgresql_client._run("""
    SELECT id, source_file, project_name, budget, deadline,
           jsonb_array_length(COALESCE(qualification_requirements,'[]'::jsonb)) AS qr_count,
           length(scoring_criteria) AS sc_len, text_length, parse_status
    FROM bidding_documents WHERE id=6
""")
if rows:
    r = rows[0]
    ev["doc_6"] = {"id": r["id"], "source_file": r["source_file"],
                   "project_name": r["project_name"], "budget": r["budget"],
                   "deadline": r["deadline"], "qualification_count": r["qr_count"],
                   "scoring_text_len": r["sc_len"], "text_length": r["text_length"],
                   "parse_status": r["parse_status"]}

with open("tests/acceptance/db_evidence.json", "w", encoding="utf-8") as f:
    json.dump(ev, f, ensure_ascii=False, indent=2, default=str)
print(json.dumps(ev, ensure_ascii=False, indent=2, default=str))
