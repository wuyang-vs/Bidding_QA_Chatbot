"""从 MySQL rag_cleaned + Qdrant 抽样原始内容，输出 JSONL 供后续 LLM 生成 Q&A。

用法:
    python scripts/sft/extract_sources.py

输出:
    scripts/sft/sources_legal.jsonl   — 法条 + 政策原文
    scripts/sft/sources_bid.jsonl     — 招标公告 + 中标公告 + 项目记录
    scripts/sft/sources_qdrant.jsonl  — Qdrant 209 篇招标文件 chunk
    scripts/sft/sources_seed.jsonl    — shenlan_qa.qa_pairs 80 条种子(直接用作 SFT)
"""
import json
import os
import random
import sys
from pathlib import Path

# 确保项目根目录在 sys.path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pymysql

random.seed(42)


def _load_env():
    """手动解析 .env (不依赖 python-dotenv)"""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip("'\"")
        if k and k not in os.environ:
            os.environ[k] = v


_load_env()
OUT_DIR = Path(__file__).resolve().parent


# ────────────────── MySQL 抽样 ──────────────────

def _mysql_conn():
    return pymysql.connect(
        host=os.environ["MYSQL_HOST"],
        port=int(os.environ["MYSQL_PORT"]),
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PWD"],
        charset="utf8mb4",
    )


def extract_legal(conn):
    """法条 + 政策原文 → sources_legal.jsonl"""
    cur = conn.cursor()
    items = []

    # 法律条文 (4772 条, 抽样 200 条)
    cur.execute("SELECT law_id, article_number, article_title, chapter, content_text "
                "FROM rag_cleaned.legal_articles ORDER BY RAND() LIMIT 200")
    for row in cur.fetchall():
        law_id, art_num, art_title, chapter, content = row
        if not content or len(content.strip()) < 20:
            continue
        items.append({
            "source": "legal_article",
            "law_id": law_id,
            "article_number": art_num,
            "title": art_title or "",
            "chapter": chapter or "",
            "content": content.strip(),
        })

    # 法律元数据补充法条上下文
    cur.execute("SELECT law_id, name_zh, law_type, publish_date FROM rag_cleaned.legal_metadata")
    law_map = {}
    for row in cur.fetchall():
        law_map[row[0]] = {"name": row[1], "type": row[2], "date": str(row[3])}
    for item in items:
        if item["law_id"] in law_map:
            meta = law_map[item["law_id"]]
            item["law_name"] = meta["name"]
            item["law_type"] = meta["type"]

    # 政策全文 (42 条, 全取)
    cur.execute("SELECT title, content, release_time, imple_time FROM rag_cleaned.policy_政策全文")
    for row in cur.fetchall():
        title, content, rel, impl = row
        if not content or len(content.strip()) < 20:
            continue
        items.append({
            "source": "policy_full",
            "title": title or "",
            "content": content.strip(),
            "release_time": str(rel) if rel else "",
            "imple_time": str(impl) if impl else "",
        })

    # 政策文件索引 (371 条, 抽样 50 条)
    cur.execute("SELECT policy_name, publish_date, source_url FROM rag_cleaned.policy_政策文件 "
                "ORDER BY RAND() LIMIT 50")
    for row in cur.fetchall():
        name, date, url = row
        items.append({
            "source": "policy_index",
            "title": name or "",
            "publish_date": str(date) if date else "",
            "source_url": url or "",
            "content": name or "",  # 索引行内容有限, 作为补充
        })

    cur.close()
    _write_jsonl("sources_legal.jsonl", items)
    print(f"[legal] {len(items)} 条 → sources_legal.jsonl")
    return items


