# -*- coding: utf-8 -*-
"""检索消融评测: 退化配置 vs 完整流水线 (同一 17 例固定题集, 检索与生成分离).

配置梯度 (同一候选预算 recall_limit=max(top_k*6,30), 同一行级隔离 anonymous=public):
  A0 单路·纯 dense        无变体/无 BM25/无精排/无多样性 (优化前基线)
  A1 单路·dense+BM25     +混合召回 RRF (加词法通道)
  A2 多路·+受控变体       +Query 规划 (同义词受控替换, ≤3 变体) 变体间 RRF
  A3 完整流水线           +CrossEncoder 精排 +来源多样性 (等价 rag_pipeline.search)

指标: Top-1 命中率 / HitRate@20 (Recall@20) / MRR@20 / nDCG@20。
确定性评测, 不调用生成 LLM。评测 reranker 为检索组件, 保留。

用法:
  .venv\\Scripts\\python.exe tests\\eval\\run_retrieval_ablation.py --topk 20
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import requests  # noqa: F401  (保持与其它评测脚本一致的导入风格检查基线)

logging.basicConfig(level=logging.WARNING)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from src.rag.embedder import embedder, reranker  # noqa: E402
from src.rag.vector_store import vector_store  # noqa: E402
from src.rag.pipeline import _rrf_merge_multi  # noqa: E402
from src.rag.query_planner import plan_query  # noqa: E402
from src.rag.diversity import apply_source_diversity  # noqa: E402
from src.config import settings  # noqa: E402
from tests.eval.run_retrieval_eval import (  # noqa: E402
    CASES_PATH, _is_relevant, _ndcg_at_k,
)

RECALL_LIMIT = None  # 按 top_k 计算后填充


def _qdrant_search(dense, sparse, limit: int, question: str) -> list[dict]:
    """单查询检索; sparse=None 时为纯 dense 单通道 (A0 基线).

    与 vector_store.hybrid_search 同一 RrfQuery 语义与行级过滤,
    仅通道数不同, 保证各配置候选预算与过滤条件一致.
    """
    from qdrant_client.http.models import Prefetch, Rrf, RrfQuery
    from src.auth.access_scope import get_current_scope, build_qdrant_filter
    from src.rag.vector_store import _rrf_k_for

    k = _rrf_k_for(question)
    prefetch = [Prefetch(query=dense, using="dense", limit=30)]
    if sparse is not None:
        prefetch.append(Prefetch(query=sparse, using="sparse", limit=30))
    kwargs = dict(
        collection_name=settings.qdrant_collection,
        prefetch=prefetch,
        query=RrfQuery(rrf=Rrf(k=k)), limit=limit, with_payload=True)
    qdrant_filter = build_qdrant_filter(get_current_scope())
    if qdrant_filter is not None:
        kwargs["query_filter"] = qdrant_filter
    resp = vector_store._get_client().query_points(**kwargs)
    results = []
    for h in resp.points:
        item = {
            "id": h.id, "score": h.score,
            "question": h.payload.get("question", ""),
            "answer": h.payload.get("answer", ""),
        }
        for meta_key in ("source_file", "section_title", "doc_type",
                         "chunk_id", "business_line", "db_id",
                         "page_no", "package", "bidder_name"):
            val = h.payload.get(meta_key)
            if val not in (None, ""):
                item[meta_key] = val
        results.append(item)
    return results


def _search_config(question: str, top_k: int, cfg: dict) -> list[dict]:
    variants = [question]
    if cfg["plan"]:
        variants = plan_query(question, None, max_variants=3)
    per_variant = []
    for v in variants:
        dense = embedder.encode_query_dense(v)
        sparse = embedder.encode_query_sparse(v) if cfg["sparse"] else None
        per_variant.append(_qdrant_search(
            dense, sparse, max(top_k * 6, 30), v))
    docs = per_variant[0] if len(per_variant) == 1 else _rrf_merge_multi(per_variant, k=60)
    if cfg["rerank"]:
        docs = reranker.rerank(question, docs, top_k=top_k * 3)
    if cfg["diversity"]:
        docs = apply_source_diversity(
            docs, max_per_source=settings.source_diversity_max)
    return docs[:top_k]


CONFIGS = [
    ("A0", "单路·纯 dense (优化前基线)",
     {"plan": False, "sparse": False, "rerank": False, "diversity": False}),
    ("A1", "单路·+BM25 混合召回",
     {"plan": False, "sparse": True, "rerank": False, "diversity": False}),
    ("A2", "多路·+Query 受控变体",
     {"plan": True, "sparse": True, "rerank": False, "diversity": False}),
    ("A3", "完整流水线·+精排+来源多样性",
     {"plan": True, "sparse": True, "rerank": True, "diversity": True}),
]


def _metrics(cases: list[dict], top_k: int, cfg: dict) -> dict:
    per = []
    for case in cases:
        docs = _search_config(case["question"], top_k, cfg)
        flags = [_is_relevant(d, case) for d in docs]
        rank = next((i + 1 for i, ok in enumerate(flags) if ok), None)
        per.append({
            "id": case["id"], "hit": rank is not None,
            "top1": rank == 1, "rr": 1.0 / rank if rank else 0.0,
            "ndcg": round(_ndcg_at_k(flags), 4),
        })
    n = len(per)
    return {
        "cases": n,
        "top1_rate": round(sum(c["top1"] for c in per) / n, 4),
        "hit_rate": round(sum(c["hit"] for c in per) / n, 4),
        "mrr": round(sum(c["rr"] for c in per) / n, 4),
        "ndcg": round(sum(c["ndcg"] for c in per) / n, 4),
        "per_case": per,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topk", type=int, default=20)
    args = ap.parse_args()

    spec = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = spec["cases"]

    from src.rag.pipeline import rag_pipeline
    if not rag_pipeline.ready:
        rag_pipeline.initialize()
    if not rag_pipeline.ready:
        raise RuntimeError("RAG 流水线未就绪 (vocab/模型缺失)")

    results = {"top_k": args.topk, "cases": len(cases), "configs": {}}
    for cid, name, cfg in CONFIGS:
        m = _metrics(cases, args.topk, cfg)
        results["configs"][cid] = {"name": name, **m}
        print(f"[{cid}] {name}: Top-1={m['top1_rate']:.0%} "
              f"HitRate@{args.topk}={m['hit_rate']:.0%} "
              f"MRR={m['mrr']:.4f} nDCG={m['ndcg']:.4f}")

    base = results["configs"]["A0"]
    final = results["configs"]["A3"]
    results["improvement"] = {
        "hit_rate_pp": round((final["hit_rate"] - base["hit_rate"]) * 100, 1),
        "top1_pp": round((final["top1_rate"] - base["top1_rate"]) * 100, 1),
        "ndcg_pp": round((final["ndcg"] - base["ndcg"]) * 100, 1),
        "mrr_delta": round(final["mrr"] - base["mrr"], 4),
    }

    jp = HERE / "retrieval_ablation_report.json"
    jp.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                  encoding="utf-8")

    lines = [
        "# 检索消融评测报告 (优化前后对比)",
        "",
        f"- 用例数: {len(cases)} (固定题集, 与 retrieval_eval 同源)  |  top-K: {args.topk}",
        "- 原则: 检索与生成分离 — 确定性评测, 不调用生成 LLM; 各配置同候选预算同行级隔离",
        "",
        "| 配置 | Top-1 命中 | HitRate@K (Recall) | MRR | nDCG |",
        "|---|---|---|---|---|",
    ]
    for cid, name, _ in CONFIGS:
        m = results["configs"][cid]
        lines.append(f"| {cid} {name} | {m['top1_rate']:.0%} | "
                     f"{m['hit_rate']:.0%} | {m['mrr']:.4f} | {m['ndcg']:.4f} |")
    imp = results["improvement"]
    lines += [
        "",
        f"**优化前后 (A0→A3): Recall@{args.topk} {imp['hit_rate_pp']:+.1f}pp, "
        f"Top-1 {imp['top1_pp']:+.1f}pp, nDCG {imp['ndcg_pp']:+.1f}pp**",
        "",
    ]
    mp = HERE / "retrieval_ablation_report.md"
    mp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"报告: {jp}")
    print(f"报告: {mp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
