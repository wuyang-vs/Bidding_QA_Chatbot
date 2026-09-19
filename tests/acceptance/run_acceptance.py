# -*- coding: utf-8 -*-
"""招投标采购 RAG-Agent MVP 验收测试脚本.

覆盖范围:
  MVP1 文档库 / MVP2 混合检索+引用 / MVP3 条款提取 /
  MVP4 资格+废标检查 / MVP5 人工复核留痕 /
  P4 响应性 / P5 评分辅助表 / P6 多家对比 /
  P7 报价计算 / P8 投标文件解析器 / P9 围串标线索 /
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
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "http://localhost:8001"
HERE = Path(__file__).resolve().parent
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


@case("MVP2检索", "GATE-01", "硬闸门: 知识库无证据的问题禁止LLM自由生成")
def t():
    q = "月球表面氦3开采基地绿化景观工程的投标保证金缴纳比例和开标时间是怎么规定的？"
    s, d = http("POST", "/api/chat", {"question": q, "history": []}, timeout=280)
    assert s == 200, f"status={s} {str(d)[:200]}"
    assert d.get("gated") is True, f"应被硬闸门标记 gated=True, 实际 {d.get('gated')}"
    assert not (d.get("sources") or []), "无证据问题不应返回任何引用来源"
    ans = d.get("answer") or ""
    assert "未在本地权威知识库中检索到" in ans, f"固定话术不符: {ans[:120]}"
    # 不得编造具体数字(保证金比例/金额/日期)
    assert "%" not in ans and "万元" not in ans, f"固定话术中混入编造事实: {ans[:150]}"
    return {"note": f"gated=True, sources=0, 返回受控拒答话术({len(ans)}字)"}


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


# ================= P7 报价计算 (纯规则) =================

@case("P7报价计算", "P7-01", "正确报价表: 算术/汇总/大写/价格分")
def t():
    s, d = http("POST", "/api/price/calculate", {
        "items": [
            {"name": "服务器", "qty": 10, "unit_price": 50000, "amount": 500000},
            {"name": "交换机", "qty": 5, "unit_price": 8000, "amount": 40000},
            {"name": "实施服务", "qty": 1, "unit_price": 200000, "amount": 200000}],
        "declared_total": 740000, "declared_total_cn": "柒拾肆万元整",
        "control_price": 1000000, "all_bid_prices": [740000, 800000]}, timeout=30)
    assert s == 200, f"status={s} {d}"
    assert d["verdict"] == "pass", f"应无异常: {d['anomalies']}"
    assert d["subtotal"] == 740000, d["subtotal"]
    assert d["cn_amount"] == 740000, d["cn_amount"]
    assert d["price_score"] == 100.0, f"最低价应满分: {d['price_score']}"
    return {"note": f"合计{d['subtotal']} 大写校验一致 价格分{d['price_score']} verdict=pass"}


@case("P7报价计算", "P7-02", "异常检出: 行内算术不符+超最高限价")
def t():
    s, d = http("POST", "/api/price/calculate", {
        "items": [
            {"name": "服务器", "qty": 10, "unit_price": 50000, "amount": 600000},
            {"name": "实施服务", "qty": 1, "unit_price": 200000, "amount": 200000}],
        "declared_total": 800000, "control_price": 700000}, timeout=30)
    assert s == 200 and d["verdict"] == "fail", f"应判fail: {s} {d.get('verdict')}"
    codes = {a["code"] for a in d["anomalies"]}
    assert "ROW_ARITHMETIC" in codes, f"未检出行内错误: {codes}"
    assert "OVER_CONTROL_PRICE" in codes, f"未检出超限价: {codes}"
    return {"note": f"verdict=fail, 异常={sorted(codes)}"}


@case("P7报价计算", "P7-03", "大小写金额不一致检出")
def t():
    s, d = http("POST", "/api/price/calculate", {
        "items": [{"name": "设备", "qty": 1, "unit_price": 740000, "amount": 740000}],
        "declared_total": 740000, "declared_total_cn": "柒拾伍万元整"}, timeout=30)
    assert s == 200
    codes = {a["code"] for a in d["anomalies"]}
    assert "CN_MISMATCH" in codes, f"未检出大小写不符: {codes}"
    return {"note": "大写750000 vs 数字740000 → CN_MISMATCH"}


# ================= P8 投标文件解析器 =================

_BID_TEXT = (
    "投标函\n项目名称：XX市智慧园区信息化建设项目（二期）\n投标人：验收测试科技有限公司\n"
    "投标总报价：人民币 820 万元\n工期：100 个日历天\n质保期：3 年\n"
    "投标有效期：90 天\n投标保证金：16 万元\n"
    "本项目采用微服务架构与国产化服务器，关键技术参数全部满足并优于招标要求。\n"
    "我司具备电子与智能化工程专业承包贰级资质，近三年完成两个同类信息化项目。\n"
    "售后服务：2 小时响应、4 小时到场。项目经理为高级工程师。\n"
    "付款方式：验收合格后支付 95%，质保金 5%。"
)


@case("P8投标解析器", "P8-01", "单份投标→商务/技术/资格三维度结构化")
def t():
    s, d = http("POST", "/api/bid/parse",
                {"bidder_name": "验收测试科技有限公司", "text": _BID_TEXT}, timeout=150)
    assert s == 200 and d.get("parse_status") == "ok", f"status={s} {str(d)[:200]}"
    c = d.get("commercial") or {}
    filled_c = [k for k, v in c.items() if v]
    assert len(filled_c) >= 4, f"商务字段不足: {filled_c}"
    tech = d.get("technical") or {}
    filled_t = [k for k, v in tech.items() if v]
    assert len(filled_t) >= 2, f"技术维度字段不足: {filled_t}"
    assert len(d.get("qualifications") or []) >= 1, "资质未抽出"
    assert d.get("fields", {}).get("报价"), "fields 报价缺失(多家对比兼容)"
    return {"note": f"商务{len(filled_c)}/6 技术{len(filled_t)}/4 资质{len(d.get('qualifications',[]))}条 "
                    f"报价={c.get('报价')} 工期={c.get('工期')}"}


# ================= P9 围串标线索 =================

_COLLUSION_SENT = ("我方将严格按照ISO9001质量管理体系组织项目实施，确保系统一次验收合格率达到百分之百，"
                   "售后服务响应时间不超过两小时，质保期内免费上门维护并更换故障部件。")


@case("P9围串标线索", "P9-01", "雷同文本+接近报价→线索输出(不定性)")
def t():
    s, d = http("POST", "/api/collusion/detect", {"bids": [
        {"bidder_name": "甲公司", "text": "投标报价：人民币 820 万元。" + _COLLUSION_SENT},
        {"bidder_name": "乙公司", "text": "投标报价：人民币 822 万元。" + _COLLUSION_SENT},
        {"bidder_name": "丙公司", "text": "我司投标总报价 950 万元，具备建筑工程总承包一级资质，质保两年。"}]},
        timeout=60)
    assert s == 200, f"status={s} {d}"
    assert d["verdict"] == "clues_found", d["verdict"]
    clues = d.get("clues", [])
    assert len(clues) >= 2, f"线索不足: {len(clues)}"
    dims = {c["dimension"] for c in clues}
    assert "文本雷同" in dims and "报价规律" in dims, f"维度缺失: {dims}"
    # 每条线索须含等级/理由/双方证据
    c0 = clues[0]
    assert c0.get("level") and c0.get("reason") and "evidence" in c0, c0
    # 严禁自动定性
    assert "不构成" in d.get("disclaimer", ""), "缺少不定性免责声明"
    return {"note": f"{len(clues)}条线索 维度={dims}; 高{d['summary']['high']} 中{d['summary']['medium']}; 仅提示不定性"}


@case("P9围串标线索", "P9-02", "内容独立的投标→无线索 clean")
def t():
    s, d = http("POST", "/api/collusion/detect", {"bids": [
        {"bidder_name": "丁公司", "text": "投标报价 680 万元，采用集装箱模块化机房方案，冬季施工。"},
        {"bidder_name": "戊公司", "text": "投标总报价 910 万元，以分布式光纤组网，项目团队含五名注册建造师。"}]},
        timeout=60)
    assert s == 200 and d["verdict"] == "clean", f"应clean: {d.get('verdict')} {d.get('clues')}"
    assert d["summary"]["total_clues"] == 0
    return {"note": "两家内容/报价独立, verdict=clean"}


@case("P9围串标线索", "P9-03", "少于2份投标被拒(400)")
def t():
    s, d = http("POST", "/api/collusion/detect",
                {"bids": [{"bidder_name": "孤家", "text": "xxx"}]}, timeout=30)
    assert s == 400, f"应400, 实际{s}"
    return {"note": "400 输入校验生效"}


@case("P9围串标线索", "P9-04", "围串标已注册为工作流节点(自定义配置)")
def t():
    cfg = {"name": "围串标快速扫描", "nodes": [
        {"id": "c", "tool": "collusion_check",
         "params": {"bids": [
             {"bidder_name": "甲公司", "text": "投标报价：820 万元。" + _COLLUSION_SENT},
             {"bidder_name": "乙公司", "text": "投标报价：821 万元。" + _COLLUSION_SENT}]}}]}
    s, d = http("POST", "/api/workflow/run", {"config": cfg, "ctx": {}}, timeout=120)
    assert s == 200 and d["summary"]["success"] == 1, f"工作流节点失败: {s} {str(d)[:200]}"
    out = d["raw"]["c"]["output"]
    assert out["verdict"] == "clues_found", out.get("verdict")
    return {"note": f"collusion_check 节点执行成功, 线索{out['summary']['total_clues']}条"}


# ================= Auth =================

def t_auth_common(username: str, password: str, display: str = "", role: str = "bidder"):
    ts = int(time.time())
    uname = f"acpt_{username}_{ts}"
    s, d = http("POST", "/auth/register",
                {"username": uname, "password": password,
                 "display_name": display, "role": role}, timeout=15)
    assert s == 200, f"注册失败 {s} {d}"
    assert d.get("role") == role, f"注册返回角色不符: {d.get('role')} != {role}"
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

@case("MVP5复核留痕", "M5-01", "管理员建专家号→登录提交复核→user_id自动关联")
def t():
    # auditor 不允许自助注册, 由 admin 账号创建
    ts = int(time.time())
    uname = f"acpt_reviewer_{ts}"
    s, d = http("POST", "/auth/login",
                {"username": "admin", "password": "admin123"}, timeout=15)
    assert s == 200, f"admin 登录失败 {s}"
    admin_tok = d["access_token"]
    s, d = http("POST", "/auth/admin/users",
                {"username": uname, "password": "accept123",
                 "display_name": "复核员甲", "role": "auditor"},
                token=admin_tok, timeout=15)
    assert s == 200 and d.get("role") == "auditor", f"管理员创建 auditor 失败 {s} {d}"
    s, d = http("POST", "/auth/login",
                {"username": uname, "password": "accept123"}, timeout=15)
    assert s == 200 and d.get("access_token"), f"专家登录失败 {s} {d}"
    token, user = d["access_token"], d["user"]
    s, d = http("POST", "/api/reviews", {
        "document_id": DB_ID, "review_type": "compliance",
        "verdict": "approved", "comment": "验收测试自动复核",
        "result_snapshot": {"acceptance": True}}, token=token, timeout=15)
    assert s == 200 and d.get("id"), f"保存失败 {s} {d}"
    rid = d["id"]
    # 查列表验证留痕
    s2, d2 = http("GET", f"/api/reviews?document_id={DB_ID}&review_type=compliance",
                  token=token, timeout=15)
    assert s2 == 200
    recs = d2.get("items") or d2.get("reviews") or (d2 if isinstance(d2, list) else [])
    mine = [r for r in recs if r.get("id") == rid]
    assert mine, f"未查到复核记录 id={rid}"
    assert mine[0].get("user_id") == user["id"], \
        f"user_id 未关联: 期望 {user['id']}, 实际 {mine[0].get('user_id')}"
    return {"note": f"admin建 auditor {uname}; review id={rid}, user_id={mine[0].get('user_id')} 已关联"}


@case("MVP5复核留痕", "M5-02", "非法review_type被拒(400)")
def t():
    s, d = http("POST", "/api/reviews", {
        "document_id": DB_ID, "review_type": "hack", "verdict": "approved"}, timeout=15)
    assert s == 400, f"应400, 实际{s}"
    return {"note": "400 非法类型已拦截"}


# ================= RBAC 角色权限隔离 =================

RBAC_STATE = {}


def upload_multipart(filename: str, content: bytes, content_type: str = "text/plain",
                     token: str | None = None, fields: dict | None = None,
                     timeout: int = 180):
    boundary = "----acptrbacBoundary7MA4YWxk"
    body = b""
    for k, v in (fields or {}).items():
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n"
                 f"{v}\r\n").encode("utf-8")
    body += (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"{filename}\"\r\nContent-Type: {content_type}\r\n\r\n"
    ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        f"{BASE}/api/document/upload?save_to_db=true", data=body,
        method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw.decode("utf-8", "ignore")[:300]}


def list_ids(token: str | None = None):
    s, d = http("GET", "/api/documents", token=token, timeout=20)
    assert s == 200, f"文档列表失败 {s}"
    return {x["id"]: x for x in d.get("items", [])}


@case("RBAC权限隔离", "RBAC-01", "投标人自助注册; 冒充admin注册被强制降级")
def t():
    _uname, token, user = t_auth_common("rbac_bidder", "accept123", role="bidder")
    assert user["role"] == "bidder", user
    ts = int(time.time())
    s, d = http("POST", "/auth/register",
                {"username": f"acpt_fakeadmin_{ts}", "password": "accept123",
                 "role": "admin"}, timeout=15)
    assert s == 200 and d.get("role") == "bidder", f"提权注册未被降级: {d}"
    RBAC_STATE["bidder_token"] = token
    return {"note": f"bidder={user['username']}; role=admin 自助注册已降级为 bidder"}


@case("RBAC权限隔离", "RBAC-02", "投标人被禁: 写复核/查复核/围串标检测 均403")
def t():
    _u, token, _user = t_auth_common("rbac_forbidden", "accept123", role="bidder")
    s1, _ = http("POST", "/api/reviews",
                 {"document_id": DB_ID, "review_type": "compliance", "verdict": "approved"},
                 token=token, timeout=15)
    s2, _ = http("GET", "/api/reviews", token=token, timeout=15)
    s3, _ = http("POST", "/api/collusion/detect", {"bids": []}, token=token, timeout=15)
    assert (s1, s2, s3) == (403, 403, 403), f"应全403, 实际 {s1},{s2},{s3}"
    return {"note": f"reviews POST/GET={s1}/{s2}, collusion={s3}"}


@case("RBAC权限隔离", "RBAC-02B", "管理员建号端点: 匿名401/投标人403")
def t():
    ts = int(time.time())
    s1, _ = http("POST", "/auth/admin/users",
                 {"username": f"acpt_x_{ts}", "password": "accept123", "role": "auditor"},
                 timeout=15)
    _u, token, _ = t_auth_common("rbac_notadmin", "accept123", role="bidder")
    s2, _ = http("POST", "/auth/admin/users",
                 {"username": f"acpt_y_{ts}", "password": "accept123", "role": "auditor"},
                 token=token, timeout=15)
    assert s1 == 401 and s2 == 403, f"应 401/403, 实际 {s1}/{s2}"
    return {"note": f"anonymous={s1}, bidder={s2}"}


@case("RBAC权限隔离", "RBAC-03", "招标人上传内部文档→按角色行级可见性隔离")
def t():
    _ua, tok_a, _ua_info = t_auth_common("rbac_purchaser_a", "accept123", role="purchaser")
    _ub, tok_b, _ = t_auth_common("rbac_purchaser_b", "accept123", role="purchaser")
    _uc, tok_c, _ = t_auth_common("rbac_bidder_c", "accept123", role="bidder")
    _ad, d_ad = http("POST", "/auth/login",
                     {"username": "admin", "password": "admin123"}, timeout=15)
    tok_admin = d_ad["access_token"]

    content = (
        "XX市权限隔离内部项目(评标内部文件)\n项目名称：XX市权限隔离内部项目\n"
        "预算金额：人民币 880 万元\n投标截止时间：2026年9月1日 10:00\n"
        "本文件含评标基准价计算过程, 属评标内部资料, 不对外公开。\n"
    ).encode("utf-8")
    s, d = upload_multipart("rbac_internal.txt", content, token=tok_a,
                            fields={"visibility": "internal", "package": "PKG-A"})
    assert s == 200, f"招标人上传 internal 失败 {s} {d}"
    assert d.get("visibility") == "internal", d
    doc_id = d["db_id"]
    RBAC_STATE["internal_doc"] = doc_id

    ids_a = list_ids(tok_a); ids_b = list_ids(tok_b)
    ids_c = list_ids(tok_c); ids_admin = list_ids(tok_admin)
    assert doc_id in ids_a, "owner 招标人 A 应可见自己的 internal 文档"
    assert doc_id not in ids_b, "招标人 B 不应看到他人 internal 文档"
    assert doc_id not in ids_c, "投标人不应看到 internal 文档"
    assert doc_id in ids_admin, "管理员应可见全部文档"
    assert ids_a[doc_id].get("package") == "PKG-A", "包件号未持久化"
    return {"note": f"internal doc_id={doc_id}: A可见/B不可见/bidder不可见/admin可见, package=PKG-A"}


@case("RBAC权限隔离", "RBAC-04", "投标人/匿名访问内部文档检查端点均403")
def t():
    doc_id = RBAC_STATE.get("internal_doc")
    assert doc_id, "前置 RBAC-03 未产生 internal_doc"
    _u, token, _ = t_auth_common("rbac_reader", "accept123", role="bidder")
    s1, _ = http("POST", "/api/compliance/check", {"db_id": doc_id}, token=token, timeout=15)
    s2, _ = http("POST", "/api/compliance/check", {"db_id": doc_id}, timeout=15)
    assert s1 == 403, f"投标人应 403, 实际 {s1}"
    assert s2 == 403, f"匿名应 403, 实际 {s2}"
    return {"note": f"doc {doc_id}: bidder={s1}, anonymous={s2}"}


@case("RBAC权限隔离", "RBAC-05", "投标人不得公开上传; 默认为internal且本人可见他人不可见")
def t():
    _u1, tok1, _ = t_auth_common("rbac_bid_self", "accept123", role="bidder")
    _u2, tok2, _ = t_auth_common("rbac_bid_other", "accept123", role="bidder")
    content = ("XX市投标文件(投标人上传)\n投标人：测试有限公司\n投标报价：799万元\n").encode("utf-8")
    # 显式 public 必须被拒
    s, d = upload_multipart("bid_public.txt", content, token=tok1,
                            fields={"visibility": "public"}, timeout=30)
    assert s == 403, f"投标人显式 public 应 403, 实际 {s} {d}"
    # 默认 auto → internal
    s, d = upload_multipart("bid_auto.txt", content, token=tok1, timeout=180)
    assert s == 200 and d.get("visibility") == "internal", f"默认应 internal: {s} {d}"
    bid_doc = d["db_id"]
    ids1, ids2 = list_ids(tok1), list_ids(tok2)
    assert bid_doc in ids1, "投标人应能看到本人上传的投标文件"
    assert bid_doc not in ids2, "其他投标人不应看到该投标文件"
    return {"note": f"public 上传 403; auto→internal doc={bid_doc}, 本人可见/他人不可见"}


@case("RBAC权限隔离", "META-01", "PDF按页解析页数回传 + 包件元数据持久化")
def t():
    _u, tok, _ = t_auth_common("rbac_pdf_owner", "accept123", role="purchaser")
    pdf_path = HERE / "sample_multipage.pdf"
    content = pdf_path.read_bytes()
    s, d = upload_multipart("sample_multipage.pdf", content,
                            content_type="application/pdf", token=tok,
                            fields={"visibility": "internal", "package": "PKG-PDF"},
                            timeout=240)
    assert s == 200, f"PDF 上传失败 {s} {str(d)[:200]}"
    assert d.get("page_count") == 2, f"页数应为2, 实际 {d.get('page_count')}"
    doc_id = d["db_id"]
    item = list_ids(tok)[doc_id]
    assert item.get("page_count") == 2, f"列表页数未持久化: {item.get('page_count')}"
    assert item.get("package") == "PKG-PDF", "包件号未持久化"
    return {"note": f"pdf doc={doc_id} page_count=2, package=PKG-PDF, chunks={d.get('vector_indexed_chunks')}"}


# ================= ⑥ 评审业务状态机 =================

def _stage_upload_doc(token: str, name: str, visibility: str = "public") -> int:
    ts = int(time.time())
    s, d = upload_multipart(
        f"{name}_{ts}.txt",
        f"评审状态机测试文档 {ts}\n评分办法: 价格60分 技术40分\n废标条款: 逾期拒收".encode("utf-8"),
        content_type="text/plain", token=token,
        fields={"visibility": visibility}, timeout=120)
    assert s == 200, f"状态机用例文档上传失败 {s} {str(d)[:200]}"
    return d["db_id"]


@case("评审状态机", "STAGE-01", "初评→质疑→复审→结案 合法流转+历史留痕+非法流转拦截")
def t():
    _u, tok, _ = t_auth_common("stage_owner", "accept123", role="purchaser")
    doc_id = _stage_upload_doc(tok, "stage_doc", visibility="public")
    path = "/api/review-stage/transition"

    def trans(action, comment=""):
        return http("POST", path, {"document_id": doc_id, "action": action, "comment": comment},
                    token=tok, timeout=30)

    # 初始为 none
    s, d = http("GET", f"/api/review-stage/{doc_id}", token=tok, timeout=15)
    assert s == 200 and d["stage"] == "none" and d["history"] == [], d

    for action, expect in (("start", "initial"), ("challenge", "challenge"),
                           ("start_recheck", "recheck"), ("close", "closed")):
        s, d = trans(action, f"备注-{action}")
        assert s == 200 and d["stage"] == expect, f"{action} 应→{expect}, 实际 {s} {d}"

    # 历史完整 4 条且顺序正确
    s, d = http("GET", f"/api/review-stage/{doc_id}", token=tok, timeout=15)
    acts = [h["action"] for h in d["history"]]
    assert acts == ["start", "challenge", "start_recheck", "close"], acts
    assert d["history"][0]["operator"], "操作人未留痕"
    assert d["stage_label"] == "结案" and d["history"][0]["to_stage_label"] == "初评", d

    # 结案后再流转 → 400; 未知动作 → 400
    s1, _ = trans("challenge")
    s2, _ = trans("not_an_action")
    assert s1 == 400 and s2 == 400, f"非法流转应400, 实际 {s1}/{s2}"
    return {"note": f"doc={doc_id} 全链路4步, history={acts}, 非法流转均400"}


@case("评审状态机", "STAGE-02", "状态机端点权限: 匿名401/投标人403/跨租户internal 403")
def t():
    _u, tok_a, _ = t_auth_common("stage_owner_a", "accept123", role="purchaser")
    internal_id = _stage_upload_doc(tok_a, "stage_internal", visibility="internal")
    public_id = _stage_upload_doc(tok_a, "stage_public", visibility="public")

    # 匿名: POST/GET 均 401
    s1, _ = http("POST", "/api/review-stage/transition",
                 {"document_id": public_id, "action": "start"}, timeout=15)
    s2, _ = http("GET", f"/api/review-stage/{public_id}", timeout=15)
    # bidder: public 文档可读但角色不足 → 403
    _u2, tok_b, _ = t_auth_common("stage_bidder", "accept123", role="bidder")
    s3, _ = http("POST", "/api/review-stage/transition",
                 {"document_id": public_id, "action": "start"}, token=tok_b, timeout=15)
    # 另一个 purchaser 对 A 的 internal 文档行级 403
    _u3, tok_c, _ = t_auth_common("stage_owner_c", "accept123", role="purchaser")
    s4, _ = http("POST", "/api/review-stage/transition",
                 {"document_id": internal_id, "action": "start"}, token=tok_c, timeout=15)
    # 文档不存在 → 404
    s5, _ = http("GET", "/api/review-stage/99999999", token=tok_a, timeout=15)
    assert (s1, s2, s3, s4, s5) == (401, 401, 403, 403, 404), \
        f"期望 401/401/403/403/404, 实际 {s1}/{s2}/{s3}/{s4}/{s5}"
    # owner 本人对 internal 文档可正常流转
    s6, d6 = http("POST", "/api/review-stage/transition",
                  {"document_id": internal_id, "action": "start"}, token=tok_a, timeout=15)
    assert s6 == 200 and d6["stage"] == "initial", d6
    return {"note": f"anon=401/401 bidder=403 cross-tenant=403 missing=404 owner=200"}


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


# ================= 标书生成闭环 =================

@case("标书生成闭环", "BID-01", "对话内触发 generate_bid_draft 工具生成标书章节")
def t():
    s, d = http("POST", "/api/chat",
                {"question": f"请根据{DB_ID}号招标文件帮我生成投标技术方案章节草稿",
                 "history": []}, timeout=300)
    assert s == 200, f"status={s} {str(d)[:200]}"
    names = [x.get("name") for x in d.get("exec_log", {}).get("tool_calls", [])]
    assert "generate_bid_draft" in names, f"LLM 未调用标书工具: {names}"
    assert d.get("gated") is not True, "有本地证据的生成不应被闸门拦截"
    ans = d.get("answer") or ""
    assert len(ans) > 300, f"章节答案过短: {len(ans)}"
    return {"note": f"工具={names}, 答案{len(ans)}字, gated={d.get('gated')}"}


@case("标书生成闭环", "BID-02", "/api/bid/section 单章同步生成(公开招标文件)")
def t():
    s, d = http("POST", "/api/bid/section",
                {"db_id": DB_ID, "section": "technical"}, timeout=300)
    assert s == 200, f"status={s} {str(d)[:200]}"
    md = d.get("markdown") or ""
    assert d.get("section_key") == "technical" and d.get("title"), d
    assert len(md) > 300, f"章节内容过短: {len(md)}"
    assert d["title"] in md, "Markdown 应含章节标题"
    # 非法章节 400
    s2, _ = http("POST", "/api/bid/section",
                 {"db_id": DB_ID, "section": "not_exist"}, timeout=30)
    assert s2 == 400, f"非法章节应400, 实际 {s2}"
    return {"note": f"title={d['title']}, {len(md)}字, 案例={d.get('similar_cases_found')}, 非法章节={s2}"}


@case("标书生成闭环", "BID-03", "单章生成行级权限: 投标人对internal 403/owner 200")
def t():
    _u, tok_owner, _ = t_auth_common("bid_owner", "accept123", role="purchaser")
    _u2, tok_bidder, _ = t_auth_common("bid_reader", "accept123", role="bidder")
    content = (
        "XX市标书闭环内部项目招标文件\n项目名称：XX市标书闭环内部项目\n"
        "预算金额：人民币 660 万元\n投标截止时间：2026年10月1日 09:30\n"
        "采购标的: 智慧园区管理平台软件开发与集成服务, 含三年运维。\n"
        "资质要求: 软件企业证书; 近三年同类项目业绩2个。\n"
    ).encode("utf-8")
    s, d = upload_multipart("bid_internal_tender.txt", content, token=tok_owner,
                            fields={"visibility": "internal"}, timeout=180)
    assert s == 200 and d.get("visibility") == "internal", f"internal 上传失败 {s} {d}"
    doc_id = d["db_id"]

    s1, _ = http("POST", "/api/bid/section",
                 {"db_id": doc_id, "section": "technical"}, token=tok_bidder, timeout=30)
    s2, _ = http("POST", "/api/bid/section",
                 {"db_id": doc_id, "section": "technical"}, timeout=30)
    assert s1 == 403, f"投标人对 internal 应 403, 实际 {s1}"
    assert s2 == 403, f"匿名对 internal 应 403, 实际 {s2}"
    # owner 本人可基于 internal 招标文件生成 (证明不是一刀切拒绝)
    s3, d3 = http("POST", "/api/bid/section",
                  {"db_id": doc_id, "section": "commercial"}, token=tok_owner, timeout=300)
    assert s3 == 200 and len(d3.get("markdown") or "") > 300, \
        f"owner 应能生成, 实际 {s3} {str(d3)[:200]}"
    return {"note": f"doc={doc_id} bidder={s1}/anon={s2}/owner={s3}({len(d3['markdown'])}字)"}


# ================= V1.4 企业资料库+占位符回填+对照表+整本合稿 =================

@case("V14企业资料库", "PROFILE-01", "企业资料库 1:1: 空档案→PUT→GET回显; 匿名401")
def t():
    _u, tok, _ = t_auth_common("profile", "accept123", display="资料库", role="bidder")
    company = f"华信闭环测试有限公司{int(time.time()) % 100000}"
    s0, _ = http("GET", "/api/profile", timeout=15)
    assert s0 == 401, f"匿名 GET 应401, 实际 {s0}"
    s, d = http("GET", "/api/profile", token=tok, timeout=15)
    assert s == 200 and d["profile"].get("company_name") == "", f"空档案不符 {s} {str(d)[:200]}"
    payload = {
        "company_name": company, "company_short": "华信闭环", "legal_person": "李四",
        "contact_phone": "13900001111", "registered_capital": "人民币5000万元",
        "certs": [{"name": "软件企业证书", "level": "二级",
                   "cert_no": "HX-2025-001", "valid_until": "2028-12-31"}],
        "past_projects": [{"name": "某智慧园区一期", "owner": "某管委会",
                           "amount": "500万元", "date": "2024", "role": "总集成"}],
    }
    s, d = http("PUT", "/api/profile", payload, token=tok, timeout=15)
    assert s == 200, f"PUT 失败 {s} {str(d)[:200]}"
    assert d["profile"]["company_name"] == company
    assert d["completeness"]["certs_count"] == 1
    assert d["completeness"]["projects_count"] == 1
    s, d = http("GET", "/api/profile", token=tok, timeout=15)
    assert d["profile"]["legal_person"] == "李四"
    assert d["profile"]["certs"][0]["cert_no"] == "HX-2025-001"
    return {"note": f"company={company}, 完整度={d['completeness']['filled_fields']}/12, 匿名={s0}"}


@case("V14占位符回填", "BID-04", "单章生成按企业资料自动回填占位符(fill_info)")
def t():
    _u, tok, _ = t_auth_common("filler", "accept123", role="bidder")
    company = f"华信回填测试有限公司{int(time.time()) % 100000}"
    payload = {"company_name": company, "legal_person": "王五",
               "contact_phone": "13700002222",
               "certs": [{"name": "软件企业证书", "level": "二级",
                          "cert_no": "FILL-001", "valid_until": "2028-06-30"}]}
    s, _ = http("PUT", "/api/profile", payload, token=tok, timeout=15)
    assert s == 200, f"档案保存失败 {s}"
    s, d = http("POST", "/api/bid/section",
                {"db_id": DB_ID, "section": "technical"}, token=tok, timeout=300)
    assert s == 200, f"生成失败 {s} {str(d)[:200]}"
    md = d.get("markdown") or ""
    assert company in md, "正文未使用企业资料中的公司全称"
    assert "[公司全称]" not in md, "仍残留 [公司全称] 占位符"
    filled = d.get("fill_info", {}).get("filled", [])
    # LLM 经占位符回填, 或被 prompt 直接引导写出真实名称, 两种均算回填生效
    assert "公司全称" in filled or company in md, f"企业资料未生效: {filled}"
    assert d.get("profile_used") is True
    return {"note": f"{len(md)}字, 占位符回填{len(filled)}项: {','.join(filled[:5]) or 'LLM直接引用资料'}"}


@case("V14响应对照表", "BID-05", "空投标稿对照表 verdict=fail/red>0/含🔴; 无原文400")
def t():
    s, d = http("POST", "/api/bid/matrix",
                {"db_id": DB_ID, "markdown": ""}, timeout=300)
    assert s == 200, f"matrix 失败 {s} {str(d)[:200]}"
    assert d.get("verdict") == "fail", f"空稿应 fail, 实际 {d.get('verdict')}"
    assert d["summary"]["red"] > 0, "空稿 red 应 >0"
    assert "🔴" in d.get("markdown", ""), "附录 markdown 应含 🔴"
    rows = d.get("matrix") or []
    assert len(rows) == d["summary"]["total"], "rows 与 summary.total 不一致"
    # 无 db_id(手填空白 tender, 无原文无资质要求) → 400
    s2, _ = http("POST", "/api/bid/matrix", {"markdown": "# 无招标信息"}, timeout=30)
    assert s2 == 400, f"缺原文应400, 实际 {s2}"
    return {"note": f"要求{d['summary']['total']}条, 红{d['summary']['red']}, 非法={s2}"}


@case("V14整本合稿", "BID-06", "/api/bid/full/stream SSE: 封面目录+fill_info+对照表")
def t():
    _u, tok, _ = t_auth_common("fullbid", "accept123", role="bidder")
    company = f"华信整本测试有限公司{int(time.time()) % 100000}"
    http("PUT", "/api/profile", {"company_name": company, "legal_person": "赵六"},
         token=tok, timeout=15)
    body = json.dumps({"db_id": DB_ID, "sections": ["technical", "qualification"]}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/api/bid/full/stream", data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {tok}"})
    counts = {"meta": 0, "section_start": 0, "section_done": 0,
              "matrix_done": 0, "done": 0, "error": 0}
    done = None
    with urllib.request.urlopen(req, timeout=600) as r:
        for raw in r:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data: "):
                continue
            ev = json.loads(line[6:])
            tp = ev.get("type")
            if tp in counts:
                counts[tp] += 1
            if tp == "done":
                done = ev
            if tp == "error":
                raise AssertionError(f"SSE error: {ev.get('content')}")
    assert counts == {"meta": 1, "section_start": 2, "section_done": 2,
                      "matrix_done": 1, "done": 1, "error": 0}, f"事件序列异常: {counts}"
    md = done.get("markdown") or ""
    assert "投 标 文 件" in md, "缺封面"
    assert "目 录" in md, "缺目录"
    assert company in md, "整本未回填公司名"
    assert done.get("fill_info") is not None
    total = (done.get("matrix_summary") or {}).get("total", 0)
    assert total > 0, f"对照表要求数应>0: {done.get('matrix_summary')}"
    return {"note": f"事件={counts}, 整本{len(md)}字, 对照{total}条, verdict={done.get('verdict')}"}


# ================= V1.5 证书附件上传 + OCR 结构化 =================

def _make_cert_png() -> tuple[bytes, str]:
    """生成一张中文资质证书 PNG (pymupdf 排版 + Windows 中文字体), 返回 (png字节, 字体路径)。"""
    import pymupdf
    font_file = ""
    for fp in ("C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/msyh.ttc",
               "C:/Windows/Fonts/simsun.ttc"):
        if Path(fp).exists():
            font_file = fp
            break
    assert font_file, "未找到中文字体, 无法生成 OCR 验收夹具"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    for text, size, y in (
        ("建筑业企业资质证书", 34, 170),
        ("企业名称：华信OCR验收有限公司", 22, 300),
        ("资质等级：一级", 22, 380),
        ("证书编号：BZ-2025-777888", 22, 460),
        ("有效期至：2029年12月31日", 22, 540),
    ):
        page.insert_text((90, y), text, fontname="certfont",
                         fontfile=font_file, fontsize=size)
    png = page.get_pixmap(dpi=200).tobytes("png")
    doc.close()
    return png, font_file


def _post_cert_ocr(content: bytes, token: str | None, filename: str = "qual_cert.png",
                   content_type: str = "image/png", timeout: int = 300):
    boundary = "----certOcrBoundary7MA4YWxk"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"{filename}\"\r\nContent-Type: {content_type}\r\n\r\n"
    ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        f"{BASE}/api/profile/cert/ocr", data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw.decode("utf-8", "ignore")[:300]}


def _get_cert_file(auth_token: str, file_token: str):
    req = urllib.request.Request(
        f"{BASE}/api/profile/cert/file?token={urllib.parse.quote(file_token)}",
        headers={"Authorization": f"Bearer {auth_token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()


@case("V15证书OCR", "CERT-01", "证书图片上传→OCR结构化→私有预览鉴权→保存→孤儿清理")
def t():
    _u, tok, _ = t_auth_common("certocr", "accept123", role="bidder")
    _u2, tok2, _ = t_auth_common("certocr2", "accept123", role="bidder")
    png, font_file = _make_cert_png()
    assert len(png) > 50_000, f"证书 PNG 异常过小: {len(png)}"

    # 1) 匿名上传 → 401
    s0, _ = _post_cert_ocr(png, None, timeout=30)
    assert s0 in (401, 403), f"匿名应401/403, 实际 {s0}"

    # 2) 登录上传 → OCR + 结构化
    s, d = _post_cert_ocr(png, tok)
    assert s == 200, f"OCR 上传失败 {s} {str(d)[:300]}"
    ocr_source = d.get("source")
    cert = d.get("cert") or {}
    ocr_text = cert.get("ocr_text") or ""
    assert len(ocr_text) > 20, f"OCR 文本为空/过短: {ocr_text!r}"
    norm_no = (cert.get("cert_no") or "").replace(" ", "").upper()
    assert "777888" in norm_no, f"证书编号未识别: {cert.get('cert_no')!r} OCR={ocr_text[:120]!r}"
    assert "2029" in (cert.get("valid_until") or ""), f"有效期未识别: {cert.get('valid_until')!r}"
    assert (cert.get("name") or "").strip(), "证书名称为空"
    ftoken = cert.get("file_token") or ""
    assert ftoken.endswith(".png"), f"file_token 异常: {ftoken}"

    # 3) 原件预览: 本人 200 image/png; 跨用户/非法 token 404
    s1, ctype, blob = _get_cert_file(tok, ftoken)
    assert s1 == 200 and ctype.startswith("image/") and blob == png, \
        f"本人预览异常 {s1} {ctype} {len(blob)}!={len(png)}"
    s2, _ct, _b = _get_cert_file(tok2, ftoken)
    assert s2 == 404, f"跨用户访问应404, 实际 {s2}"
    s3, _ct, _b = _get_cert_file(tok, "../../../etc/passwd")
    assert s3 == 404, f"路径穿越应404, 实际 {s3}"

    # 4) 非法格式 → 400
    sx, _ = _post_cert_ocr(b"MZbad", tok, filename="evil.exe",
                           content_type="application/octet-stream", timeout=30)
    assert sx == 400, f"exe 应400, 实际 {sx}"

    # 5) 随整表保存 → GET 回显附件信息
    company = f"华信OCR验收有限公司{int(time.time()) % 100000}"
    s, d = http("PUT", "/api/profile",
                {"company_name": company, "certs": [cert]}, token=tok, timeout=15)
    assert s == 200, f"档案保存失败 {s} {str(d)[:200]}"
    s, d = http("GET", "/api/profile", token=tok, timeout=15)
    certs = d["profile"].get("certs") or []
    assert any(c.get("file_token") == ftoken and c.get("ocr_text") for c in certs), \
        f"回显证书缺附件信息: {certs}"

    # 6) 去掉证书再保存 → 孤儿原件被清理 → 404
    s, _ = http("PUT", "/api/profile", {"company_name": company}, token=tok, timeout=15)
    assert s == 200
    s4, _ct, _b = _get_cert_file(tok, ftoken)
    assert s4 == 404, f"孤儿文件应被清理(404), 实际 {s4}"

    return {"note": f"字体={Path(font_file).name}, source={ocr_source}, "
                    f"编号={cert.get('cert_no')}, 有效期={cert.get('valid_until')}, "
                    f"匿名={s0}/越权={s2}/穿越={s3}/非法格式={sx}/孤儿={s4}"}


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
