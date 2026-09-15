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
}


def find_excel_file() -> Path | None:
    for pat in ("*.xlsx", "*.xls"):
        for p in DATA_DIR.rglob(pat):
            if p.name.startswith("~$"):
                continue
            return p
    return None


def read_qa_data(path: Path) -> tuple[pd.DataFrame, dict]:
    """读取 Excel, 返回 (标准化 DataFrame, 元数据字段映射).
    
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
    path = find_excel_file()
    if path is None:
        logger.error("data/ 下未找到 Excel 文件")
        return False
    logger.info("读取数据: %s", path)
    df, meta_found = read_qa_data(path)
    logger.info("有效 Q&A: %d 条", len(df))
    logger.info("识别元数据列: %s", list(meta_found.keys()) or "无 (使用默认值)")

    embedder.fit_sparse(df["answer"].tolist())
    embedder.save_vocab()
    vector_store.create_collection(force=force)

    points = []
    for i, row in df.iterrows():
        try:
            dense = embedder.encode_document_dense(row["answer"])
            sparse = embedder.encode_document_sparse(row["answer"])
            point = {
                "id": i,
                "dense": dense,
                "sparse": sparse,
                "question": row["question"],
                "answer": row["answer"],
            }
            # 元数据
            for meta_key in ("source_file", "section_title", "doc_type", "chunk_id"):
                if meta_key in row.index and pd.notna(row[meta_key]):
                    point[meta_key] = str(row[meta_key])
            points.append(point)
        except Exception as e:
            logger.warning("第 %d 行编码失败: %s", i, e)
    vector_store.upsert_points(points)
    logger.info("写入 Qdrant: %d 点", vector_store.count())
    embedder.save_vocab()
    return True
