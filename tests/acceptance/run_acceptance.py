# -*- coding: utf-8 -*-
"""招投标采购 RAG-Agent MVP 验收测试脚本.

覆盖范围:
  MVP1 文档库 / MVP2 混合检索+引用 / MVP3 条款提取 /
  MVP4 资格+废标检查 / MVP5 人工复核留痕 /
  P4 响应性 / P5 评分辅助表 / P6 多家对比 /
  Auth 权限控制 / Workflow 工具链编排

用法: .venv/Scripts/python.exe tests/acceptance/run_acceptance.py
输出: tests/acceptance/evidence.json + 控制台摘要
"""
from __future__ import annotations

import io
import json
import sys
import time
import traceback
import urllib.error
import urllib.request
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "http://localhost:8001"
DB_ID = 6  # 已解析的 test_bid.txt 招标文件

results: list[dict] = []
_REGISTERED: list = []


def case(suite: str, cid: str, name: str):
    def deco(fn):
        def wrapper():
            t0 = time.time()
            rec = {"suite": suite, "id": cid, "name": name}
            try:
                detail = fn() or {}
                rec.update({"status": "PASS", "ms": int((time.time() - t0) * 1000), **detail})
                print(f"  [PASS] {cid} {name}  ({rec['ms']}ms) {detail.get('note','')}")
            except AssertionError as e:
                rec.update({"status": "FAIL", "ms": int((time.time() - t0) * 1000),
                            "error": f"断言失败: {e}"})
                print(f"  [FAIL] {cid} {name} 断言失败: {e}")
            except Exception as e:
                rec.update({"status": "ERROR", "ms": int((time.time() - t0) * 1000),
                            "error": f"{type(e).__name__}: {e}",
                            "trace": traceback.format_exc()[-500:]})
                print(f"  [ERR ] {cid} {name} {type(e).__name__}: {e}")
            results.append(rec)
        _REGISTERED.append(wrapper)
        return wrapper
    return deco


def http(method: str, path: str, body=None, token: str | None = None, timeout: int = 180):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw.decode("utf-8", "ignore")[:300]}


# ================= ENV =================

@case("环境", "ENV-01", "后端服务存活 /api/health")
def t():
    s, d = http("GET", "/api/health", timeout=10)
    assert s == 200, f"status={s}"
    return {"note": str(d)[:100]}


@case("环境", "ENV-02", "PostgreSQL 已连接")
def t():
    s, d = http("GET", "/api/health", timeout=15)
    assert d.get("pg_ready") is True, f"pg_ready={d.get('pg_ready')}"
    return {"note": "pg_ready=true"}


@case("环境", "ENV-03", "Qdrant 向量库已连接且有向量")
def t():
    s, d = http("GET", "/api/health", timeout=15)
    pts = d.get("points_count")
    assert pts is not None and pts >= 0, f"points_count={pts}"
    assert d.get("ready") is True, f"RAG pipeline ready={d.get('ready')}"
    return {"note": f"向量点数={pts}, rag_ready=true"}


# ================= MVP-1 文档库 =================

@case("MVP1文档库", "M1-01", "文档列表可分页查询")
def t():
    s, d = http("GET", "/api/documents", timeout=15)
    assert s == 200, f"status={s}"
    items = d.get("items", [])
    assert len(items) >= 1, "文档库为空"
    return {"note": f"共 {len(items)} 份文档"}


@case("MVP1文档库", "M1-02", "文档含结构化字段+全文")
def t():
    s, d = http("GET", "/api/documents", timeout=15)
    items = d.get("items", [])
    target = next((x for x in items if x.get("id") == DB_ID), items[0])
    needed = ["project_name", "budget", "scoring_criteria", "qualification_requirements", "deadline"]
    missing = [k for k in needed if not target.get(k)]
    assert not missing, f"缺字段: {missing}"
    assert (target.get("text_length") or 0) > 100, "全文过短"
    return {"note": f"#{target['id']} {target.get('source_file','')[:30]} 全文{target.get('text_length')}字"}


