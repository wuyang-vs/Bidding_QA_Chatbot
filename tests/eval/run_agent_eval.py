"""Agent 端到端评测运行器 (手动评测: 需运行中的后端 + 可用 LLM)。

与 run_retrieval_eval.py 的分工:
  - 检索评测只测"召回对不对"(确定性、零 LLM);
  - 本评测测"Agent 端到端答得好不好": 每题真实走 /api/chat 的 ReAct 链路,
    双指标打分 —— 工具选择(该查的源查了没) + 答案事实(关键事实答对没),
    覆盖单跳/多跳/跨域三类题型。

用法:
  .venv\\Scripts\\python.exe tests\\eval\\run_agent_eval.py
  .venv\\Scripts\\python.exe tests\\eval\\run_agent_eval.py --base-url http://localhost:8001 --min-pass 0.7

产出: tests/eval/agent_eval_report.json / agent_eval_report.md
打分器为纯函数 src.agent.eval_scoring, 离线单测见 tests/test_agent_eval_scoring.py。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from src.agent.eval_scoring import aggregate, score_case  # noqa: E402

CASES_PATH = HERE / "agent_eval_cases.json"

ROLE_LABELS = {
    "search_bidding_knowledge": "知识库",
    "search_knowledge_graph": "图谱",
    "search_postgresql": "结构化库",
    "list_bid_documents": "文档列表",
    "generate_bid_draft": "标书生成",
    "explain_anomaly": "异常解释",
    "recommend_template": "范本推荐",
    "consult_appeal": "异议咨询",
    "guide_operation": "操作引导",
    "search_web": "联网",
    "search_exa": "Exa",
}
CAT_LABELS = {"single_hop": "单跳", "multi_hop": "多跳", "cross_domain": "跨域"}


def _extract_tool_names(data: dict) -> list[str]:
    names: list[str] = []
    for tc in (data.get("exec_log") or {}).get("tool_calls") or []:
        n = tc.get("name")
        if n and n not in names:
            names.append(n)
    # 兼容老形态
    if not names and data.get("tool_name"):
        names.append(data["tool_name"])
    return names


def run_one(base_url: str, case: dict, timeout: int, fact_threshold: float) -> dict:
    payload = {"question": case["question"], "history": []}
    t0 = time.time()
    try:
        resp = requests.post(f"{base_url}/api/chat", json=payload, timeout=timeout)
        elapsed_ms = int((time.time() - t0) * 1000)
        if resp.status_code != 200:
            sc = score_case(case, "", [], fact_threshold)
            sc.update({"error": f"HTTP {resp.status_code}: {resp.text[:150]}",
                       "elapsed_ms": elapsed_ms})
            return sc
        data = resp.json()
        answer = data.get("answer") or ""
        tools = _extract_tool_names(data)
        sc = score_case(case, answer, tools, fact_threshold)
        sc.update({"gated": bool(data.get("gated")),
                   "elapsed_ms": elapsed_ms,
                   "answer_head": answer[:100]})
        return sc
    except Exception as e:  # noqa: BLE001 - 评测记录任何链路异常均计为失败用例
        sc = score_case(case, "", [], fact_threshold)
        sc.update({"error": f"{type(e).__name__}: {e}"[:200],
                   "elapsed_ms": int((time.time() - t0) * 1000)})
        return sc


def _md_table(rows: list[dict]) -> str:
    lines = ["| 指标 | 值 |", "|---|---|"]
    order = [
        ("cases", "用例数"), ("passed", "通过数"), ("pass_rate", "通过率"),
        ("tool_selection_rate", "工具选择正确率"),
        ("required_tool_recall", "必需工具召回率"),
        ("fact_group_hit_rate", "事实组覆盖率"),
    ]
    for k, label in order:
        v = rows.get(k)
        if v is None:
            continue
        lines.append(f"| {label} | {v:.4f} |" if isinstance(v, float) else f"| {label} | {v} |")
    return "\n".join(lines)


def write_reports(cases: list[dict], results: list[dict], summary: dict,
                  fact_threshold: float, out_json: Path, out_md: Path) -> None:
    out_json.write_text(json.dumps(
        {"fact_threshold": fact_threshold, "summary": summary,
         "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")

    md = [
        "# Agent 端到端评测报告",
        "",
        f"- 用例数: {len(results)}（单跳/多跳/跨域）；事实组通过阈值: {fact_threshold}",
        "- 链路: POST /api/chat（ReAct 多轮工具 + 硬闸门）",
        "- 指标: 工具选择正确率（tools_any 命中且 tools_required 全中）、事实组覆盖率（关键词组等权）",
        "- 打分器为纯字符串/集合判定，不做 LLM 评审，同输入同结果",
        "",
        "## 总体",
        "",
        _md_table(summary["overall"]),
        "",
        "## 分类别",
        "",
        "| 类别 | 用例 | 通过 | 通过率 | 工具选择正确 | 必需工具召回 | 事实覆盖 |",
        "|---|---|---|---|---|---|---|",
    ]
    for cat, b in summary["by_category"].items():
        def f(v):
            return f"{v:.3f}" if isinstance(v, float) else ("—" if v is None else str(v))
        md.append(f"| {CAT_LABELS.get(cat, cat)} | {b.get('cases', 0)} | "
                  f"{b.get('passed', 0)} | {f(b.get('pass_rate'))} | "
                  f"{f(b.get('tool_selection_rate'))} | {f(b.get('required_tool_recall'))} | "
                  f"{f(b.get('fact_group_hit_rate'))} |")
    md += ["", "## 逐用例", "",
           "| ID | 类别 | 实际调用工具 | 工具通过 | 事实覆盖 | 结果 | 耗时s | 备注 |",
           "|---|---|---|---|---|---|---|---|"]
    for r in results:
        tools = "、".join(ROLE_LABELS.get(t, t) for t in r["tool"]["actual"]) or "（无）"
        fr = r["fact"]["hit_rate"]
        fr_s = "—" if fr is None else f"{fr:.2f}"
        note = r.get("error") or ("gated 拒答" if r.get("gated") else "")
        md.append(f"| {r['id']} | {CAT_LABELS.get(r['category'], r['category'])} | "
                  f"{tools} | {'✅' if r['tool_ok'] else '❌'} | {fr_s} | "
                  f"{'PASS' if r['passed'] else 'FAIL'} | {r.get('elapsed_ms', 0)/1000:.1f} | {note} |")
    out_md.write_text("\n".join(md) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8001")
    ap.add_argument("--timeout", type=int, default=280)
    ap.add_argument("--fact-threshold", type=float, default=0.6)
    ap.add_argument("--min-pass", type=float, default=0.0,
                    help="通过率低于该值则退出码 1（默认不卡门）")
    args = ap.parse_args()

    try:
        h = requests.get(f"{args.base_url}/api/health", timeout=5).json()
    except Exception as e:  # noqa: BLE001
        print(f"后端不可达 ({args.base_url}): {e}\n请先启动后端再运行本评测。")
        return 2
    if not h.get("ready"):
        print(f"后端未就绪: {h}")
        return 2

    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    print(f"共 {len(cases)} 题, 目标 {args.base_url}/api/chat")
    results = []
    for i, case in enumerate(cases, 1):
        r = run_one(args.base_url, case, args.timeout, args.fact_threshold)
        results.append(r)
        fr = r["fact"]["hit_rate"]
        fr_s = "-" if fr is None else f"{fr:.2f}"
        err_s = f"  err={r['error']}" if r.get("error") else ""
        print(f"[{i}/{len(cases)}] {r['id']} "
              f"{'PASS' if r['passed'] else 'FAIL'}  "
              f"工具={'✓' if r['tool_ok'] else '✗'} 事实={fr_s} "
              f"({r.get('elapsed_ms', 0)/1000:.1f}s){err_s}",
              flush=True)

    summary = aggregate(results)
    write_reports(cases, results, summary, args.fact_threshold,
                  HERE / "agent_eval_report.json", HERE / "agent_eval_report.md")

    ov = summary["overall"]
    print("\n" + "=" * 60)
    print(f"通过率 {ov.get('passed', 0)}/{ov.get('cases', 0)} = {ov.get('pass_rate')}")
    print(f"工具选择正确率={ov.get('tool_selection_rate')} "
          f"必需工具召回={ov.get('required_tool_recall')} "
          f"事实组覆盖={ov.get('fact_group_hit_rate')}")
    print("报告: tests/eval/agent_eval_report.md")

    if (ov.get("pass_rate") or 0) + 1e-9 < args.min_pass:
        print(f"低于门禁 --min-pass {args.min_pass}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
