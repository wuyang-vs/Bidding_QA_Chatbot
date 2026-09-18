"""Excel Q&A → Qdrant 导入 (支持元数据: source_file, section_title, doc_type, chunk_id)"""
import logging
from pathlib import Path

import pandas as pd

from src.rag.embedder import embedder
from src.rag.vector_store import vector_store

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# 元数据列映射 (Excel 列名 → payload 字段)
_META_COLS = {
    "source_file": ["source_file", "来源文件", "文件", "文档"],
    "section_title": ["section_title", "章节", "章节标题", "标题", "条款"],
    "doc_type": ["doc_type", "文档类型", "类型"],
    "chunk_id": ["chunk_id", "分片id", "切片id", "id"],
    "business_line": ["business_line", "业务线"],
}


def find_excel_files() -> list[Path]:
    """扫描 data/raw/ 下所有 Q&A Excel, 排除非问答格式文件."""
    results = []
    skip = {"test.xlsx", "ccgp_structured.xlsx"}
    for pat in ("*.xlsx", "*.xls"):
        for p in (DATA_DIR / "raw").glob(pat):
            if p.name.startswith("~$") or p.name in skip:
                continue
            results.append(p)
    return sorted(results)


def read_qa_data(path: Path) -> tuple[pd.DataFrame, dict]:
    """读取 Excel, 返回 (标准化 DataFrame, 元数据字段映射).
from __future__ import annotations
    
    DataFrame 保证有 question/answer 列, 可能额外有 source_file/section_title/doc_type/chunk_id.
    """
    df = pd.read_excel(path)
    col_map = {}
    for col in df.columns:
        c = str(col).strip().lower()
        if c in ("问", "问题", "question"):
            col_map[col] = "question"
        elif c in ("答", "答案", "answer"):
            col_map[col] = "answer"
    if col_map:
        df = df.rename(columns=col_map)
    else:
        df = df.iloc[:, :2]
        df.columns = ["question", "answer"]

    # 识别元数据列
    meta_found = {}
    for meta_key, aliases in _META_COLS.items():
        for col in df.columns:
            if str(col).strip().lower() in aliases:
                df = df.rename(columns={col: meta_key})
                meta_found[meta_key] = col
                break

    df = df.dropna(subset=["question", "answer"])
    df["question"] = df["question"].astype(str).str.strip()
    df["answer"] = df["answer"].astype(str).str.strip()
    df = df[(df["question"] != "") & (df["answer"] != "")]
    df = df.drop_duplicates(subset=["question"])
    df = df.reset_index(drop=True)

    # 默认 source_file = Excel 文件名
    if "source_file" not in df.columns:
        df["source_file"] = path.name

    return df, meta_found


def ingest_data(force: bool = True) -> bool:
    paths = find_excel_files()
    if not paths:
        logger.error("data/raw/ 下未找到 Excel 文件")
        return False

    all_dfs = []
    offset = 0
    for path in paths:
        logger.info("读取数据: %s", path.name)
        df, meta_found = read_qa_data(path)
        # 默认 business_line 从文件名推断
        if "business_line" not in df.columns:
            fname = path.stem.lower()
            if "regulation" in fname or "法规" in fname:
                df["business_line"] = "regulation"
            elif "enterprise" in fname or "企业" in fname:
                df["business_line"] = "enterprise"
            else:
                df["business_line"] = "bidding"
        # 默认 source_file
        if "source_file" not in df.columns or df["source_file"].isna().all():
            df["source_file"] = path.name
        df["_global_id"] = range(offset, offset + len(df))
        offset += len(df)
        all_dfs.append(df)
        logger.info("  -> %s: %d 条 (业务线: %s)", path.name, len(df),
                     df["business_line"].iloc[0] if "business_line" in df.columns else "unknown")

    df = pd.concat(all_dfs, ignore_index=True)
    logger.info("总计有效 Q&A: %d 条", len(df))

    # 编码 question+answer 拼接文本
    combined_texts = (df["question"] + " " + df["answer"]).tolist()
    embedder.fit_sparse(combined_texts)
    embedder.save_vocab()
    vector_store.create_collection(force=force)

    points = []
    for _, row in df.iterrows():
        try:
            combined = row["question"] + " " + row["answer"]
            dense = embedder.encode_document_dense(combined)
            sparse = embedder.encode_document_sparse(combined)
            point = {
                "id": int(row["_global_id"]),
                "dense": dense,
                "sparse": sparse,
                "question": row["question"],
                "answer": row["answer"],
            }
            for meta_key in ("source_file", "section_title", "doc_type", "chunk_id", "business_line"):
                if meta_key in row.index and pd.notna(row[meta_key]):
                    point[meta_key] = str(row[meta_key])
            points.append(point)
        except Exception as e:
            logger.warning("编码失败: %s", e)
    vector_store.upsert_points(points)
    logger.info("写入 Qdrant: %d 点", vector_store.count())
    embedder.save_vocab()
    return True


