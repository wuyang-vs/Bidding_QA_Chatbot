"""检索质量离线评测 (确定性, 不调用 LLM).

指标:
  HitRate@K   top-K 来源中是否存在与期望答案匹配的分片 (漏检率 = 1 - HitRate; 即 Recall@K)
  MRR@K       首个匹配来源倒数排名的均值
  nDCG@K      二元相关性归一化折损累计增益 (相关分片越靠前越接近 1)
  CitationPrecision@K  top-K 来源中相关分片占比 (引用准确率, 越低噪声引用越多)
  EvidenceCoverage      期望证据词组在 top-K 拼接文本中的覆盖率 (采纳充分度)

用法:
  .venv\\Scripts\\python.exe -m tests.eval.run_retrieval_eval
  .venv\\Scripts\\python.exe tests\\eval\\run_retrieval_eval.py --topk 5
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from pathlib import Path

logging.basicConfig(level=logging.WARNING)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
CASES_PATH = HERE / "retrieval_cases.json"


def _source_text(doc: dict) -> str:
    return f"{doc.get('question', '')}\n{doc.get('answer', '')}"


def _is_relevant(doc: dict, case: dict) -> bool:
    t = _source_text(doc)
    must_all = case.get("must_all") or []
    must_any = case.get("must_any") or []
    if not all(w in t for w in must_all):
        return False
    if must_any and not any(w in t for w in must_any):
        return False
    return True


def _ndcg_at_k(flags: list[bool]) -> float:
    """二元相关性 nDCG@K: DCG/IDCG, IDCG 取 top-K 内相关条数的理想排布.

    无全量 qrels 时以 top-K 内相关条数近似理想 DCG (标准近似):
    全部相关分片聚在列表最前 → 1.0; 相关越靠后越低; 无相关条目 → 0.
    """
    rel = [1.0 if f else 0.0 for f in flags]
    dcg = sum(r / math.log2(i + 2) for i, r in enumerate(rel))
    n_rel = sum(rel)
    if n_rel == 0:
        return 0.0
    idcg = sum(1.0 / math.log2(i + 2) for i in range(int(n_rel)))
    return dcg / idcg


def _evidence_coverage(docs: list[dict], case: dict) -> float:
    """期望证据覆盖: must_all 每个词为一组, must_any 整体为一组 (组内 OR)."""
    t = "\n".join(_source_text(d) for d in docs)
    groups = [[w] for w in (case.get("must_all") or [])]
    if case.get("must_any"):
        groups.append(case["must_any"])
    if not groups:
        return 1.0
    hit = sum(1 for g in groups if any(w in t for w in g))
    return hit / len(groups)


def run(top_k: int | None = None) -> dict:
    from src.rag.pipeline import rag_pipeline

    spec = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    top_k = top_k or int(spec.get("top_k", 5))
    cases = spec["cases"]

    if not rag_pipeline.ready:
        rag_pipeline.initialize()
    if not rag_pipeline.ready:
        raise RuntimeError("RAG 流水线未就绪 (vocab/模型缺失)")

    per_case = []
    for case in cases:
        docs = rag_pipeline.search(case["question"], top_k=top_k)
        flags = [_is_relevant(d, case) for d in docs]
        rank = next((i + 1 for i, ok in enumerate(flags) if ok), None)
        rel_count = sum(flags)
        per_case.append({
            "id": case["id"],
            "domain": case.get("domain", ""),
            "question": case["question"],
            "hit": rank is not None,
            "rank": rank,
            "rr": 1.0 / rank if rank else 0.0,
            "relevant_in_topk": rel_count,
            "precision_at_k": round(rel_count / max(len(docs), 1), 3),
            "ndcg": round(_ndcg_at_k(flags), 4),
            "evidence_coverage": round(_evidence_coverage(docs, case), 3),
            "top_sources": [
                {
                    "rank": i + 1,
                    "source_file": d.get("source_file", ""),
                    "db_id": d.get("db_id"),
                    "page_no": d.get("page_no"),
                    "relevant": flags[i],
                    "snippet": _source_text(d)[:90].replace("\n", " "),
                }
                for i, d in enumerate(docs)
            ],
        })

    n = len(per_case)
    hits = sum(1 for c in per_case if c["hit"])
    summary = {
        "cases": n,
        "top_k": top_k,
        "hit_rate": round(hits / n, 4),
        "miss_rate": round(1 - hits / n, 4),
        "mrr": round(sum(c["rr"] for c in per_case) / n, 4),
        "ndcg": round(sum(c["ndcg"] for c in per_case) / n, 4),
        "citation_precision": round(
            sum(c["precision_at_k"] for c in per_case) / n, 4),
        "evidence_coverage": round(
            sum(c["evidence_coverage"] for c in per_case) / n, 4),
    }
    by_domain: dict[str, list[dict]] = {}
    for c in per_case:
        by_domain.setdefault(c["domain"], []).append(c)
    summary["by_domain"] = {
        dom: {
            "cases": len(items),
            "hit_rate": round(sum(x["hit"] for x in items) / len(items), 4),
            "mrr": round(sum(x["rr"] for x in items) / len(items), 4),
            "ndcg": round(sum(x["ndcg"] for x in items) / len(items), 4),
        }
        for dom, items in by_domain.items()
    }
    return {"summary": summary, "cases": per_case}


def write_reports(result: dict) -> tuple[Path, Path]:
    jp = HERE / "retrieval_eval_report.json"
    mp = HERE / "retrieval_eval_report.md"
    jp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    s = result["summary"]
    lines = [
        "# 检索质量离线评测报告",
        "",
        f"- 用例数: {s['cases']}  |  top-K: {s['top_k']}",
        f"- **命中率 HitRate@K: {s['hit_rate']:.2%}**  (漏检率 {s['miss_rate']:.2%})",
        f"- **MRR@K: {s['mrr']:.4f}**",
        f"- **nDCG@K: {s['ndcg']:.4f}**",
        f"- **引用准确率 CitationPrecision@K: {s['citation_precision']:.2%}**",
        f"- **证据采纳覆盖率 EvidenceCoverage: {s['evidence_coverage']:.2%}**",
        "",
        "## 分领域",
        "",
        "| 领域 | 用例 | HitRate | MRR | nDCG |",
        "|---|---|---|---|---|",
    ]
    for dom, d in s["by_domain"].items():
        lines.append(
            f"| {dom} | {d['cases']} | {d['hit_rate']:.2%} | "
            f"{d['mrr']:.3f} | {d['ndcg']:.3f} |")
    lines += ["", "## 逐用例", "",
              "| ID | 领域 | 命中 | 首位排名 | 相关条数 | 引用准确率 | nDCG | 证据覆盖 |",
              "|---|---|---|---|---|---|---|---|"]
    for c in result["cases"]:
        lines.append(
            f"| {c['id']} | {c['domain']} | {'✅' if c['hit'] else '❌'} | "
            f"{c['rank'] or '-'} | {c['relevant_in_topk']} | "
            f"{c['precision_at_k']:.0%} | {c['ndcg']:.3f} | "
            f"{c['evidence_coverage']:.0%} |")
    mp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return jp, mp


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topk", type=int, default=None)
    ap.add_argument("--min-hitrate", type=float, default=0.0,
                    help="命中率低于该值时退出码=1 (默认不卡阈值, 仅建立基线)")
    args = ap.parse_args()

    result = run(args.topk)
    jp, mp = write_reports(result)
    s = result["summary"]
    print(f"用例 {s['cases']} | HitRate@{s['top_k']}={s['hit_rate']:.2%} "
          f"(漏检 {s['miss_rate']:.2%}) | MRR={s['mrr']:.4f} | "
          f"nDCG={s['ndcg']:.4f} | "
          f"引用准确率={s['citation_precision']:.2%} | "
          f"证据覆盖={s['evidence_coverage']:.2%}")
    for c in result["cases"]:
        mark = "OK " if c["hit"] else "MISS"
        print(f"  [{mark}] {c['id']} rank={c['rank'] or '-'} "
              f"rel={c['relevant_in_topk']} ndcg={c['ndcg']:.3f} "
              f"cov={c['evidence_coverage']:.2f} "
              f"Q={c['question'][:38]}")
    print(f"报告: {jp}")
    print(f"报告: {mp}")
    return 1 if s["hit_rate"] < args.min_hitrate else 0


if __name__ == "__main__":
    sys.exit(main())