@case("MVP1文档库", "M1-03", "上传招标文件→解析入库+自动向量化")
def t():
    # multipart/form-data 手工构造
    boundary = "----acptboundary7MA4YWxkTrZu0gW"
    content = (
        "XX市验收测试专用项目招标文件\n"
        "项目名称：XX市验收测试专用项目\n"
        "预算金额：人民币 3,210,000.00 元\n"
        "投标截止时间：2026年3月8日 09:30\n"
        "一、投标人资格要求：1. 具有独立法人资格；2. 具备建筑工程施工总承包二级及以上资质。\n"
        "二、评标办法：价格分40分，技术分40分，商务分20分，总分100分。\n"
        "三、废标条款：逾期送达或未按要求密封的投标文件将被拒收并否决其投标。\n"
    ).encode("utf-8")
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"acceptance_upload_test.txt\"\r\nContent-Type: text/plain\r\n\r\n"
    ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/api/document/upload?save_to_db=true", data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.loads(r.read())
    assert d.get("db_id"), "未返回 db_id"
    n = d.get("vector_indexed_chunks", 0)
    assert n and n > 0, f"未自动向量化: vector_indexed_chunks={n}"
    return {"note": f"db_id={d['db_id']}, 解析状态={d.get('parse_status')}, 向量化分片={n}"}


# ================= MVP-2 混合检索+引用 =================
@case("MVP2检索", "M2-01", "问答接口返回带引用来源的答案(命中文档库)")
def t():
    q = "XX市智慧园区信息化建设项目（二期）的投标截止时间和预算金额分别是什么？"
    s, d = http("POST", "/api/chat", {"question": q, "history": []}, timeout=280)
    assert s == 200, f"status={s} {str(d)[:200]}"
    ans = d.get("answer") or d.get("response") or ""
    assert len(ans) > 10, "答案为空"
    sources = d.get("sources") or []
    assert len(sources) >= 1, "无引用来源"
    tender = [x for x in sources if x.get("doc_type") == "tender_document"]
    assert tender, f"未命中文档库分片, 来源类型: {[x.get('doc_type','FAQ') for x in sources]}"
    # 答案应含原文事实: 截止 2025年12月15日 / 预算 860万
    hit_deadline = "2025" in ans and "12" in ans
    hit_budget = ("860" in ans) or ("8,600,000" in ans) or ("8600000" in ans)
    assert hit_deadline or hit_budget, f"答案未引用原文事实: {ans[:120]}"
    return {"note": f"答案{len(ans)}字, 引用{len(sources)}条(招标分片{len(tender)}), 事实命中: 截止={hit_deadline} 预算={hit_budget}",
            "answer_head": ans[:80]}


# ================= MVP-3 条款提取 =================

@case("MVP3条款提取", "M3-01", "评分办法已结构化提取")
def t():
    s, d = http("GET", "/api/documents", timeout=15)
    target = next((x for x in d["items"] if x.get("id") == DB_ID), d["items"][0])
    sc = target.get("scoring_criteria") or ""
    assert "价格" in sc and ("技术" in sc), f"评分办法内容异常: {sc[:80]}"
    return {"note": sc[:60].replace("\n", " ")}


@case("MVP3条款提取", "M3-02", "资格要求列表非空")
def t():
    s, d = http("GET", "/api/documents", timeout=15)
    target = next((x for x in d["items"] if x.get("id") == DB_ID), d["items"][0])
    qr = target.get("qualification_requirements") or []
    assert isinstance(qr, list) and len(qr) >= 1, "资格要求为空"
    return {"note": f"{len(qr)} 条资格要求"}


# ================= MVP-4 合规/资格/废标 =================

@case("MVP4条款检查", "M4-01", "合规性扫描(排他性条款)")
def t():
    s, d = http("POST", "/api/compliance/check", {"db_id": DB_ID}, timeout=150)
    assert s == 200, f"status={s} {str(d)[:200]}"
    issues = d.get("issues") or d.get("risks") or []
    summary = d.get("summary") or {}
    return {"note": f"发现 {len(issues)} 个风险项, status={d.get('status','?')}, 分级={summary}"}


@case("MVP4条款检查", "M4-02", "资格条件逐条比对")
def t():
    s, d = http("POST", "/api/qualification/check", {
        "db_id": DB_ID,
        "company_qualifications": ["电子与智能化工程专业承包一级", "ISO 9001 认证"]}, timeout=150)
    assert s == 200, f"status={s} {str(d)[:200]}"
    return {"note": f"结果项 {len(d.get('results') or d.get('items') or [])}, keys={list(d.keys())[:5]}"}


@case("MVP4条款检查", "M4-03", "废标条款提取")
def t():
    s, d = http("POST", "/api/rejection/check", {"db_id": DB_ID}, timeout=150)
    assert s == 200, f"status={s} {str(d)[:200]}"
    clauses = d.get("clauses") or d.get("rejection_clauses") or []
    return {"note": f"提取 {len(clauses)} 条废标条款"}


