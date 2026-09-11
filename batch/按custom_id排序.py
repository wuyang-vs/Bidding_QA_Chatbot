"""按 custom_id 数字排序 JSONL"""
import argparse
import json
import logging
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.logging_config import setup_logging
setup_logging()

logger = logging.getLogger(__name__)

SRC = PROJECT_ROOT / "data" / "batch" / "batch_results_raw.jsonl"
OUT = PROJECT_ROOT / "data" / "batch" / "batch_results_processed.jsonl"

_NUM_RE = re.compile(r"(\d+)")


def _cid_num(custom_id: str) -> int:
    m = _NUM_RE.search(custom_id or "")
    return int(m.group(1)) if m else 0


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

    parsed = []
    bad = 0
    for line in src.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            cid = obj.get("custom_id", "")
            parsed.append((cid, _cid_num(cid), line))
        except json.JSONDecodeError:
            bad += 1

    if not parsed:
        logger.warning("无有效行，退出")
        return 0

    parsed.sort(key=lambda x: x[1])
    lines = [p[2] for p in parsed]
    logger.info("有效 %d 行，坏行 %d 行", len(lines), bad)

    if args.dry_run:
        return 0

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("已保存 %d 行: %s", len(lines), out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