# ---------- 招标文件 (上传文档) 入库 ----------
# 招标文件分片使用独立 ID 段, 避免与 FAQ 数据 (从 0 起) 冲突
_TENDER_ID_BASE = 10_000_000
_TENDER_ID_SLOTS = 10_000
_CHUNK_SIZE = 500
_CHUNK_OVERLAP = 80


def _chunk_tender_text(text: str, size: int = _CHUNK_SIZE,
                       overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """按行聚合的滑动窗口分片, 尽量不切断条款行."""
    lines = [ln.strip() for ln in (text or "").splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines:
        return []
    chunks: list[str] = []
    buf = ""
    for ln in lines:
        candidate = (buf + "\n" + ln) if buf else ln
        if len(candidate) <= size:
            buf = candidate
        else:
            if buf:
                chunks.append(buf)
            # 超长行硬切; 否则以当前行开启新块, 带上上一块尾部做重叠
            tail = buf[-overlap:] if buf and len(buf) > overlap else ""
            buf = (tail + "\n" + ln) if tail else ln
            while len(buf) > size:
                chunks.append(buf[:size])
                buf = buf[size - overlap:]
    if buf:
        chunks.append(buf)
    return chunks


def _heading_of(chunk: str) -> str:
    """取分片中首个短行作为章节/条款标题."""
    for ln in chunk.splitlines():
        ln = ln.strip()
        if ln and len(ln) <= 40:
            return ln
    return chunk[:30].replace("\n", " ")


def ingest_tender_document(db_id: int, raw_text: str,
                           source_file: str = "", project_name: str = "",
                           pages: list[dict] | None = None,
                           package: str = "", bidder_name: str = "",
                           visibility: str = "public",
                           owner_id: int | None = None) -> int:
    """把一份上传的招标/投标文件全文分片 → dense+sparse 向量 → upsert 到 Qdrant.

    重传同 db_id 时先删旧分片. 返回写入分片数.

    元数据:
      pages: [{"page_no": 1 起或 None, "text": ...}] — PDF 按页保留真实页码,
             扫描 OCR 页同样带页码; 其他格式 page_no=None (不伪造页码).
      package: 包件号/包件名 (多包件项目人工或抽取后传入).
      bidder_name: 投标文件归属的投标人 (招标文件留空).
    """
    if not vector_store.collection_exists():
        vector_store.create_collection(force=False)

    # 去旧分片
    deleted = vector_store.delete_by_payload("db_id", int(db_id))
    if deleted:
        logger.info("招标文件 #%s 清理旧分片 %d 个", db_id, deleted)

    # 页感知分片: (chunk_text, page_no); 无 pages 时退回全文滑窗 (页码未知)
    if pages:
        page_chunks: list[tuple[str, int | None]] = []
        for pg in pages:
            for ch in _chunk_tender_text(pg.get("text") or ""):
                page_chunks.append((ch, pg.get("page_no")))
    else:
        page_chunks = [(ch, None) for ch in _chunk_tender_text(raw_text)]
    chunks = [c for c, _ in page_chunks]
    if not chunks:
        logger.warning("招标文件 #%s 无有效文本, 跳过向量化", db_id)
        return 0

    embedder.fit_sparse(chunks)
    embedder.save_vocab()

    title = project_name or source_file or f"tender_doc_{db_id}"
    points = []
    for i, (ch, page_no) in enumerate(page_chunks):
        heading = _heading_of(ch)
        combined = f"{heading}\n{ch}"
        point = {
            "id": _TENDER_ID_BASE + int(db_id) * _TENDER_ID_SLOTS + i,
            "dense": embedder.encode_document_dense(combined),
            "sparse": embedder.encode_document_sparse(combined),
            "question": f"【招标文件】{title} - {heading}",
            "answer": ch,
            "source_file": source_file or f"tender_doc_{db_id}",
            "section_title": heading,
            "doc_type": "tender_document",
            "chunk_id": f"tender-{db_id}-p{page_no if page_no is not None else 'x'}-{i}",
            "business_line": "tender",
            "db_id": int(db_id),
        }
        if page_no is not None:
            point["page_no"] = int(page_no)
        if package:
            point["package"] = package[:100]
        if bidder_name:
            point["bidder_name"] = bidder_name[:100]
        # 行级访问控制: visibility=public/internal + owner_id
        point["visibility"] = visibility if visibility == "internal" else "public"
        if owner_id is not None:
            point["owner_id"] = int(owner_id)
        points.append(point)
    vector_store.upsert_points(points)
    logger.info("招标文件 #%s《%s》写入 %d 个分片 (有页码分片 %d 个%s%s), Qdrant 总点数=%d",
                db_id, title[:30], len(points),
                sum(1 for _, pn in page_chunks if pn is not None),
                f", 包件={package}" if package else "",
                f", 投标人={bidder_name}" if bidder_name else "",
                vector_store.count())
    return len(points)


def delete_tender_document(db_id: int) -> int:
    """删除某份招标文件的全部分片."""
    return vector_store.delete_by_payload("db_id", int(db_id))


def backfill_access_metadata() -> dict:
    """一次性回填存量分片的 visibility/owner_id (幂等).

    - FAQ 等无 db_id 的分片 → public
    - 招标分片按 PG bidding_documents 的 owner_id/visibility 对齐
    新分片在 ingest 时已自带字段, 本函数随服务启动执行, 收敛后为空操作.
    """
    stats = {"faq_public": 0, "tender_aligned": 0, "tender_public_fallback": 0}
    try:
        c = vector_store._get_client()
        from src.config import settings as _s
        pending: list = []
        offset = None
        while True:
            pts, offset = c.scroll(
                _s.qdrant_collection, limit=512, offset=offset,
                with_payload=True, with_vectors=False)
            pending.extend(pts)
            if offset is None:
                break
        missing = [p for p in pending if "visibility" not in (p.payload or {})]
        if not missing:
            return stats

        # PG 文档权限映射 (表小, 一次取全)
        doc_map: dict[int, dict] = {}
        try:
            from src.database.postgresql_client import postgresql_client
            if postgresql_client.ready:
                for r in postgresql_client._run(
                        "SELECT id, owner_id, visibility FROM bidding_documents", {}):
                    doc_map[int(r["id"])] = r
        except Exception as e:
            logger.warning("回填: 读取文档权限失败, 招标分片按 public 兜底: %s", e)

        # FAQ 类 → public
        faq_ids = [p.id for p in missing if (p.payload or {}).get("db_id") is None]
        for i in range(0, len(faq_ids), 256):
            c.set_payload(_s.qdrant_collection, {"visibility": "public"},
                          points=faq_ids[i:i + 256])
        stats["faq_public"] = len(faq_ids)

        # 招标分片 → 按 DB 对齐
        for p in missing:
            pl = p.payload or {}
            db_id = pl.get("db_id")
            if db_id is None:
                continue
            doc = doc_map.get(int(db_id))
            if doc:
                payload = {
                    "visibility": doc.get("visibility") or "public",
                }
                if doc.get("owner_id") is not None:
                    payload["owner_id"] = int(doc["owner_id"])
                stats["tender_aligned"] += 1
            else:
                payload = {"visibility": "public"}
                stats["tender_public_fallback"] += 1
            c.set_payload(_s.qdrant_collection, payload, points=[p.id])
        if any(stats.values()):
            logger.info("分片访问权限回填完成: %s", stats)
    except Exception as e:
        logger.warning("backfill_access_metadata 失败 (不阻断启动): %s", e)
    return stats
