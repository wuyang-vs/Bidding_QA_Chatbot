"""按「项目编号+中标金额」去重，保留空值最少/发布最新的行"""
import argparse
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

SRC = PROJECT_ROOT / "data" / "raw" / "招标采购标的物信息提取训练数据_s.xlsx"
KEYS = ["项目编号", "中标金额"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--src", default=str(SRC))
    args = parser.parse_args()

    src = Path(args.src)
    if not src.exists():
        logger.error("源文件不存在: %s", src)
        return 1

    df = pd.read_excel(src, dtype=str)
    total = len(df)
    if total == 0:
        logger.warning("空文件，退出")
        return 1

    null_key_mask = df[KEYS].isnull().all(axis=1)
    null_rows = df[null_key_mask].copy()
    valid = df[~null_key_mask].copy()
    valid["_nulls"] = valid.isnull().sum(axis=1)
    if "发布时间" in valid.columns:
        valid = valid.sort_values("发布时间", ascending=False, na_position="last")
    valid = valid.sort_values("_nulls", kind="stable").drop_duplicates(subset=KEYS, keep="first")
    valid = valid.drop(columns=["_nulls"])

    result = pd.concat([valid, null_rows]).sort_index()
    removed = total - len(result)
    logger.info("去重: %d → %d（移除 %d，保留 %d 空键行）",
                total, len(result), removed, len(null_rows))

    if args.dry_run:
        return 0

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = src.with_name(f"{src.stem}_{ts}.xlsx")
    tmp = src.with_suffix(".tmp.xlsx")
    try:
        result.to_excel(tmp, index=False)
        shutil.copy2(src, backup)
        tmp.replace(src)
        logger.info("已保存 (备份: %s)", backup.name)
    except OSError as e:
        if tmp.exists():
            tmp.unlink()
        logger.error("保存失败: %s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
