"""中国政府采购网爬虫: 列表页 → 详情页 → 结构化 Excel + Q&A Excel

数据源: http://www.ccgp.gov.cn/cggg/
  - 公开招标公告 / 邀请招标公告 / 中标结果公告 / 单一来源公示

输出:
  data/raw/ccgp_structured.xlsx   — 结构化数据 (项目名称/采购单位/金额/开标时间...)
  data/raw/ccgp_qa.xlsx           — Q&A 对 (供 Qdrant RAG 导入)
"""
import logging
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("ccgp_spider")

BASE = "http://www.ccgp.gov.cn"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "raw"
DATA_DIR.mkdir(parents=True, exist_ok=True)


# ========== 列表页 URL 模板 ==========
LIST_URLS = [
    # 公开招标公告 (中央+地方)
    f"{BASE}/cggg/zygg/gkzb/",
    f"{BASE}/cggg/dfgg/gkzb/",
    # 中标结果公告
    f"{BASE}/cggg/zygg/zbgg/",
    f"{BASE}/cggg/dfgg/zbgg/",
    # 单一来源公示 (中央)
    f"{BASE}/cggg/zygg/dsly/",
    f"{BASE}/cggg/dfgg/dsly/",
    # 更正公告
    f"{BASE}/cggg/zygg/gzgg/",
    f"{BASE}/cggg/dfgg/gzgg/",
]


def fetch(url: str, timeout: int = 15) -> str | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.encoding = r.apparent_encoding or "utf-8"
        if r.status_code == 200:
            return r.text
        logger.warning("HTTP %d for %s", r.status_code, url)
        return None
    except Exception as e:
        logger.warning("fetch failed %s: %s", url, e)
        return None


def parse_list_page(html: str, list_url: str = "") -> list[dict]:
    """从列表页提取 {title, url, date, region, buyer}."""
    soup = BeautifulSoup(html, "html.parser")
    items = []

    # ccgp 列表项: 先找所有 li 和 a, 再过滤
    for a in soup.find_all("a"):
        title = a.get("title") or a.get_text(strip=True)
        href = a.get("href", "")
        if not title or not href:
            continue
        # 只收集招标公告链接
        if not href.endswith(".htm") or "2026" not in href and "2025" not in href:
            continue
        if not href.startswith("http"):
            href = urljoin(list_url or BASE, href)
        # 找到父 li 的兄弟 span (日期/地域/采购人)
        parent = a.parent
        spans = []
        if parent:
            # 向上找 2 层的 li, 收集所有 span
            for _ in range(3):
                if parent.name == "li":
                    spans = [s.get_text(strip=True) for s in parent.find_all("span")]
                    break
                parent = parent.parent
                if parent is None:
                    break
        date = spans[0] if len(spans) > 0 else ""
        region = ""
        buyer = ""
        for s in spans[1:]:
            if "地域" in s or s.startswith("*"):
                region = s.replace("*", "").replace("地域：", "").strip()
            elif "采购人" in s:
                buyer = s.replace("*", "").replace("采购人：", "").strip()
        items.append({"title": title, "url": href, "date": date,
                      "region": region, "buyer": buyer})
    # 去重 (同 URL)
    seen = set()
    unique = []
    for it in items:
        if it["url"] not in seen:
            seen.add(it["url"])
            unique.append(it)
    return unique


def parse_detail_page(html: str) -> dict:
    """从详情页提取结构化字段."""
    soup = BeautifulSoup(html, "html.parser")
    result = {
        "project_name": "", "buyer": "", "buyer_addr": "", "buyer_phone": "",
        "agent": "", "agent_addr": "", "agent_phone": "",
        "budget": "", "bid_time": "", "bid_place": "",
        "admin_region": "", "announce_date": "", "doc_price": "",
        "project_code": "", "purchase_method": "",
        "content": "",
    }

    # 匹配规则: (key关键词, 目标字段, 是否覆盖已有值)
    # 长关键词必须在前 (避免 "采购单位联系方式" 先被 "采购单位" 匹配)
    rules = [
        ("采购项目名称", "project_name", True),
        ("采购单位地址", "buyer_addr", True),
        ("采购单位联系方式", "buyer_phone", True),
        ("采购单位", "buyer", True),
        ("代理机构地址", "agent_addr", True),
        ("代理机构联系方式", "agent_phone", True),
        ("代理机构名称", "agent", True),
        ("预算金额", "budget", True),
        ("最高限价", "budget", False),  # 已有预算时不覆盖
        ("开标时间", "bid_time", True),
        ("投标截止", "bid_time", False),
        ("开标地点", "bid_place", True),
        ("投标地点", "bid_place", False),
        ("行政区域", "admin_region", True),
        ("公告时间", "announce_date", True),
        ("发布时间", "announce_date", False),
        ("招标文件售价", "doc_price", True),
        ("项目编号", "project_code", True),
        ("采购方式", "purchase_method", True),
        ("招标方式", "purchase_method", False),
    ]

    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            key = tds[0].get_text(strip=True).replace("：", "").replace(":", "")
            val = tds[1].get_text(strip=True)
            # 按 rules 顺序匹配 (长 key 先)
            matched = False
            for kw, field, overwrite in rules:
                if kw in key:
                    if overwrite or not result[field]:
                        result[field] = val
                    matched = True
                    break
            if matched:
                continue

    # 正文取第一段
    body = soup.find("div", class_="vF_detail_content") or soup.find("div", class_="content")
    if body:
        text = body.get_text("\n", strip=True)
        result["content"] = text[:500]

    return result


