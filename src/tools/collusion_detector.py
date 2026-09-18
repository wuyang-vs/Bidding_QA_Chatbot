"""围标串标线索检测 — 雷同度 / 文件元数据 / 报价规律.

重要原则:
  本工具只输出**线索**与原文证据, 不输出 "围标/串标成立" 的定性结论;
  所有结果须由评标委员会/监管人员人工复核.

检测维度:
  1. 文本雷同: 字符二元组 Jaccard + 相同整句摘录
  2. 文件属性: docx/pdf 元数据 (作者/最后保存者/生成程序/公司),
     原件由 API 层提取后通过 metadata 传入
  3. 机器特征: 正文内出现的相同 IPv4/MAC 地址
  4. 报价规律: 报价接近度、相同分项报价、三家及以上等差/等比

输入限制 (随结果 limitations 返回):
  - IP/MAC 不是普通 docx/pdf 标准元数据; 仅能检测正文暴露的地址,
    或电子标书平台导出的特殊元数据 (本工具暂不支持专有格式)
  - 仅提供文本 (无原件) 时文件属性维度无法检测
"""
from __future__ import annotations

import logging
import re
from itertools import combinations
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Jaccard 阈值
_HIGH_JACCARD = 0.85
_MED_JACCARD = 0.65
_LOW_JACCARD = 0.45
# 报价接近度阈值 (相对偏差)
_HIGH_PRICE_DIFF = 0.01
_MED_PRICE_DIFF = 0.02
# 相同整句最短长度
_SHARED_SENT_MIN = 12
_SHARED_SENT_MAX = 3

_DISCLAIMER = "本结果仅为系统发现的疑似线索，不构成围标串标的定性结论，请结合原件与其他证据人工复核。"

_PUNCT_RE = re.compile(r"[\s，。；、,.;:：!！?？（）()\[\]【】\"'“”‘’\-—_*#《》<>/\\|]+")
_SENT_SPLIT_RE = re.compile(r"[。；;\n！？!?]+")
_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_MAC_RE = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
_PRICE_RE = re.compile(
    r"(?:投标总报价|投标报价|总报价|报价)[^0-9¥￥]{0,12}?"
    r"(?:人民币\s*)?[¥￥]?\s*([0-9][0-9,]{3,}(?:\.\d+)?|[0-9]+(?:\.\d+)?)\s*"
    r"(万元|万|元)")


# ---------- 文本雷同 ----------

def normalize_text(text: str) -> str:
    return _PUNCT_RE.sub("", (text or ""))


def char_bigrams(text: str) -> set[str]:
    s = normalize_text(text)
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else set()


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def shared_sentences(text_a: str, text_b: str, limit: int = _SHARED_SENT_MAX) -> list[str]:
    def _sents(t: str) -> set[str]:
        out = set()
        for raw in _SENT_SPLIT_RE.split(t or ""):
            s = normalize_text(raw)
            if len(s) >= _SHARED_SENT_MIN:
                out.add(s)
        return out
    shared = sorted(_sents(text_a) & _sents(text_b), key=len, reverse=True)
    return shared[:limit]


def _level_by_jaccard(score: float) -> str | None:
    if score >= _HIGH_JACCARD:
        return "high"
    if score >= _MED_JACCARD:
        return "medium"
    if score >= _LOW_JACCARD:
        return "low"
    return None


# ---------- 报价 ----------

def extract_price(text: str) -> float | None:
    """从正文正则抽取投标总报价 (元). 取第一个匹配."""
    for m in _PRICE_RE.finditer(text or ""):
        try:
            v = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        if m.group(2) in ("万元", "万"):
            v *= 10000
        return round(v, 2)
    return None


def _price_diff_pct(a: float, b: float) -> float:
    base = max(a, b)
    return abs(a - b) / base if base else 0.0


# ---------- 文件元数据 ----------

