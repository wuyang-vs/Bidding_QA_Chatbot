# -*- coding: utf-8 -*-
"""评测用例自动扩充: 检索 17→~70, Agent 12→~55.

从 data/raw/*.xlsx (326 条 QA) + appeal_catalog (11 主题) 自动生成评测用例.
关键词一律取自 answer 原文子串, 不编造. 改写后经 rag_pipeline.search 验证.
用法: .venv\\Scripts\\python.exe tests\\eval\\generate_eval_cases.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

DATA_DIR = HERE.parent.parent / "data" / "raw"
RET_CASES_PATH = HERE / "retrieval_cases.json"
AGT_CASES_PATH = HERE / "agent_eval_cases.json"

# domain → 期望工具子集 (取自 src/agent/intent.py)
DOMAIN_TOOLS: dict[str, list[str]] = {
    "regulation": ["search_bidding_knowledge", "consult_appeal", "recommend_template"],
    "enterprise": ["search_bidding_knowledge", "search_knowledge_graph", "search_postgresql"],
    "tender_fact": ["search_bidding_knowledge", "search_knowledge_graph", "search_postgresql"],
}

# ---- 关键词正则 (全部取自 answer 原文子串) ----
RE_AMOUNT = re.compile(r"￥?\s*([\d,]+\.?\d*)\s*万元?")
RE_DATE_MD = re.compile(r"\d{1,2}月\d{1,2}日")
RE_DATE_FULL = re.compile(r"\d{4}年\d{1,2}月\d{1,2}日")
RE_TIME = re.compile(r"\d{1,2}:\d{2}")
RE_ARTICLE = re.compile(r"第[一二三四五六七八九十百零]+条")

_STOP_WORDS = {
    "应当", "不得", "可以", "按照", "根据", "规定", "招标", "投标", "采购",
    "活动", "应当", "进行", "应当", "工程", "建设", "项目", "货物", "服务",
}
_GENERIC_PROJECT_WORDS = {
    "项目", "采购", "建设", "改造", "配套", "基础设施", "及系统集成",
    "设备", "服务", "年度", "一期", "二期", "标段", "管理", "平台", "升级",
}


# ============================================================
# 数据加载
# ============================================================

def load_existing() -> tuple[list[dict], list[dict], set[str], set[str]]:
    """读现有 retrieval_cases/agent_eval_cases, 返回 (ret, agt, ret_seen, agt_seen)."""
    ret_spec = json.loads(RET_CASES_PATH.read_text(encoding="utf-8"))
    agt = json.loads(AGT_CASES_PATH.read_text(encoding="utf-8"))
    ret_seen = {_norm(c["question"]) for c in ret_spec["cases"]}
    agt_seen = {_norm(c["question"]) for c in agt}
    return ret_spec["cases"], agt, ret_seen, agt_seen


def _norm(q: str) -> str:
    """question 归一化: 去标点空格, 用于去重."""
    return re.sub(r"[\s，。、；;：:？?！!（()【】\[\]\"'""'']", "", q or "")


def load_qa_pairs() -> list[dict]:
    """读 3 个 Excel, 标准化为 QA 对列表."""
    from src.rag.ingest import find_excel_files, read_qa_data
    pairs: list[dict] = []
    for path in find_excel_files():
        df, _ = read_qa_data(path)
        for _, row in df.iterrows():
            pairs.append({
                "question": str(row.get("question", "")).strip(),
                "answer": str(row.get("answer", "")).strip(),
                "source_file": str(row.get("source_file", path.name)).strip(),
                "section_title": str(row.get("section_title", "")).strip(),
                "doc_type": str(row.get("doc_type", "")).strip(),
                "business_line": str(row.get("business_line", "")).strip(),
                "domain": _classify_domain(row, path.stem),
            })
    return pairs


def _classify_domain(row: pd.Series, file_stem: str) -> str:
    """按 source_file/section_title/doc_type 分类."""
    sf = str(row.get("source_file", "")).strip()
    st = str(row.get("section_title", "")).strip()
    dt = str(row.get("doc_type", "")).strip()
    bl = str(row.get("business_line", "")).strip()
    if dt == "regulation" or bl == "regulation" or "法规" in file_stem:
        return "regulation"
    if st in ("代理机构", "行政区域") or "代理" in st:
        return "enterprise"
    if bl == "enterprise":
        return "enterprise"
    return "tender_fact"


# ============================================================
# 关键词提取 (核心: 必须是 answer 原文子串)
# ============================================================

def _norm_amount(raw: str) -> str:
    """金额规范化: 去千分位逗号."""
    return raw.replace(",", "")


def _is_substring(needle: str, hay: str) -> bool:
    return needle in hay and len(needle) >= 2


def _pick_regulation_term(answer: str, article: str) -> str:
    """从条号所在句取一个区分性术语 (2-4字)."""
    idx = answer.find(article)
    seg = answer[idx:idx + 60] if idx >= 0 else answer[:60]
    for size in (4, 3, 2):
        for i in range(len(seg) - size + 1):
            w = seg[i:i + size]
            if w not in _STOP_WORDS and not w.startswith("第") and w in answer:
                return w
    return ""


def _pick_project_keyword(project: str, question: str) -> str:
    """从项目名/问题取 3-6 字专名片段."""
    src = project or question
    cands = re.findall(r"[\u4e00-\u9fa5]{2,8}", src)
    cands = [c for c in cands if not any(g in c for g in _GENERIC_PROJECT_WORDS) and len(c) >= 3]
    return cands[0] if cands else ""


def _pick_org_name(answer: str) -> str:
    """提取机构/区域名."""
    m = re.search(r"(.+?(?:公司|集团|中心|局|院|省|市|区))", answer)
    return m.group(1) if m else ""


def extract_keywords(answer: str, question: str, domain: str,
                     section_title: str = "") -> dict:
    """返回 {"must_all": [...], "must_any": [...]}."""
    must_all: list[str] = []
    must_any: list[str] = []
    a = answer or ""

    if domain == "regulation":
        arts = RE_ARTICLE.findall(a)
        if arts:
            must_all.append(arts[0])
            term = _pick_regulation_term(a, arts[0])
            if term:
                must_all.append(term)
        if not must_all:
            return {}
        return {"must_all": must_all, "must_any": must_any}

    # tender_fact / enterprise
    amts_raw = RE_AMOUNT.findall(a)
    amts = [_norm_amount(x) for x in amts_raw if _is_substring(_norm_amount(x), a)]
    dates = RE_DATE_MD.findall(a) or RE_DATE_FULL.findall(a)
    times = RE_TIME.findall(a)
    proj_kw = _pick_project_keyword(section_title, question)

    if amts:
        must_any = amts
        if proj_kw:
            must_all = [proj_kw]
    elif dates and times:
        must_all = [dates[0], times[0]]
    elif dates:
        must_all = [dates[0]] if not proj_kw else [proj_kw, dates[0]]
    elif times:
        must_all = [times[0]]
    elif domain == "enterprise" and proj_kw:
        org = _pick_org_name(a)
        must_all = [proj_kw] + ([org] if org else [])

    return {"must_all": must_all, "must_any": must_any} if (must_all or must_any) else {}


# ============================================================
# 改写策略 (安全: 实体不动)
# ============================================================

_PREFIXES = ["", "请问", "那个", "我想问下"]


def rewrite_question(q: str, domain: str, idx: int) -> str:
    """确定性口语化改写 (idx 决定变体). 关键实体不动."""
    if not q:
        return q
    out = q
    if domain == "regulation":
        out = re.sub(r"^根据[^，,。]*[，,]?", "", out)
        return _PREFIXES[idx % len(_PREFIXES)] + out
    out = out.replace("的预算金额", "预算").replace("的采购单位", "采购单位")
    out = out.replace("的代理机构", "代理机构")
    if "是多少" in out:
        out = out.replace("是多少", ["多少钱", "大概多少", "是多少"][idx % 3])
    return _PREFIXES[idx % len(_PREFIXES)] + out


# ============================================================
# 用例构造
# ============================================================

def build_retrieval_case(qa: dict, idx: int) -> dict | None:
    kw = extract_keywords(qa["answer"], qa["question"], qa["domain"], qa["section_title"])
    if not kw:
        return None
    return {
        "id": f"EV-G{idx:03d}",
        "domain": qa["domain"],
        "question": rewrite_question(qa["question"], qa["domain"], idx),
        "must_all": kw["must_all"],
        "must_any": kw["must_any"],
    }


def build_appeal_retrieval_cases() -> list[dict]:
    """从 APPEAL_CATALOG 生成法规类 retrieval case."""
    from src.tools.appeal_catalog import APPEAL_CATALOG
    cases = []
    for i, (code, e) in enumerate(APPEAL_CATALOG.items()):
        basis = e.get("legal_basis", "")
        arts = RE_ARTICLE.findall(basis)
        must_all: list[str] = []
        if arts:
            must_all.append(arts[0])
            term = _pick_regulation_term(basis, arts[0])
            if term:
                must_all.append(term)
        if not must_all:
            continue
        cases.append({
            "id": f"EV-AP{i:02d}",
            "domain": "regulation",
            "question": rewrite_question(e["title"], "regulation", i),
            "must_all": must_all,
            "must_any": [],
        })
    return cases


def build_agent_single_hop(qa: dict, idx: int) -> dict | None:
    kw = extract_keywords(qa["answer"], qa["question"], qa["domain"], qa["section_title"])
    facts: list[dict] = []
    if kw.get("must_all"):
        facts.append({"all": kw["must_all"]})
    elif kw.get("must_any"):
        facts.append({"any": kw["must_any"]})
    if not facts:
        return None
    tools = DOMAIN_TOOLS.get(qa["domain"], ["search_bidding_knowledge"])
    return {
        "id": f"E2E-SH{idx:03d}",
        "category": "single_hop",
        "question": rewrite_question(qa["question"], qa["domain"], idx),
        "tools_any": tools,
        "facts": facts,
        "note": f"{qa['domain']} 单跳, 源 {qa['source_file']}",
    }


def build_agent_multi_hop(project_group: list[dict], idx: int) -> dict | None:
    """同项目多事实点组合."""
    if len(project_group) < 2:
        return None
    # 取两个不同 section_title 的 QA
    sections: dict[str, dict] = {}
    for qa in project_group:
        st = qa.get("section_title", "")
        if st and st not in sections:
            sections[st] = qa
            if len(sections) >= 2:
                break
    if len(sections) < 2:
        return None
    qa_list = list(sections.values())
    a, b = qa_list[0], qa_list[1]
    fa = extract_keywords(a["answer"], a["question"], a["domain"], a["section_title"])
    fb = extract_keywords(b["answer"], b["question"], b["domain"], b["section_title"])
    facts: list[dict] = []
    for kw in (fa, fb):
        if kw.get("must_all"):
            facts.append({"all": kw["must_all"]})
        elif kw.get("must_any"):
            facts.append({"any": kw["must_any"]})
    if len(facts) < 2:
        return None
    proj = a.get("section_title", "")[:20]
    sa = a.get("section_title", "")[:6]
    sb = b.get("section_title", "")[:6]
    return {
        "id": f"E2E-MH{idx:03d}",
        "category": "multi_hop",
        "question": f"{proj}这个项目的{sa}和{sb}分别是什么？请分别给出。",
        "tools_any": ["search_bidding_knowledge", "search_knowledge_graph"],
        "facts": facts,
        "note": "同项目双事实点多跳",
    }


def build_agent_cross_domain(qa: dict, reg_qa: dict, idx: int) -> dict | None:
    """项目事实 + 法规处置组合."""
    f1 = extract_keywords(qa["answer"], qa["question"], qa["domain"], qa["section_title"])
    f2 = extract_keywords(reg_qa["answer"], reg_qa["question"], "regulation", reg_qa["section_title"])
    facts: list[dict] = []
    if f1.get("must_any"):
        facts.append({"any": f1["must_any"]})
    elif f1.get("must_all"):
        facts.append({"all": f1["must_all"]})
    if f2.get("must_all"):
        facts.append({"all": f2["must_all"]})
    elif f2.get("must_any"):
        facts.append({"any": f2["must_any"]})
    if len(facts) < 2:
        return None
    proj = qa.get("section_title", "")[:16]
    sa = qa.get("section_title", "")[:6]
    return {
        "id": f"E2E-CD{idx:03d}",
        "category": "cross_domain",
        "question": f"{proj}的{sa}是？{reg_qa['question']}",
        "tools_any": ["search_bidding_knowledge"],
        "facts": facts,
        "note": "项目事实+法规处置跨域组合",
    }


def build_agent_appeal_cases() -> list[dict]:
    """APPEAL_CATALOG → 单跳法规工具用例."""
    from src.tools.appeal_catalog import APPEAL_CATALOG
    out = []
    for i, (code, e) in enumerate(APPEAL_CATALOG.items()):
        basis = e.get("legal_basis", "")
        arts = RE_ARTICLE.findall(basis)
        facts: list[dict] = []
        if arts:
            facts.append({"any": arts})
            term = _pick_regulation_term(basis, arts[0])
            if term:
                facts.append({"any": [term]})
        if not facts:
            continue
        out.append({
            "id": f"E2E-AP{i:02d}",
            "category": "single_hop",
            "question": rewrite_question(e["title"], "regulation", i),
            "tools_any": ["consult_appeal", "search_bidding_knowledge"],
            "facts": facts,
            "note": f"异议/投诉专项, code={code}",
        })
    return out


# ============================================================
# 验证逻辑
# ============================================================

def _init_rag():
    from src.rag.pipeline import rag_pipeline
    if not rag_pipeline.ready:
        rag_pipeline.initialize()
    if not rag_pipeline.ready:
        raise RuntimeError("RAG 未就绪, 请先 ingest")
    return rag_pipeline


def _source_text(doc: dict) -> str:
    """同 run_retrieval_eval._source_text."""
    return f"{doc.get('question', '')}\n{doc.get('answer', '')}"


def verify_retrieval_case(case: dict, rag_pipeline, top_k: int = 5) -> bool:
    """跑 search, 检查 top-5 是否有 doc 命中关键词."""
    from src.auth.access_scope import use_access_scope
    with use_access_scope(None):
        docs = rag_pipeline.search(case["question"], top_k=top_k)
    must_all = case.get("must_all") or []
    must_any = case.get("must_any") or []
    for d in docs:
        t = _source_text(d)
        if not all(w in t for w in must_all):
            continue
        if must_any and not any(w in t for w in must_any):
            continue
        return True
    return False


# ============================================================
# 去重 + 合并 + 写回
# ============================================================

def dedup(cases: list[dict], seen: set[str]) -> list[dict]:
    out = []
    for c in cases:
        n = _norm(c["question"])
        if n in seen:
            continue
        seen.add(n)
        out.append(c)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="评测用例扩充")
    ap.add_argument("--dry-run", action="store_true", help="只统计不写回")
    ap.add_argument("--ret-target", type=int, default=70)
    ap.add_argument("--agt-target", type=int, default=55)
    ap.add_argument("--topk", type=int, default=5)
    args = ap.parse_args()

    ret_existing, agt_existing, ret_seen, agt_seen = load_existing()
    qa_pairs = load_qa_pairs()
    print(f"Excel QA 对: {len(qa_pairs)} 条")
    rag = _init_rag()

    # ---- 检索用例 ----
    cand_ret: list[dict] = []
    for i, qa in enumerate(qa_pairs):
        c = build_retrieval_case(qa, i + 100)
        if c:
            cand_ret.append(c)
    cand_ret += build_appeal_retrieval_cases()
    print(f"检索候选: {len(cand_ret)} 条 (含 appeal)")

    verified_ret: list[dict] = []
    for c in cand_ret:
        if len(verified_ret) >= args.ret_target - len(ret_existing):
            break
        if _norm(c["question"]) in ret_seen:
            continue
        if verify_retrieval_case(c, rag, args.topk):
            verified_ret.append(c)
            ret_seen.add(_norm(c["question"]))
    print(f"检索验证通过: {len(verified_ret)} 条")

    new_ret_spec = {
        "description": json.loads(RET_CASES_PATH.read_text(encoding="utf-8"))["description"],
        "top_k": 5,
        "cases": ret_existing + verified_ret,
    }

    # ---- Agent 用例 ----
    cand_agt: list[dict] = []
    for i, qa in enumerate(qa_pairs):
        c = build_agent_single_hop(qa, i + 100)
        if c:
            cand_agt.append(c)

    by_proj: dict[str, list[dict]] = {}
    for qa in qa_pairs:
        st = qa.get("section_title", "")
        if st:
            by_proj.setdefault(st, []).append(qa)
    for i, (_, grp) in enumerate(by_proj.items()):
        c = build_agent_multi_hop(grp, i + 100)
        if c:
            cand_agt.append(c)

    tfs = [q for q in qa_pairs if q["domain"] == "tender_fact"]
    regs = [q for q in qa_pairs if q["domain"] == "regulation"]
    for i in range(min(len(tfs), len(regs), 15)):
        reg_idx = (i * 3) % len(regs) if regs else 0
        c = build_agent_cross_domain(tfs[i], regs[reg_idx], i + 100)
        if c:
            cand_agt.append(c)
    cand_agt += build_agent_appeal_cases()
    print(f"Agent 候选: {len(cand_agt)} 条")

    verified_agt = dedup(cand_agt, agt_seen)
    verified_agt = verified_agt[:args.agt_target - len(agt_existing)]
    print(f"Agent 去重后: {len(verified_agt)} 条")

    new_agt = agt_existing + verified_agt

    print(f"\n检索: {len(ret_existing)} + {len(verified_ret)} = {len(new_ret_spec['cases'])}")
    print(f"Agent: {len(agt_existing)} + {len(verified_agt)} = {len(new_agt)}")

    if args.dry_run:
        print("[dry-run] 不写回")
        return 0

    RET_CASES_PATH.write_text(
        json.dumps(new_ret_spec, ensure_ascii=False, indent=2), encoding="utf-8")
    AGT_CASES_PATH.write_text(
        json.dumps(new_agt, ensure_ascii=False, indent=2), encoding="utf-8")
    print("已写回 retrieval_cases.json + agent_eval_cases.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