# ========== Q&A 对生成 ==========

def build_qa_pairs(item: dict) -> list[dict]:
    """从结构化数据生成 Q&A 对 (供 RAG 导入)."""
    pairs = []
    name = item.get("project_name", "")

    def _add(q, a):
        if name and a and len(a) > 2:
            pairs.append({"question": q, "answer": a, "source_file": "ccgp.gov.cn",
                          "section_title": name[:60], "doc_type": "招标公告"})

    if name:
        _add(f"{name}的预算金额是多少？", item.get("budget", ""))
        _add(f"{name}的采购单位是谁？", item.get("buyer", ""))
        _add(f"{name}的开标时间？", item.get("bid_time", ""))
        _add(f"{name}的开标地点？", item.get("bid_place", ""))
        _add(f"{name}的代理机构？", item.get("agent", ""))
        _add(f"{name}的项目编号？", item.get("project_code", ""))
        _add(f"{name}的采购方式？", item.get("purchase_method", ""))

    return pairs


# ========== 主流程 ==========

def crawl(max_pages_per_list: int = 2, max_detail: int = 30, delay: float = 0.8):
    """
    Args:
        max_pages_per_list: 每个列表类别翻几页
        max_detail: 总共最多抓多少条详情 (避免跑一整天)
        delay: 每条详情之间的秒数
    """
    logger.info("=== 开始爬虫 (ccgp.gov.cn) ===")
    logger.info("最多抓 %d 条详情, 每个列表翻 %d 页", max_detail, max_pages_per_list)

    all_items = []  # 列表页摘要
    all_details = []  # 详情结构化
    all_qa = []  # Q&A 对

    for list_url in LIST_URLS:
        for page in range(max_pages_per_list):
            url = list_url if page == 0 else list_url.rstrip("/") + f"/index_{page}.htm"
            logger.info("列表页: %s", url)
            html = fetch(url)
            if not html:
                break
            items = parse_list_page(html, url)
            logger.info("  提取 %d 条链接", len(items))
            all_items.extend(items)
            time.sleep(0.5)

    # 去重
    seen_urls = set()
    unique_items = []
    for it in all_items:
        if it["url"] not in seen_urls:
            seen_urls.add(it["url"])
            unique_items.append(it)
    logger.info("共 %d 条唯一链接, 开始抓详情", len(unique_items))

    for i, item in enumerate(unique_items[:max_detail]):
        logger.info("[%d/%d] %s", i + 1, min(len(unique_items), max_detail), item["title"][:40])
        html = fetch(item["url"])
        if not html:
            continue
        detail = parse_detail_page(html)
        # 合并列表页信息
        detail["title"] = item["title"]
        detail["list_date"] = item["date"]
        detail["list_region"] = item["region"]
        detail["list_buyer"] = item["buyer"]
        detail["url"] = item["url"]
        all_details.append(detail)

        # 生成 Q&A
        qa = build_qa_pairs(detail)
        all_qa.extend(qa)

        time.sleep(delay)

    # 保存 Excel
    structured_path = DATA_DIR / "ccgp_structured.xlsx"
    qa_path = DATA_DIR / "ccgp_qa.xlsx"

    pd.DataFrame(all_details).to_excel(structured_path, index=False)
    pd.DataFrame(all_qa).to_excel(qa_path, index=False)

    logger.info("\n=== 完成 ===")
    logger.info("结构化: %d 条 → %s", len(all_details), structured_path)
    logger.info("Q&A: %d 条 → %s", len(all_qa), qa_path)
    return structured_path, qa_path


if __name__ == "__main__":
    crawl(max_pages_per_list=1, max_detail=15, delay=0.5)