def extract_file_metadata(path: str | Path) -> dict[str, Any]:
    """读取 docx/pdf 原件元数据. txt/md 或失败返回空 dict."""
    p = Path(path)
    ext = p.suffix.lower()
    meta: dict[str, Any] = {"file_name": p.name, "file_type": ext.lstrip(".")}
    try:
        if ext == ".docx":
            from docx import Document
            doc = Document(str(p))
            cp = doc.core_properties
            meta.update({
                "author": cp.author or "",
                "last_modified_by": cp.last_modified_by or "",
                "created": cp.created.isoformat() if cp.created else "",
                "modified": cp.modified.isoformat() if cp.modified else "",
                "revision": cp.revision or "",
                "application": "Microsoft Word",
            })
            try:
                import zipfile
                from xml.etree import ElementTree as ET
                with zipfile.ZipFile(str(p)) as z:
                    if "docProps/app.xml" in z.namelist():
                        root = ET.fromstring(z.read("docProps/app.xml"))
                        company = ""
                        app = ""
                        for el in root.iter():
                            tag = el.tag.split("}")[-1]
                            if tag == "Company":
                                company = (el.text or "").strip()
                            elif tag == "Application":
                                app = (el.text or "").strip()
                        if company:
                            meta["company"] = company
                        if app:
                            meta["application"] = app
            except Exception as e:
                logger.debug("docx app.xml 读取失败: %s", e)
        elif ext == ".pdf":
            import pymupdf
            doc = pymupdf.open(str(p))
            try:
                m = doc.metadata or {}
                meta.update({
                    "author": m.get("author") or "",
                    "creator": m.get("creator") or "",
                    "producer": m.get("producer") or "",
                    "application": m.get("creator") or m.get("producer") or "",
                    "created": m.get("creationDate") or "",
                    "modified": m.get("modDate") or "",
                })
            finally:
                doc.close()
    except Exception as e:
        logger.warning("元数据读取失败 %s: %s", p.name, e)
        meta["read_error"] = str(e)[:200]
    return {k: v for k, v in meta.items() if v not in ("", None)}


# ---------- 主检测 ----------

_META_COMPARE = {
    "author": "文档作者相同",
    "last_modified_by": "最后保存者相同",
    "company": "文档公司属性相同",
    "creator": "PDF 创建程序相同",
    "producer": "PDF 生成器相同",
}