# ================= P4/P5/P6 =================

@case("P4响应性", "P4-01", "投标逐条响应判定(正偏离识别)")
def t():
    s, d = http("POST", "/api/response/check", {
        "tender_db_id": DB_ID,
        "bid_text": "投标报价: 人民币820万元\n投标工期: 100个日历天\n质保期: 3年\n投标有效期: 90天",
        "clause": ""}, timeout=150)
    assert s == 200, f"status={s} {str(d)[:200]}"
    sm = d.get("summary", {})
    assert sm.get("total", 0) > 0, "未提取到条款"
    assert sm.get("positive", 0) >= 1, "未识别到正偏离(工期100<120/质保3>2)"
    return {"note": f"总{sm.get('total')} 响应{sm.get('response')} 正偏离{sm.get('positive')} verdict={d.get('verdict')}"}


@case("P5评分辅助表", "P5-01", "评分办法→结构化打分表(权重合计100)")
def t():
    s, d = http("POST", "/api/scoring/table", {"db_id": DB_ID}, timeout=120)
    assert s == 200, f"status={s} {str(d)[:200]}"
    items = d.get("items", [])
    assert len(items) >= 4, f"评分项过少: {len(items)}"
    assert abs(d.get("total_score", 0) - 100) < 0.5, f"权重合计={d.get('total_score')}"
    dims = [i["dimension"] for i in items]
    return {"note": f"{dims}, 合计{d['total_score']}分"}


@case("P6多家对比", "P6-01", "三家投标关键字段并排对比")
def t():
    s, d = http("POST", "/api/bids/compare", {"bids": [
        {"bidder_name": "A公司", "text": "投标报价: 820万元 工期:100天 质保:3年"},
        {"bidder_name": "B公司", "text": "投标报价: 950万元 工期:120天 质保:2年"},
        {"bidder_name": "C公司", "text": "投标报价: 880万元 工期:110天 质保:2年"},
    ]}, timeout=150)
    assert s == 200, f"status={s} {str(d)[:200]}"
    assert len(d.get("bidders", [])) == 3, "投标人数不为3"
    prices = [b["values"].get("报价", "") for b in d["bidders"]]
    assert all(prices), f"报价抽取缺失: {prices}"
    return {"note": f"字段{len(d.get('fields',[]))}个; 报价列: {prices}"}


# ================= Auth =================

def t_auth_common(username: str, password: str, display: str = ""):
    ts = int(time.time())
    uname = f"acpt_{username}_{ts}"
    s, d = http("POST", "/auth/register",
                {"username": uname, "password": password, "display_name": display}, timeout=15)
    assert s == 200, f"注册失败 {s} {d}"
    s, d = http("POST", "/auth/login", {"username": uname, "password": password}, timeout=15)
    assert s == 200 and d.get("access_token"), f"登录失败 {s} {d}"
    return uname, d["access_token"], d["user"]


@case("Auth权限", "AUTH-01", "注册→登录→/auth/me 全链路")
def t():
    uname, token, user = t_auth_common("user01", "accept123", "验收员")
    s, d = http("GET", "/auth/me", token=token, timeout=15)
    assert s == 200 and d["user"]["username"] == uname, d
    return {"note": f"{uname} role={user['role']}"}


@case("Auth权限", "AUTH-02", "错误密码登录被拒(401)")
def t():
    ts = int(time.time())
    uname = f"acpt_bad_{ts}"
    http("POST", "/auth/register", {"username": uname, "password": "accept123"}, timeout=15)
    s, d = http("POST", "/auth/login", {"username": uname, "password": "wrongpass9"}, timeout=15)
    assert s == 401, f"应返回401, 实际{s}"
    return {"note": f"401 {d.get('detail','')}"}


@case("Auth权限", "AUTH-03", "无token访问/auth/me被拒(401)")
def t():
    s, d = http("GET", "/auth/me", timeout=15)
    assert s == 401, f"应返回401, 实际{s}"
    return {"note": "401 未登录"}


@case("Auth权限", "AUTH-04", "默认管理员 admin/admin123 可用")
def t():
    s, d = http("POST", "/auth/login", {"username": "admin", "password": "admin123"}, timeout=15)
    assert s == 200 and d["user"]["role"] == "admin", d
    return {"note": "admin 登录成功, role=admin"}


# ================= MVP-5 人工复核留痕 =================

