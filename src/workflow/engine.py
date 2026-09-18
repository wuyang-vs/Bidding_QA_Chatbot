"""轻量工作流引擎 —— JSON 配置 + 节点注册 + DAG 执行器.

不引 LangGraph / LangChain 等重依赖, 纯自建实现:
  - 节点注册: 把 6 个独立工具包装成 callable
  - JSON 配置: 节点 + 依赖边 + 参数模板
  - 执行器: 线程池并行 + 条件分支 + 降级

JSON 格式示例:
{
  "name": "合规审查一条龙",
  "description": "...",
  "nodes": [
    {"id": "n1", "tool": "compliance_check",
     "params": {"tender_db_id": "<ctx.db_id>"},
     "fail_mode": "stop"},        // stop | degrade | continue
    {"id": "n2", "tool": "qualification_check",
     "params": {"tender_text": "<ctx.tender_text>"}}
  ],
  "edges": {"n1": ["n2"]},        // n1 完成后执行 n2
  "parallel": ["compliance"]      // 可并行的节点 id 组
}
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ---------- 节点注册表 ----------

_TOOL_REGISTRY: dict[str, Callable] = {}


def register_tool(name: str, fn: Callable) -> None:
    _TOOL_REGISTRY[name] = fn


def _ensure_tools_registered() -> None:
    """惰性注册所有 6 个工具节点 (首次调用时); 单个失败不影响其他, 后续调用自动补注册."""
    llm = _get_llm()

    def _fetch_doc(db_id: Any) -> dict | None:
        """按 db_id 取已解析招标文件整行 (工具接受 dict 行)."""
        if not db_id:
            return None
        try:
            from src.database.postgresql_client import postgresql_client
            if not postgresql_client.ready:
                return None
            rows = postgresql_client._run(
                "SELECT * FROM bidding_documents WHERE id=:id", {"id": int(db_id)})
            return rows[0] if rows else None
        except Exception as e:
            logger.warning("读取招标文件失败 db_id=%s: %s", db_id, e)
            return None

    if "compliance_check" not in _TOOL_REGISTRY:
        try:
            from src.tools.compliance_checker import check_compliance

            def _compliance(p: dict):
                content = p.get("tender_text") or _fetch_doc(
                    p.get("tender_db_id") or p.get("db_id"))
                if not content:
                    raise ValueError("缺少招标文件: 需 tender_text 或 tender_db_id")
                return check_compliance(content, llm_client=llm)

            register_tool("compliance_check", _compliance)
        except Exception as e:
            logger.warning("register compliance_check 失败: %s", e)

    if "qualification_check" not in _TOOL_REGISTRY:
        try:
            from src.tools.qualification_checker import check_qualification

            def _qualification(p: dict):
                # 资格要求: 显式文本/list → db_id 回退取库
                tr: Any = p.get("qualification_requirements") or p.get("criteria_text") or ""
                if not tr:
                    doc = _fetch_doc(p.get("db_id") or p.get("tender_db_id"))
                    if doc and isinstance(doc.get("qualification_requirements"), list):
                        tr = doc["qualification_requirements"]
                if isinstance(tr, str) and tr:
                    tr = [s.strip() for s in tr.splitlines() if s.strip()]
                cq: Any = p.get("qualification_text") or p.get("company_qualifications") or ""
                if isinstance(cq, str) and cq:
                    cq = [s.strip() for s in cq.splitlines() if s.strip()]
                if not tr:
                    raise ValueError("缺少资格要求: 需 criteria_text 或 db_id")
                return check_qualification(tr or None, cq or None, llm_client=llm)

            register_tool("qualification_check", _qualification)
        except Exception as e:
            logger.warning("register qualification_check 失败: %s", e)

    if "rejection_check" not in _TOOL_REGISTRY:
        try:
            from src.tools.bid_rejection_checker import check_bid_rejection

            def _rejection(p: dict):
                content = p.get("tender_text") or _fetch_doc(
                    p.get("tender_db_id") or p.get("db_id"))
                if not content:
                    raise ValueError("缺少招标文件: 需 tender_text 或 tender_db_id")
                return check_bid_rejection(
                    content, bidder_status=p.get("bidder_status") or None, llm_client=llm)

            register_tool("rejection_check", _rejection)
        except Exception as e:
            logger.warning("register rejection_check 失败: %s", e)

    if "response_check" not in _TOOL_REGISTRY:
        try:
            from src.tools.response_checker import check_response

            def _response(p: dict):
                tender = p.get("tender_text") or _fetch_doc(
                    p.get("tender_db_id") or p.get("db_id"))
                bid = p.get("bid_text") or _fetch_doc(p.get("bid_db_id"))
                if not tender:
                    raise ValueError("缺少招标文件: 需 tender_text 或 tender_db_id")
                if not bid:
                    raise ValueError("缺少投标内容: 需 bid_text 或 bid_db_id")
                return check_response(tender, bid, p.get("clause") or None, llm_client=llm)

            register_tool("response_check", _response)
        except Exception as e:
            logger.warning("register response_check 失败: %s", e)

    if "scoring_table" not in _TOOL_REGISTRY:
        try:
            from src.tools.scoring_table import generate_scoring_table

            def _scoring(p: dict):
                text = p.get("scoring_text") or ""
                if not text:
                    doc = _fetch_doc(p.get("db_id") or p.get("tender_db_id"))
                    if doc:
                        text = doc.get("scoring_criteria") or ""
                if not text:
                    raise ValueError("缺少评分办法: 需 scoring_text 或 db_id")
                return generate_scoring_table(text, llm_client=llm)

            register_tool("scoring_table", _scoring)
        except Exception as e:
            logger.warning("register scoring_table 失败: %s", e)

    if "bid_compare" not in _TOOL_REGISTRY:
        try:
            from src.tools.bid_comparator import compare_bids
            register_tool("bid_compare", lambda p: compare_bids(
                p.get("bids") or [], llm_client=llm))
        except Exception as e:
            logger.warning("register bid_compare 失败: %s", e)


_llm_cached = None
_llm_lock = threading.Lock()


def _get_llm():
    global _llm_cached
    if _llm_cached is None:
        with _llm_lock:
            if _llm_cached is None:
                try:
                    from src.clients.llm_factory import get_llm_client
                    _llm_cached = get_llm_client()
                except Exception:
                    _llm_cached = None
    return _llm_cached


def _render_params(raw: dict, ctx: dict, node_results: dict) -> dict:
    """把 params 里的 `<ctx.xxx>` 占位符替换成 ctx 值.

    支持 `<ctx.db_id>` / `<node_result.xxx>` 两种来源.
    """
    def _sub(v):
        if isinstance(v, str):
            import re
            def _repl(m):
                key = m.group(1)
                if key.startswith("ctx."):
                    return str(ctx.get(key[4:], ""))
                if key.startswith("node."):
                    nid = key[5:]
                    return str(node_results.get(nid, {}))
                return m.group(0)
            return re.sub(r"<([a-z_\.]+)>", _repl, v)
        if isinstance(v, dict):
            return {k: _sub(vv) for k, vv in v.items()}
        if isinstance(v, list):
            return [_sub(x) for x in v]
        return v
    return {k: _sub(v) for k, v in raw.items()}


# ---------- 预置工作流 ----------

PRESETS: dict[str, dict[str, Any]] = {
    "compliance_review": {
        "name": "合规审查一条龙",
        "description": "依次执行合规检查 → 资格条件检查 → 废标条款检查",
        "nodes": [
            {"id": "compliance", "tool": "compliance_check",
             "params": {"tender_db_id": "<ctx.db_id>"},
             "fail_mode": "degrade"},
            {"id": "qualification", "tool": "qualification_check",
             "params": {"db_id": "<ctx.db_id>",
                        "criteria_text": "<ctx.qualification_requirements>",
                        "qualification_text": "<ctx.qualification_text>"},
             "fail_mode": "degrade"},
            {"id": "rejection", "tool": "rejection_check",
             "params": {"tender_db_id": "<ctx.db_id>"},
             "fail_mode": "degrade"},
        ],
        "edges": {"compliance": ["qualification", "rejection"]},
    },
    "eval_assist": {
        "name": "评标辅助一条龙",
        "description": "评分辅助表 + 投标响应性检查 + 多家投标对比 (可选)",
        "nodes": [
            {"id": "scoring", "tool": "scoring_table",
             "params": {"db_id": "<ctx.db_id>",
                        "scoring_text": "<ctx.scoring_criteria>"},
             "fail_mode": "degrade"},
            {"id": "response", "tool": "response_check",
             "params": {"tender_db_id": "<ctx.db_id>",
                        "bid_text": "<ctx.bid_text>",
                        "clause": "<ctx.clause>"},
             "fail_mode": "degrade"},
        ],
        "edges": {"scoring": ["response"]},
    },
}


def list_presets() -> list[dict[str, str]]:
    return [{"id": k, "name": v["name"], "description": v["description"]}
            for k, v in PRESETS.items()]


# ---------- 执行器 ----------

def run_workflow(
    config: dict[str, Any],
    ctx: dict[str, Any],
    parallel: bool = True,
) -> dict[str, Any]:
    """执行一个工作流配置.

    Args:
        config: 预置 id (如 "compliance_review") 或完整配置 dict
        ctx: 上下文数据, 含 db_id / bid_text 等, 节点 params 可通过 <ctx.xxx> 引用
        parallel: 允许无依赖节点并行执行

    Returns:
        {name, results: {node_id: {status, duration_ms, output, error}}, summary}
    """
    _ensure_tools_registered()

    # 支持传预设 id
    if isinstance(config, str):
        config = PRESETS.get(config, {})
    if not config.get("nodes"):
        return {"error": "无效的工作流配置: 缺少 nodes"}

    nodes = {n["id"]: n for n in config["nodes"]}
    edges: dict[str, list[str]] = config.get("edges", {})

    # 拓扑排序 (简单版本: 按 edges 拓扑)
    order = _topo_sort(nodes, edges)
    logger.info("工作流 %s 执行顺序: %s", config.get("name", "?"), order)

    node_results: dict[str, dict] = {}
    futures: dict[str, Future] = {}

    def _exec_node(nid: str) -> dict:
        node = nodes[nid]
        tool_name = node["tool"]
        params_raw = node.get("params", {})
        params = _render_params(params_raw, ctx, node_results)

        fn = _TOOL_REGISTRY.get(tool_name)
        if not fn:
            return {"status": "error", "error": f"tool 未注册: {tool_name}", "params": params}

        import time as _time
        t0 = _time.time()
        try:
            out = fn(params)
            return {"status": "success", "duration_ms": int((_time.time() - t0) * 1000),
                    "output": out, "params": params}
        except Exception as e:
            logger.warning("节点 %s(%s) 执行失败: %s", nid, tool_name, e)
            return {"status": "error", "duration_ms": int((_time.time() - t0) * 1000),
                    "error": str(e), "params": params}

    if parallel:
        with ThreadPoolExecutor(max_workers=4) as pool:
            # 第一轮: 无入边节点
            in_degree = {nid: 0 for nid in nodes}
            for child_ids in edges.values():
                for c in child_ids:
                    if c in in_degree:
                        in_degree[c] = in_degree.get(c, 0) + 1

            ready = [nid for nid, d in in_degree.items() if d == 0]
            completed = set()

            while ready or futures:
                # 提交 ready 节点
                for nid in ready:
                    futures[nid] = pool.submit(_exec_node, nid)
                ready = []

                # 等待任一完成
                for fut in as_completed(list(futures.values())):
                    nid = [k for k, v in futures.items() if v is fut][0]
                    result = fut.result()
                    node_results[nid] = result
                    del futures[nid]
                    completed.add(nid)

                    # 检查后继节点是否 ready
                    for child_id in edges.get(nid, []):
                        if child_id not in in_degree:
                            continue
                        in_degree[child_id] -= 1
                        if in_degree[child_id] == 0:
                            ready.append(child_id)
                    break
    else:
        for nid in order:
            node_results[nid] = _exec_node(nid)

    # 汇总
    total = len(nodes)
    success = sum(1 for r in node_results.values() if r["status"] == "success")
    errors = total - success

    return {
        "name": config.get("name", "未命名工作流"),
        "nodes": [nodes[nid]["tool"] for nid in order],
        "results": {nid: {
            "status": r["status"],
            "duration_ms": r.get("duration_ms", 0),
            "error": r.get("error"),
            "output_keys": list(r.get("output", {}).keys()) if isinstance(r.get("output"), dict) else [],
        } for nid, r in node_results.items()},
        "raw": node_results,
        "summary": {
            "total": total,
            "success": success,
            "errors": errors,
            "verdict": "ok" if errors == 0 else ("partial" if success > 0 else "failed"),
        },
    }


def _topo_sort(nodes: dict, edges: dict[str, list[str]]) -> list[str]:
    in_degree = {nid: 0 for nid in nodes}
    for children in edges.values():
        for c in children:
            if c in in_degree:
                in_degree[c] = in_degree.get(c, 0) + 1
    queue = [nid for nid, d in in_degree.items() if d == 0]
    order: list[str] = []
    while queue:
        nid = queue.pop(0)
        order.append(nid)
        for c in edges.get(nid, []):
            if c in in_degree:
                in_degree[c] -= 1
                if in_degree[c] == 0:
                    queue.append(c)
    # 循环或孤立节点补齐
    for nid in nodes:
        if nid not in order:
            order.append(nid)
    return order