def detect_collusion(bids: list[dict[str, Any]]) -> dict[str, Any]:
    """围串标线索检测.

    Args:
        bids: [{"bidder_name", "text", "price"(可选),
                "price_items"(可选 [{"name","amount"}]),
                "metadata"(可选, extract_file_metadata 的输出)}]

    Returns:
        {summary, pairs, clues, limitations, disclaimer, verdict}
    """
    clues: list[dict[str, Any]] = []
    pairs_out: list[dict[str, Any]] = []
    limitations: list[str] = []
    clue_id = 0

    def add(pair: tuple[str, str], dimension: str, level: str, rule: str,
            reason: str, ev_a: Any = None, ev_b: Any = None):
        nonlocal clue_id
        clue_id += 1
        clues.append({
            "id": f"C{clue_id:02d}", "pair": list(pair), "dimension": dimension,
            "level": level, "rule": rule, "reason": reason,
            "evidence": {"a": ev_a, "b": ev_b},
        })

    if len(bids) < 2:
        return {
            "summary": {"high": 0, "medium": 0, "low": 0, "pairs": 0},
            "pairs": [], "clues": [],
            "limitations": ["围串标检测至少需要 2 份投标文件"],
            "disclaimer": _DISCLAIMER, "verdict": "insufficient",
        }

    has_original_file = any(b.get("metadata") for b in bids)
    if not has_original_file:
        limitations.append("未提供 Word/PDF 原件，文件属性（作者/生成程序/公司）维度无法检测；IP/MAC 不是普通文档标准元数据，仅能识别正文暴露的地址。")
    limitations.append("IP/MAC 地址仅从投标正文文本中识别；电子标书平台专有元数据暂不支持。")

    prepared = []
    for b in bids:
        text = b.get("text") or ""
        price = b.get("price")
        price = float(price) if price not in (None, "") else extract_price(text)
        prepared.append({
            "name": (b.get("bidder_name") or "未命名投标人").strip(),
            "text": text, "bigrams": char_bigrams(text),
            "price": price,
            "price_items": b.get("price_items") or [],
            "metadata": b.get("metadata") or {},
            "ips": set(_IP_RE.findall(text)),
            "macs": set(x.upper() for x in _MAC_RE.findall(text)),
        })

    for x, y in combinations(prepared, 2):
        pair = (x["name"], y["name"])

        # 维度 1: 文本雷同
        score = round(jaccard(x["bigrams"], y["bigrams"]), 4)
        shared = shared_sentences(x["text"], y["text"])
        lvl = _level_by_jaccard(score)
        pairs_out.append({
            "pair": list(pair), "jaccard": score,
            "level": lvl or "below_threshold",
            "shared_sentences": shared,
            "price_diff_pct": (round(_price_diff_pct(x["price"], y["price"]), 4)
                               if x["price"] and y["price"] else None),
        })
        if lvl:
            add(pair, "文本雷同", lvl, "jaccard_bigram",
                f"正文字符二元组 Jaccard 相似度 {score:.2f}（阈值 高≥{_HIGH_JACCARD}/中≥{_MED_JACCARD}），"
                + f"存在 {len(shared)} 处相同整句",
                ev_a=shared[0] if shared else None,
                ev_b=shared[1] if len(shared) > 1 else None)

        # 维度 2: 文件元数据
        for key, desc in _META_COMPARE.items():
            va = str(x["metadata"].get(key) or "").strip()
            vb = str(y["metadata"].get(key) or "").strip()
            if va and va == vb:
                level = "high" if key in ("author", "last_modified_by", "company") else "medium"
                add(pair, "文件属性", level, f"metadata_{key}",
                    f"{desc}：'{va}'", ev_a=va, ev_b=vb)

        # 维度 3: 正文暴露的相同 IP/MAC
        common_ips = x["ips"] & y["ips"]
        # 过滤常见示例地址
        common_ips = {ip for ip in common_ips
                      if not ip.startswith(("0.0.0.0", "127.0.0.", "255.255."))}
        if common_ips:
            add(pair, "机器特征", "high", "same_ip_in_text",
                f"两份投标正文出现相同 IPv4 地址：{sorted(common_ips)[:3]}",
                ev_a=sorted(common_ips)[0], ev_b=sorted(common_ips)[0])
        common_macs = x["macs"] & y["macs"]
        if common_macs:
            add(pair, "机器特征", "high", "same_mac_in_text",
                f"两份投标正文出现相同 MAC 地址：{sorted(common_macs)[:3]}",
                ev_a=sorted(common_macs)[0], ev_b=sorted(common_macs)[0])

        # 维度 4a: 报价接近度
        if x["price"] and y["price"]:
            diff = _price_diff_pct(x["price"], y["price"])
            if diff <= _HIGH_PRICE_DIFF:
                add(pair, "报价规律", "high", "price_too_close",
                    f"报价仅相差 {diff * 100:.2f}%（{x['price']:.2f} vs {y['price']:.2f}，阈值≤{_HIGH_PRICE_DIFF*100:.0f}%）",
                    ev_a=x["price"], ev_b=y["price"])
            elif diff <= _MED_PRICE_DIFF:
                add(pair, "报价规律", "medium", "price_close",
                    f"报价相差 {diff * 100:.2f}%（{x['price']:.2f} vs {y['price']:.2f}）",
                    ev_a=x["price"], ev_b=y["price"])

        # 维度 4b: 相同分项报价
        ax = {str(i.get("name", "")).strip(): str(i.get("amount", "")).strip()
              for i in (x["price_items"] or []) if i.get("name")}
        ay = {str(i.get("name", "")).strip(): str(i.get("amount", "")).strip()
              for i in (y["price_items"] or []) if i.get("name")}
        same_items = [(k, ax[k]) for k in ax.keys() & ay.keys() if ax[k] and ax[k] == ay[k]]
        if same_items:
            level = "high" if len(same_items) >= 3 else "medium"
            add(pair, "报价规律", level, "identical_line_items",
                f"{len(same_items)} 个分项报价完全相同：{[n for n, _ in same_items[:5]]}",
                ev_a=same_items[0], ev_b=same_items[0])

    # 维度 4c: 三家及以上报价等差
    priced = [p for p in prepared if p["price"]]
    if len(priced) >= 3:
        vals = sorted((p["price"], p["name"]) for p in priced)
        diffs = [round(vals[i + 1][0] - vals[i][0], 2) for i in range(len(vals) - 1)]
        if diffs and all(abs(d - diffs[0]) <= max(1.0, abs(diffs[0]) * 0.05)
                         for d in diffs) and diffs[0] != 0:
            add((vals[0][1], vals[-1][1]), "报价规律", "medium", "arithmetic_sequence",
                f"{len(vals)} 家报价近似等差数列，相邻价差约 {diffs[0]:.2f}："
                + ", ".join(f"{n}={v:.0f}" for v, n in vals))

    high = sum(1 for c in clues if c["level"] == "high")
    medium = sum(1 for c in clues if c["level"] == "medium")
    low = sum(1 for c in clues if c["level"] == "low")
    verdict = "clues_found" if clues else "clean"

    return {
        "summary": {"high": high, "medium": medium, "low": low,
                    "total_clues": len(clues), "pairs": len(pairs_out)},
        "pairs": pairs_out,
        "clues": clues,
        "limitations": limitations,
        "disclaimer": _DISCLAIMER,
        "verdict": verdict,
    }
