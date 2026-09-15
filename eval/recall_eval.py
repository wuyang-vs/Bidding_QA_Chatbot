"""Recall@K / MRR / NDCG 评测脚本.

使用方式:
  # 1. 准备 ground truth JSON, 格式:
  #    [{"question": "...", "gt_question": "...", "gt_ids": [0, 3]}, ...]
  #    gt_ids 是 Qdrant 中正确文档的 id; 如果只有 gt_question, 会用 question 匹配
  #
  # 2. 运行评测:
  #    python eval/recall_eval.py --gt eval/ground_truth.json --top-k 20
  #
  # 3. 自举模式 (没有标注集时, 用 corpus[i] 的 question 自举):
  #    python eval/recall_eval.py --bootstrap --top-k 20
"""
import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

import pandas as pd
from src.rag.pipeline import rag_pipeline


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
    # 简化版: 假设所有 gt 相关度 = 1
    dcg = 0.0
    for rank, rid in enumerate(retrieved_ordered[:k], 1):
        if rid in gt_ids:
            dcg += 1.0 / __import__("math").log2(rank + 1)
    # 理想排序: 所有 gt 在最前面
    idcg = 0.0
    for rank in range(1, min(len(gt_ids), k) + 1):
        idcg += 1.0 / __import__("math").log2(rank + 1)
    return dcg / idcg if idcg > 0 else 0.0


def run_eval(ground_truth: list[dict], top_k: int = 20) -> dict:
    if not rag_pipeline.ready:
        rag_pipeline.initialize()

    metrics = {f"Recall@{k}": [] for k in (1, 5, 10, 20, 50) if k <= top_k}
    metrics["MRR"] = []
    metrics[f"NDCG@{top_k}"] = []
    hit_count = 0

    for i, item in enumerate(ground_truth):
        q = item["question"]
        results = rag_pipeline.search(q, top_k=top_k)

        # 解析 gt_ids
        gt_ids = set(item.get("gt_ids", []))
        if not gt_ids and "gt_question" in item:
            # 用 question 匹配
            gt_q = item["gt_question"]
            for r in results:
                if r.get("question") == gt_q:
                    gt_ids.add(r.get("id"))
            # 如果 results 里没搜到, 说明 gt_q 不在 top_k 内,  recall=0

        # retrieved ids
        retrieved_ids = [r.get("id") for r in results]
        retrieved_set = set(retrieved_ids)

        # Recall@K
        for k in metrics:
            if k.startswith("Recall@"):
                k_val = int(k.split("@")[1])
                retrieved_k = set(retrieved_ids[:k_val])
                metrics[k].append(compute_recall_at_k(retrieved_k, gt_ids, k_val))

        # MRR
        metrics["MRR"].append(compute_mrr(retrieved_ids, gt_ids))

        # NDCG
        ndcg_key = f"NDCG@{top_k}"
        metrics[ndcg_key].append(compute_ndcg_at_k(retrieved_ids, gt_ids, top_k))

        # Hit Rate (top_k 是否至少命中 1 个)
        if gt_ids & retrieved_set:
            hit_count += 1

        if (i + 1) % 10 == 0:
            logging.info("  %d/%d 题已测...", i + 1, len(ground_truth))

    n = len(ground_truth)
    summary = {}
    for key, vals in metrics.items():
        if vals:
            summary[key] = round(sum(vals) / len(vals), 4)
    summary["HitRate"] = round(hit_count / n, 4) if n > 0 else 0.0
    summary["样本数"] = n

    return summary


def bootstrap_from_excel(excel_path: Path) -> list[dict]:
    """自举 ground truth: 用 corpus 每条 question 作为 query, gt_ids = 它自己的 id."""
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
        gt.append({"question": str(row.get("question", "")), "gt_ids": [i]})
    return gt


def main():
    parser = argparse.ArgumentParser(description="Recall@K 评测")
    parser.add_argument("--gt", type=str, help="ground truth JSON 文件路径")
    parser.add_argument("--bootstrap", action="store_true", help="从 data/test.xlsx 自举 ground truth")
    parser.add_argument("--excel", type=str, default=None, help="自举模式指定 Excel 路径")
    parser.add_argument("--top-k", type=int, default=20, help="评测 top_k (默认 20)")
    args = parser.parse_args()

    if args.gt:
        gt_path = Path(args.gt)
        ground_truth = json.loads(gt_path.read_text(encoding="utf-8"))
        logging.info("加载 ground truth: %d 题", len(ground_truth))
    elif args.bootstrap:
        excel_path = Path(args.excel) if args.excel else Path("data/test.xlsx")
        ground_truth = bootstrap_from_excel(excel_path)
        logging.info("自举 ground truth from %s: %d 题", excel_path, len(ground_truth))
    else:
        parser.error("必须指定 --gt 或 --bootstrap")
        return

    summary = run_eval(ground_truth, top_k=args.top_k)

    print("\n" + "=" * 50)
    print("Recall@K 评测结果")
    print("=" * 50)
    for key, val in summary.items():
        if isinstance(val, float):
            print(f"  {key:<15}: {val:.1%}")
        else:
            print(f"  {key:<15}: {val}")
    print("=" * 50)


if __name__ == "__main__":
    main()
