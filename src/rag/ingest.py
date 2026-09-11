"""Excel Q&A → Qdrant 导入"""
import logging
from pathlib import Path

import pandas as pd

from src.rag.embedder import embedder
from src.rag.vector_store import vector_store

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def find_excel_file() -> Path | None:
    for pat in ("*.xlsx", "*.xls"):
        for p in DATA_DIR.rglob(pat):
            if p.name.startswith("~$"):
                continue
            return p
    return None


def read_qa_data(path: Path) -> pd.DataFrame:
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
    df = df.dropna(subset=["question", "answer"])
    df["question"] = df["question"].astype(str).str.strip()
    df["answer"] = df["answer"].astype(str).str.strip()
    df = df[(df["question"] != "") & (df["answer"] != "")]
    df = df.drop_duplicates(subset=["question"])
    return df.reset_index(drop=True)


def ingest_data(force: bool = True) -> bool:
    path = find_excel_file()
    if path is None:
        logger.error("data/ 下未找到 Excel 文件")
        return False
    logger.info("读取数据: %s", path)
    df = read_qa_data(path)
    logger.info("有效 Q&A: %d 条", len(df))

    embedder.fit_sparse(df["answer"].tolist())
    embedder.save_vocab()
    vector_store.create_collection(force=force)

    points = []
    for i, row in df.iterrows():
        try:
            dense = embedder.encode_document_dense(row["answer"])
            sparse = embedder.encode_document_sparse(row["answer"])
            points.append({"id": i, "dense": dense, "sparse": sparse,
                           "question": row["question"], "answer": row["answer"]})
        except Exception as e:
            logger.warning("第 %d 行编码失败: %s", i, e)
    vector_store.upsert_points(points)
    logger.info("写入 Qdrant: %d 点", vector_store.count())
    embedder.save_vocab()
    return True
