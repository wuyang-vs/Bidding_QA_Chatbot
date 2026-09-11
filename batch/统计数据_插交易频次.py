"""统计标的物频次 → 输出两列 Excel"""
import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.logging_config import setup_logging
setup_logging()

import pandas as pd

logger = logging.getLogger(__name__)

SRC = PROJECT_ROOT / "data" / "processed" / "招标采购标的物信息提取训练数据_2_标的物.xlsx"
OUT = PROJECT_ROOT / "data" / "processed" / "标的物_交易频次.xlsx"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--src", default=str(SRC))
    parser.add_argument("-o", "--output", default=str(OUT))
    args = parser.parse_args()

    src = Path(args.src)
    if not src.exists():
        logger.error("源文件不存在: %s", src)
        return 1

    df = pd.read_excel(src, dtype=str)
    if "标的物" not in df.columns:
        logger.error("缺少「标的物」列")
        return 1

    subjects = df["标的物"].dropna().astype(str).str.strip()
    subjects = subjects[subjects != ""]
    if subjects.empty:
        logger.warning("标的物全为空，退出")
        return 1

    counts = subjects.value_counts().reset_index()
    counts.columns = ["标的物", "交易频次"]
    logger.info("统计 %d 个标的物，共 %d 条", len(counts), len(subjects))

    if args.dry_run:
        return 0

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    counts.to_excel(out, index=False)
    logger.info("已保存: %s", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
