"""提取项目名称 → 生成 batch request JSONL"""
import argparse
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.logging_config import setup_logging
setup_logging()

import pandas as pd

logger = logging.getLogger(__name__)

SRC = PROJECT_ROOT / "data" / "processed" / "招标采购标的物信息提取训练数据_2.xlsx"
OUT = PROJECT_ROOT / "data" / "batch" / "batch_requests.jsonl"

PROMPT_TEMPLATE = (
    "请从以下项目名称中，提取一个字段：核心标的物"
    "（只输出具体的商品或服务名称，不要包含公司名）。\n"
    "项目名称：'{name}'"
)


def build_request(custom_id: str, project_name: str) -> dict:
    return {
        "custom_id": custom_id,
        "method": "POST",
        "url": "/v4/chat/completions",
        "body": {
            "model": "glm-4.7-flash",
            "temperature": 0,
            "messages": [{"role": "user", "content": PROMPT_TEMPLATE.format(name=project_name)}],
        },
    }


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
    if "项目名称" not in df.columns:
        logger.error("缺少「项目名称」列")
        return 1

    names = df["项目名称"].dropna().astype(str).str.strip()
    names = names[names != ""].drop_duplicates()
    if names.empty:
        logger.warning("无有效项目名称")
        return 1

    lines = [json.dumps(build_request(f"request-{i+1}", n), ensure_ascii=False)
             for i, n in enumerate(names)]

    logger.info("生成 %d 条 batch 请求", len(lines))
    if args.dry_run:
        logger.info("[dry-run] 首条: %s", lines[0][:120])
        return 0

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("已保存: %s", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
