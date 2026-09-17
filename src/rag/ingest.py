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
