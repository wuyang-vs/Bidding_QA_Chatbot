"""Recall@K / MRR / NDCG / Complete@5 评测脚本 (支持业务线分层).

使用方式:
  # 1. 使用 ground truth JSON 运行评测:
  #    python eval/recall_eval.py --gt eval/ground_truth.json --top-k 5
  #
  # 2. 自举模式:
  #    python eval/recall_eval.py --bootstrap --top-k 5
  #
  评测结果会输出到 eval/outputs/ 目录, 包含:
    - eval_summary.json: 汇总指标 (总体 + 按业务线 + 按问题类型)
    - eval_details.csv: 逐题详情 (question, retrieved, hit, recall)
    - sha256: 语料快照 hash (可追溯)
"""
import argparse
import csv
import datetime
import hashlib
import json
import logging
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

import pandas as pd
from src.rag.pipeline import rag_pipeline
from src.rag.vector_store import vector_store

EVAL_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = EVAL_DIR / "outputs"


def compute_recall_at_k(retrieved_ids: set, gt_ids: set, k: int) -> float:
    if not gt_ids:
        return 0.0
    hits = len(retrieved_ids & gt_ids)
    return hits / len(gt_ids)


def compute_mrr(retrieved_ordered: list, gt_ids: set) -> float:
    for rank, rid in enumerate(retrieved_ordered, 1):
        if rid in gt_ids:
            return 1.0 / rank
    return 0.0


def compute_ndcg_at_k(retrieved_ordered: list, gt_ids: set, k: int) -> float:
    dcg = 0.0
    for rank, rid in enumerate(retrieved_ordered[:k], 1):
        if rid in gt_ids:
            dcg += 1.0 / math.log2(rank + 1)
    idcg = 0.0
    for rank in range(1, min(len(gt_ids), k) + 1):
        idcg += 1.0 / math.log2(rank + 1)
    return dcg / idcg if idcg > 0 else 0.0


def compute_complete_at_k(retrieved_ordered: list, gt_ids: set, k: int) -> float:
    """Complete@K: top-K 结果是否包含所有 gt_ids (1.0 or 0.0)."""
    if not gt_ids:
        return 0.0
    return 1.0 if gt_ids.issubset(set(retrieved_ordered[:k])) else 0.0


def run_eval(ground_truth: list[dict], top_k: int = 5) -> dict:
    if not rag_pipeline.ready:
        rag_pipeline.initialize()

    k_values = [1, 3, 5, 10, 20]
    k_values = [k for k in k_values if k <= top_k]

    # 总体指标
    all_metrics = defaultdict(list)
    # 分层指标
    by_bl = defaultdict(lambda: defaultdict(list))  # business_line -> metric -> [vals]
    by_qt = defaultdict(lambda: defaultdict(list))  # question_type -> metric -> [vals]
    # 逐题详情
    details = []

    for i, item in enumerate(ground_truth):
        q = item["question"]
        bl = item.get("business_line", "unknown")
        qt = item.get("question_type", "exact")
        results = rag_pipeline.search(q, top_k=top_k)

        # 解析 gt_ids: 通过 gt_question 匹配
        gt_ids = set()
        gt_q = item.get("gt_question", q)
        for r in results:
            if r.get("question") == gt_q:
                gt_ids.add(r.get("id"))

        retrieved_ids = [r.get("id") for r in results]
        retrieved_set = set(retrieved_ids)

        # 各指标
        for k in k_values:
            rk = set(retrieved_ids[:k])
            recall_k = compute_recall_at_k(rk, gt_ids, k)
            key = f"Recall@{k}"
            all_metrics[key].append(recall_k)
            by_bl[bl][key].append(recall_k)
            by_qt[qt][key].append(recall_k)

        mrr = compute_mrr(retrieved_ids, gt_ids)
        all_metrics["MRR"].append(mrr)
        by_bl[bl]["MRR"].append(mrr)
        by_qt[qt]["MRR"].append(mrr)

        ndcg = compute_ndcg_at_k(retrieved_ids, gt_ids, top_k)
        ndcg_key = f"NDCG@{top_k}"
        all_metrics[ndcg_key].append(ndcg)
        by_bl[bl][ndcg_key].append(ndcg)
        by_qt[qt][ndcg_key].append(ndcg)

        complete = compute_complete_at_k(retrieved_ids, gt_ids, top_k)
        complete_key = f"Complete@{top_k}"
        all_metrics[complete_key].append(complete)
        by_bl[bl][complete_key].append(complete)
        by_qt[qt][complete_key].append(complete)

        hit = 1.0 if (gt_ids & retrieved_set) else 0.0
        all_metrics["HitRate"].append(hit)
        by_bl[bl]["HitRate"].append(hit)
        by_qt[qt]["HitRate"].append(hit)

        details.append({
            "question": q[:100],
            "gt_question": gt_q[:100],
            "business_line": bl,
            "question_type": qt,
            "hit": bool(hit),
            "retrieved_top1": results[0].get("question", "")[:60] if results else "",
            "recall@5": recall_k if 5 in k_values else None,
        })

        if (i + 1) % 50 == 0:
            logging.info("  %d/%d 题已测...", i + 1, len(ground_truth))

    # 汇总
    def avg(d, key):
        vals = d.get(key, [])
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    summary = {"总体": {}}
    for key in all_metrics:
        summary["总体"][key] = avg(all_metrics, key)
    summary["总体"]["样本数"] = len(ground_truth)

    # 按业务线
    summary["按业务线"] = {}
    for bl, metrics in by_bl.items():
        summary["按业务线"][bl] = {k: avg(metrics, k) for k in metrics}
        summary["按业务线"][bl]["样本数"] = len(next(iter(metrics.values()))) if metrics else 0

    # 按问题类型
    summary["按问题类型"] = {}
    for qt, metrics in by_qt.items():
        summary["按问题类型"][qt] = {k: avg(metrics, k) for k in metrics}
        summary["按问题类型"][qt]["样本数"] = len(next(iter(metrics.values()))) if metrics else 0

    summary["metadata"] = {
        "total_questions": len(ground_truth),
        "top_k": top_k,
        "timestamp": datetime.datetime.now().isoformat(),
        "corpus_size": vector_store.count() if rag_pipeline.ready else 0,
    }

    return summary, details


