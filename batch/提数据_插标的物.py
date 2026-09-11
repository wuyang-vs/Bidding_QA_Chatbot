"""从 batch 结果 JSONL 提取标的物，按行序插入 Excel"""
import argparse
import json
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.logging_config import setup_logging
setup_logging()

import pandas as pd

logger = logging.getLogger(__name__)

JSONL = PROJECT_ROOT / "data" / "batch" / "batch_results_processed.jsonl"
EXCEL = PROJECT_ROOT / "data" / "processed" / "招标采购标的物信息提取训练数据_2_标的物.xlsx"


def extract_subjects(jsonl_path: Path) -> list[str]:
    items = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            items.append("")
            continue
        try:
            content = obj["response"]["body"]["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            content = ""
        items.append(content.strip().replace("\n", ""))
    return items


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--jsonl", default=str(JSONL))
    parser.add_argument("--excel", default=str(EXCEL))
    args = parser.parse_args()

    jsonl_path, excel_path = Path(args.jsonl), Path(args.excel)
    if not jsonl_path.exists() or not excel_path.exists():
        logger.error("输入文件缺失")
        return 1

    subjects = extract_subjects(jsonl_path)
    df = pd.read_excel(excel_path, dtype=str)

    if len(subjects) != len(df):
        logger.error("行数不匹配: JSONL %d vs Excel %d", len(subjects), len(df))
        return 1

    df["标的物"] = subjects
    filled = sum(1 for s in subjects if s)
    logger.info("填充 %d/%d 条", filled, len(subjects))

    if args.dry_run:
        return 0

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = excel_path.with_name(f"{excel_path.stem}_{ts}.xlsx")
    tmp = excel_path.with_suffix(".tmp.xlsx")
    try:
        df.to_excel(tmp, index=False)
        shutil.copy2(excel_path, backup)
        tmp.replace(excel_path)
        logger.info("已保存 (备份: %s)", backup.name)
    except OSError as e:
        if tmp.exists():
            tmp.unlink()
        logger.error("保存失败: %s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