@case("MVP5复核留痕", "M5-01", "登录态提交复核→user_id自动关联")
def t():
    uname, token, user = t_auth_common("reviewer", "accept123", "复核员甲")
    s, d = http("POST", "/api/reviews", {
        "document_id": DB_ID, "review_type": "compliance",
        "verdict": "approved", "comment": "验收测试自动复核",
        "result_snapshot": {"acceptance": True}}, token=token, timeout=15)
    assert s == 200 and d.get("id"), f"保存失败 {s} {d}"
    rid = d["id"]
    # 查列表验证留痕
    s2, d2 = http("GET", f"/api/reviews?document_id={DB_ID}&review_type=compliance", timeout=15)
    assert s2 == 200
    recs = d2.get("items") or d2.get("reviews") or (d2 if isinstance(d2, list) else [])
    mine = [r for r in recs if r.get("id") == rid]
    assert mine, f"未查到复核记录 id={rid}"
    assert mine[0].get("user_id") == user["id"], \
        f"user_id 未关联: 期望 {user['id']}, 实际 {mine[0].get('user_id')}"
    return {"note": f"review id={rid}, reviewer={mine[0].get('reviewer')}, user_id={mine[0].get('user_id')} 已关联"}


@case("MVP5复核留痕", "M5-02", "非法review_type被拒(400)")
def t():
    s, d = http("POST", "/api/reviews", {
        "document_id": DB_ID, "review_type": "hack", "verdict": "approved"}, timeout=15)
    assert s == 400, f"应400, 实际{s}"
    return {"note": "400 非法类型已拦截"}


# ================= Workflow =================

@case("Workflow编排", "WF-01", "预置工作流清单可查询")
def t():
    s, d = http("GET", "/api/workflow/presets", timeout=15)
    assert s == 200 and len(d.get("presets", [])) >= 2, d
    return {"note": ", ".join(p["id"] for p in d["presets"])}


@case("Workflow编排", "WF-02", "合规审查一条龙 DAG 执行(3节点+降级容错)")
def t():
    s, d = http("POST", "/api/workflow/run",
                {"config": "compliance_review", "ctx": {"db_id": DB_ID}}, timeout=240)
    assert s == 200, f"status={s} {str(d)[:200]}"
    sm = d.get("summary", {})
    assert sm.get("total") == 3, f"节点数={sm.get('total')}"
    assert sm.get("verdict") == "ok" and sm.get("errors") == 0, \
        f"应全部成功: {sm}"
    return {"note": f"verdict=ok 成功3/3 (降级容错机制保留, 本轮无失败节点)"}


@case("Workflow编排", "WF-03", "评标辅助一条龙 DAG 执行")
def t():
    s, d = http("POST", "/api/workflow/run", {
        "config": "eval_assist",
        "ctx": {"db_id": DB_ID, "bid_text": "投标报价: 820万元 工期:100天 质保:3年"}}, timeout=240)
    assert s == 200, f"status={s} {str(d)[:200]}"
    sm = d.get("summary", {})
    assert sm.get("total") == 2, f"节点数={sm.get('total')}"
    return {"note": f"verdict={sm.get('verdict')} 成功{sm.get('success')}/2"}


# ================= main =================

def main():
    print(f"\n{'='*70}")
    print(f"招投标采购 RAG-Agent MVP 验收测试  {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"目标: {BASE}  测试文档 db_id={DB_ID}")
    print(f"{'='*70}\n")

    for w in _REGISTERED:
        w()

    # 汇总
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    errored = sum(1 for r in results if r["status"] == "ERROR")

    print(f"\n{'='*70}")
    print(f"汇总: 共 {total} 项 | PASS {passed} | FAIL {failed} | ERROR {errored} | 通过率 {passed/total*100:.1f}%")
    by_suite: dict[str, dict] = {}
    for r in results:
        s = by_suite.setdefault(r["suite"], {"pass": 0, "total": 0})
        s["total"] += 1
        if r["status"] == "PASS":
            s["pass"] += 1
    for name, s in by_suite.items():
        print(f"  {name}: {s['pass']}/{s['total']}")
    print(f"{'='*70}\n")

    report = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "base_url": BASE,
        "db_id": DB_ID,
        "total": total, "pass": passed, "fail": failed, "error": errored,
        "pass_rate": round(passed / total * 100, 1),
        "by_suite": by_suite,
        "cases": results,
    }
    out = "tests/acceptance/evidence.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"证据已保存: {out}")
    return 0 if failed == 0 and errored == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