def extract_bid(conn):
    """招标公告 + 中标公告 + 项目记录 → sources_bid.jsonl"""
    cur = conn.cursor()
    items = []

    # 招标公告 (6908 条, 抽样 200 条)
    cur.execute("SELECT title, name, type, stage, date_str, source "
                "FROM rag_cleaned.bid_招标公告_ods_tender_ ORDER BY RAND() LIMIT 200")
    for row in cur.fetchall():
        title, name, typ, stage, date, src = row
        content_parts = [p for p in [title, name, typ, stage, date, src] if p]
        content = " | ".join(content_parts)
        if len(content.strip()) < 10:
            continue
        items.append({
            "source": "tender_notice",
            "title": title or "",
            "name": name or "",
            "type": typ or "",
            "stage": stage or "",
            "content": content,
        })

    # 中标公告 (1879 条, 抽样 100 条)
    cur.execute("SELECT notice_type, tender_number, successful_bidder, awarded_amount, "
                "tendering_entity FROM rag_cleaned.bid_中标公告 ORDER BY RAND() LIMIT 100")
    for row in cur.fetchall():
        ntype, tnum, winner, amount, entity = row
        content_parts = [p for p in [ntype, tnum, winner, amount, entity] if p]
        content = " | ".join(content_parts)
        if len(content.strip()) < 10:
            continue
        items.append({
            "source": "win_notice",
            "notice_type": ntype or "",
            "tender_number": tnum or "",
            "winner": winner or "",
            "awarded_amount": str(amount) if amount else "",
            "tendering_entity": entity or "",
            "content": content,
        })

    # 项目记录 (3315 条, 抽样 100 条)
    cur.execute("SELECT project_name, publish_date, category, source, province, city, district "
                "FROM rag_cleaned.bid_招标项目记录 ORDER BY RAND() LIMIT 100")
    for row in cur.fetchall():
        pname, pdate, cat, src, prov, city, dist = row
        content_parts = [p for p in [pname, pdate, cat, prov, city, dist] if p]
        content = " | ".join(content_parts)
        if len(content.strip()) < 10:
            continue
        items.append({
            "source": "project_record",
            "project_name": pname or "",
            "category": cat or "",
            "province": prov or "",
            "city": city or "",
            "content": content,
        })

    cur.close()
    _write_jsonl("sources_bid.jsonl", items)
    print(f"[bid] {len(items)} 条 → sources_bid.jsonl")
    return items


def extract_seed(conn):
    """shenlan_qa.qa_pairs 80 条种子 → sources_seed.jsonl (直接用作 SFT)"""
    cur = conn.cursor()
    cur.execute("SELECT question, answer FROM shenlan_qa.qa_pairs")
    items = []
    for q, a in cur.fetchall():
        if not q or not a or len(a.strip()) < 20:
            continue
        items.append({"question": q.strip(), "answer": a.strip()})
    cur.close()
    _write_jsonl("sources_seed.jsonl", items)
    print(f"[seed] {len(items)} 条 → sources_seed.jsonl")
    return items


# ────────────────── Qdrant 抽样 ──────────────────

def extract_qdrant():
    """从 Qdrant 按 source_file 聚合抽样 chunk → sources_qdrant.jsonl"""
    try:
        from qdrant_client import QdrantClient
    except ImportError:
        print("[qdrant] qdrant-client 未安装, 跳过")
        return []

    url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    api_key = os.environ.get("QDRANT_API_KEY") or None
    collection = os.environ.get("QDRANT_COLLECTION", "bid_qa_v2")
    client = QdrantClient(url=url, api_key=api_key, timeout=30)

    # scroll 取一批 chunk (取 2000 条, 按 source_file 聚合后每文件取前 3 段)
    all_points = []
    offset = None
    while len(all_points) < 2000:
        points, offset = client.scroll(
            collection_name=collection,
            limit=100,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        if not points:
            break
        all_points.extend(points)
        if offset is None:
            break

    # 按 source_file 分组
    by_source = {}
    for pt in all_points:
        payload = pt.payload or {}
        sf = payload.get("source_file", "unknown")
        by_source.setdefault(sf, []).append(payload)

    # 每个文件取前 3 段 (内容最长的)
    items = []
    for sf, chunks in by_source.items():
        chunks.sort(key=lambda c: len(c.get("answer", c.get("question", ""))), reverse=True)
        for chunk in chunks[:3]:
            question = chunk.get("question", "")
            answer = chunk.get("answer", "")
            content = answer if answer else question
            if not content or len(content.strip()) < 30:
                continue
            items.append({
                "source": "qdrant_chunk",
                "source_file": sf,
                "doc_type": chunk.get("doc_type", ""),
                "section_title": chunk.get("section_title", ""),
                "question": question,
                "content": content.strip()[:2000],  # 截断, 避免太长
            })
        if len(items) >= 300:
            break

    _write_jsonl("sources_qdrant.jsonl", items)
    print(f"[qdrant] {len(items)} 条 (来自 {len(by_source)} 个文件) → sources_qdrant.jsonl")
    return items


# ────────────────── 工具 ──────────────────

def _write_jsonl(filename: str, items: list):
    path = OUT_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    print("=" * 50)
    print("SFT 数据源抽取")
    print("=" * 50)

    # MySQL
    conn = _mysql_conn()
    try:
        extract_legal(conn)
        extract_bid(conn)
        extract_seed(conn)
    finally:
        conn.close()

    # Qdrant
    try:
        extract_qdrant()
    except Exception as e:
        print(f"[qdrant] 抽取失败: {e}")

    print("\n抽取完成。输出文件在:", OUT_DIR)
