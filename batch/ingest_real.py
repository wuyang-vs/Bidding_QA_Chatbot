"""真实招投标 Q&A Excel → Qdrant 导入（增强版）

功能:
  - --src 指定 Excel 路径（绕过 data/ 首文件匹配，避免 test.xlsx 遮蔽）
  - --dry-run 只预览数据，不写 Qdrant
  - --no-force 增量追加（不删 collection），默认 force=True 全量重建
  - --batch-size 批量编码大小（默认 32）
  - tqdm 进度条 + 导入后统计（总/成功/失败/耗时/Qdrant 点数）

Excel 要求: 两列，列名含 question/answer 或 问/答（大小写不敏感，去空白匹配）
           若列名不符合，取前两列当作 question/answer

示例:
  python batch/ingest_real.py --src data/processed/real_qa.xlsx --dry-run
  python batch/ingest_real.py --src data/processed/real_qa.xlsx
  python batch/ingest_real.py --src data/processed/additional.xlsx --no-force
"""
import argparse
import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.logging_config import setup_logging
setup_logging()

import pandas as pd
from tqdm import tqdm

from src.rag.embedder import embedder
from src.rag.ingest import read_qa_data
from src.rag.vector_store import vector_store

logger = logging.getLogger(__name__)


def find_excel_files(data_dir: Path) -> list[Path]:
    """列出 data/ 下所有 .xlsx/.xls，排除临时文件"""
    files = []
    for pat in ("*.xlsx", "*.xls"):
        for p in data_dir.rglob(pat):
            if p.name.startswith("~$"):
                continue
            files.append(p)
    return sorted(files)


def preview(df: pd.DataFrame, src: Path) -> None:
    logger.info("=" * 60)
    logger.info("📂 数据源: %s", src)
    logger.info("📊 原始行数: %d", len(df))
    logger.info("🏷️  列名: %s", list(df.columns))
    logger.info("--- 前 3 条 ---")
    for i, row in df.head(3).iterrows():
        q = str(row["question"])[:80]
        a = str(row["answer"])[:80]
        logger.info("  [%d] Q: %s...", i, q)
        logger.info("       A: %s...", a)
    logger.info("=" * 60)


def batch_encode(documents: list[str], batch_size: int = 32) -> list[list[float]]:
    """批量 dense 编码（SentenceTransformer.encode 原生支持 list）"""
    model = embedder._load_dense()
    results: list[list[float]] = []
    for i in range(0, len(documents), batch_size):
        batch = documents[i : i + batch_size]
        embeddings = model.encode(batch, normalize_embeddings=True, show_progress_bar=False)
        results.extend(embeddings.tolist())
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="增强版 Qdrant 导入")
    parser.add_argument("--src", "-s", default=None,
                        help="Excel 路径；不填则列出 data/ 下所有 Excel 供选择")
    parser.add_argument("--dry-run", action="store_true",
                        help="只预览数据，不写入 Qdrant")
    parser.add_argument("--no-force", action="store_true",
                        help="增量追加，不删除 collection（默认 force=True 重建）")
    parser.add_argument("--batch-size", type=int, default=32,
                        help="批量编码大小（默认 32）")
    args = parser.parse_args()

    # ---- 解析源文件 ----
    data_dir = PROJECT_ROOT / "data"
    if args.src:
        src = Path(args.src)
        if not src.is_absolute():
            src = PROJECT_ROOT / src
        if not src.exists():
            logger.error("文件不存在: %s", src)
            return 1
    else:
        options = find_excel_files(data_dir)
        if not options:
            logger.error("data/ 下未找到任何 Excel，请用 --src 指定路径")
            return 1
        if len(options) == 1:
            src = options[0]
            logger.info("自动选择唯一 Excel: %s", src)
        else:
            logger.info("data/ 下有 %d 个 Excel，请用 --src 指定:", len(options))
            for i, o in enumerate(options):
                logger.info("  [%d] %s", i, o.relative_to(PROJECT_ROOT))
            return 1

    # ---- 读取 & 清洗 ----
    df = read_qa_data(src)
    if df.empty:
        logger.error("清洗后无有效数据，退出")
        return 1

    preview(df, src)

    if args.dry_run:
        logger.info("[dry-run] 不执行实际导入")
        return 0

    # ---- 初始化组件 ----
    logger.info("初始化嵌入模型 & Qdrant ...")
    t0 = time.time()

    # Sparse: 重建 vocab（全量）或增量 fit
    embedder.fit_sparse(df["answer"].tolist())
    embedder.save_vocab()

    force = not args.no_force
    if force:
        vector_store.create_collection(force=True)
        logger.info("Qdrant collection 已重建")
    else:
        if not vector_store.collection_exists():
            vector_store.create_collection(force=False)
            logger.info("Qdrant collection 不存在，已创建")
        logger.info("增量模式: 追加 %d 条", len(df))

    # ---- 批量编码 ----
    logger.info("批量编码 dense 向量 (batch=%d) ...", args.batch_size)
    dense_vecs = batch_encode(df["answer"].tolist(), batch_size=args.batch_size)
    logger.info("dense 编码完成: %d 条, 耗时 %.1fs", len(dense_vecs), time.time() - t0)

    # ---- 逐条 sparse + 组装 ----
    points = []
    failed = 0
    for i, (_, row) in enumerate(tqdm(df.iterrows(), total=len(df), desc="Sparse encode")):
        try:
            sparse = embedder.encode_document_sparse(row["answer"])
            points.append({
                "id": i,
                "dense": dense_vecs[i],
                "sparse": sparse,
                "question": row["question"],
                "answer": row["answer"],
            })
        except Exception as e:
            failed += 1
            logger.warning("第 %d 行 sparse 编码失败: %s", i, e)

    # ---- 写入 ----
    if not points:
        logger.error("无有效 points，写入中止")
        return 1

    logger.info("写入 Qdrant: %d points ...", len(points))
    vector_store.upsert_points(points)

    total_points = vector_store.count()
    elapsed = time.time() - t0
    logger.info("=" * 60)
    logger.info("✅ 导入完成")
    logger.info("   数据源:    %s", src)
    logger.info("   有效 Q&A:  %d", len(df))
    logger.info("   写入点数:  %d", len(points))
    logger.info("   失败行数:  %d", failed)
    logger.info("   增量模式:  %s", args.no_force)
    logger.info("   Qdrant 总数: %d", total_points)
    logger.info("   总耗时:    %.1fs", elapsed)
    logger.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
