"""Agent 端到端评测打分器 (纯函数, 零 LLM/网络依赖, 毫秒级可回归).

双指标:
  1. 工具选择 — tools_required 必须全部命中、tools_any 至少命中一个;
  2. 答案事实 — 关键词组覆盖率: 组内支持 any/all 两种语义, 组间等权平均。

打分只做子串/集合判定, 不调用 LLM 评审, 保证同输入同结果、可复现可追溯。
数据集见 tests/eval/agent_eval_cases.json, 运行器见 tests/eval/run_agent_eval.py。
"""
from __future__ import annotations

from typing import Any

DEFAULT_FACT_THRESHOLD = 0.6


def _terms(group: Any) -> tuple[str, list[str]]:
    """提取 (模式, 关键词列表); 模式为 'any' 或 'all'。

    接受: 字符串(=all 单词)、list/tuple(=all)、{"any": [...]} / {"all": [...]}。
    """
    if isinstance(group, str):
        return "all", [group]
    if isinstance(group, (list, tuple)):
        return "all", [str(x) for x in group]
    if isinstance(group, dict):
        if "any" in group:
            return "any", [str(x) for x in group["any"]]
        if "all" in group:
            return "all", [str(x) for x in group["all"]]
    raise ValueError(f"非法事实组: {group!r}")


def fact_group_satisfied(group: Any, answer: str) -> tuple[bool, list[str]]:
    """单个事实组是否满足, 返回 (是否满足, 命中的关键词)。"""
    mode, words = _terms(group)
    text = (answer or "").lower()
    matched = [w for w in words if w.lower() in text]
    if mode == "any":
        return bool(matched), matched
    return len(matched) == len(words) and len(words) > 0, matched


def score_facts(fact_groups: list[Any], answer: str) -> dict:
    """事实组覆盖率: 组间等权平均。无事实组时 hit_rate=None(不适用)。"""
    details = []
    hits = 0
    for idx, g in enumerate(fact_groups or []):
        ok, matched = fact_group_satisfied(g, answer)
        hits += int(ok)
        _, words = _terms(g)
        details.append({
            "group": idx,
            "mode": _terms(g)[0],
            "expected": words,
            "matched": matched,
            "hit": ok,
        })
    total = len(details)
    return {
        "total": total,
        "hit": hits,
        "hit_rate": round(hits / total, 4) if total else None,
        "details": details,
    }


def score_tools(case: dict, actual_tools: list[str]) -> dict:
    """工具选择指标: required 全命中(召回) + any 至少一个。"""
    actual_set = {t for t in (actual_tools or []) if t}
    required = list(case.get("tools_required") or [])
    any_tools = list(case.get("tools_any") or [])

    req_hits = [t for t in required if t in actual_set]
    req_miss = [t for t in required if t not in actual_set]
    any_hits = [t for t in any_tools if t in actual_set]

    return {
        "actual": sorted(actual_set),
        "required": required,
        "required_hits": req_hits,
        "required_miss": req_miss,
        "required_recall": round(len(req_hits) / len(required), 4) if required else None,
        "any_tools": any_tools,
        "any_hit": (bool(any_hits) if any_tools else None),
    }


def score_case(case: dict, answer: str, tool_calls: list[str],
               fact_threshold: float = DEFAULT_FACT_THRESHOLD) -> dict:
    """单用例打分。passed = 工具指标通过 且 事实覆盖率达标(默认 ≥0.6)。"""
    tool = score_tools(case, tool_calls)
    fact = score_facts(case.get("facts") or [], answer)

    tool_ok = (tool["any_hit"] is None or tool["any_hit"]) and not tool["required_miss"]
    fact_rate = fact["hit_rate"]
    fact_ok = fact_rate is None or fact_rate >= fact_threshold
    answer_ok = bool((answer or "").strip())

    return {
        "id": case.get("id"),
        "category": case.get("category", "unknown"),
        "answer_chars": len(answer or ""),
        "tool": tool,
        "fact": fact,
        "tool_ok": tool_ok,
        "fact_ok": fact_ok,
        "answer_ok": answer_ok,
        "passed": bool(tool_ok and fact_ok and answer_ok),
    }


def aggregate(results: list[dict]) -> dict:
    """汇总总体与分类别指标。"""
    def _block(rows: list[dict]) -> dict:
        n = len(rows)
        if not n:
            return {"cases": 0}
        passed = sum(1 for r in rows if r["passed"])
        tool_rows = [r for r in rows if r["tool"]["any_hit"] is not None
                     or r["tool"]["required_recall"] is not None]
        tool_sel = [1 if r["tool_ok"] else 0 for r in tool_rows]
        fact_rows = [r for r in rows if r["fact"]["hit_rate"] is not None]
        avg_fact = round(sum(r["fact"]["hit_rate"] for r in fact_rows) / len(fact_rows), 4) \
            if fact_rows else None
        req_recalls = [r["tool"]["required_recall"] for r in rows
                       if r["tool"]["required_recall"] is not None]
        return {
            "cases": n,
            "passed": passed,
            "pass_rate": round(passed / n, 4),
            "tool_selection_rate": round(sum(tool_sel) / len(tool_sel), 4) if tool_sel else None,
            "fact_group_hit_rate": avg_fact,
            "required_tool_recall": round(sum(req_recalls) / len(req_recalls), 4)
            if req_recalls else None,
        }

    by_cat: dict[str, list[dict]] = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r)
    return {"overall": _block(results),
            "by_category": {k: _block(v) for k, v in sorted(by_cat.items())}}