def bootstrap_from_excel(excel_path: Path) -> list[dict]:
    """自举 ground truth: 用 corpus 每条 question 作为 query."""
    df = pd.read_excel(excel_path)
    col_map = {}
    for col in df.columns:
        c = str(col).strip().lower()
        if c in ("问", "问题", "question"):
            col_map[col] = "question"
        elif c in ("答", "答案", "answer"):
            col_map[col] = "answer"
    if col_map:
        df = df.rename(columns=col_map)
    gt = []
    for i, row in df.iterrows():
        gt.append({
            "question": str(row.get("question", "")),
            "gt_question": str(row.get("question", "")),
            "business_line": "bidding",
            "question_type": "exact",
        })
    return gt


def corpus_sha256() -> str:
    """计算语料文件 SHA256 (可追溯)."""
    h = hashlib.sha256()
    for fname in ("ccgp_qa.xlsx", "enterprise_qa.xlsx", "regulation_qa.xlsx"):
        p = EVAL_DIR.parent / "data" / "raw" / fname
        if p.exists():
            h.update(p.read_bytes())
            h.update(f"\n{fname}\n".encode())
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description="Recall@K 评测 (含业务线分层 + Complete@5)")
    parser.add_argument("--gt", type=str, default="eval/ground_truth.json", help="ground truth JSON")
    parser.add_argument("--bootstrap", action="store_true", help="自举模式")
    parser.add_argument("--excel", type=str, default=None, help="自举模式 Excel 路径")
    parser.add_argument("--top-k", type=int, default=5, help="评测 top_k (默认 5)")
    args = parser.parse_args()

    if args.gt:
        gt_raw = Path(args.gt)
        if gt_raw.is_absolute():
            gt_path = gt_raw
        elif gt_raw.parts and gt_raw.parts[0] == "eval":
            gt_path = EVAL_DIR.parent / gt_raw
        else:
            gt_path = EVAL_DIR / gt_raw
        ground_truth = json.loads(gt_path.read_text(encoding="utf-8"))
        logging.info("加载 ground truth: %d 题", len(ground_truth))
    elif args.bootstrap:
        excel_path = Path(args.excel) if args.excel else Path("data/test.xlsx")
        ground_truth = bootstrap_from_excel(excel_path)
        logging.info("自举 ground truth from %s: %d 题", excel_path, len(ground_truth))
    else:
        parser.error("必须指定 --gt 或 --bootstrap")
        return

    summary, details = run_eval(ground_truth, top_k=args.top_k)

    # 输出到 eval/outputs/
    OUTPUTS_DIR.mkdir(exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    # summary JSON
    summary["metadata"]["corpus_sha256"] = corpus_sha256()
    summary_path = OUTPUTS_DIR / f"eval_summary_{ts}.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    # symlink latest
    latest = OUTPUTS_DIR / "eval_summary_latest.json"
    if latest.exists():
        latest.unlink()
    latest.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # details CSV
    details_path = OUTPUTS_DIR / f"eval_details_{ts}.csv"
    with open(details_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(details[0].keys()) if details else [])
        writer.writeheader()
        writer.writerows(details)

    # 打印结果
    print("\n" + "=" * 60)
    print("Recall@K 评测结果")
    print("=" * 60)
    print(f"\n语料 SHA256: {summary['metadata']['corpus_sha256'][:16]}...")
    print(f"语料条数: {summary['metadata']['corpus_size']}")
    print(f"评测题数: {summary['metadata']['total_questions']}")
    print(f"Top-K: {args.top_k}")

    print(f"\n── 总体 ──")
    for key, val in summary["总体"].items():
        if isinstance(val, float):
            print(f"  {key:<15}: {val:.1%}")
        else:
            print(f"  {key:<15}: {val}")

    print(f"\n── 按业务线 ──")
    for bl, metrics in summary["按业务线"].items():
        print(f"  [{bl}]")
        for k, v in metrics.items():
            if isinstance(v, float):
                print(f"    {k:<15}: {v:.1%}")
            else:
                print(f"    {k:<15}: {v}")

    print(f"\n── 按问题类型 ──")
    for qt, metrics in summary["按问题类型"].items():
        print(f"  [{qt}]")
        for k, v in metrics.items():
            if isinstance(v, float):
                print(f"    {k:<15}: {v:.1%}")
            else:
                print(f"    {k:<15}: {v}")

    print(f"\n{'=' * 60}")
    print(f"产物: {summary_path}")
    print(f"      {details_path}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
