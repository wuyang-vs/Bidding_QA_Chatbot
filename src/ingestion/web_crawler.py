# -*- coding: utf-8 -*-
"""政府官网权威信息源爬取: 列表发现 → 详情抽取 → 限速/去重/robots 约束.

设计原则:
  - 纯解析函数(extract_links/parse_detail/normalize_date)不发网络请求, 用 fixture 离线可测;
  - 源全部由 config/web_sources.json 声明式配置, 新增省级平台无需改代码;
  - 礼貌爬取: UA 标识、单源串行、请求间隔、超时重试、robots.txt、单源条数上限;
  - 只解析不执行: requests + bs4, 无浏览器、无 JS 依赖。
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = ROOT / "config" / "web_sources.json"

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# 需要从正文 DOM 中剔除的噪声元素
_NOISE_TAGS = ("script", "style", "noscript", "iframe", "nav", "header",
               "footer", "form", "button")
# 正文文本中要丢弃的噪声行
_NOISE_LINES = re.compile(
    r"^(选择字体|分享|打印|关闭窗口|扫一扫|主办单位|承办单位|备案号|ICP备|"
    r"版权所有|当前位置|首页\s*[>>＞]|上一篇|下一篇|相关链接|微信扫一扫)")

_DATE_RES = [
    re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"),
    re.compile(r"(20\d{2})[-/\.](\d{1,2})[-/\.](\d{1,2})"),
]
_DATE_HINT = re.compile(r"(?:发布时间|发布日期|成文日期|发文日期|发布于|时间)\s*[:：]?\s*"
                        r"(20\d{2}\s*[年\-/\.]\s*\d{1,2}\s*[月\-/\.]\s*\d{1,2})")


@dataclass
class WebArticle:
    """一篇官网政策/法规文章的结构化抽取结果."""
    source: str
    source_label: str
    url: str
    title: str
    content: str
    business_line: str = "regulation"
    publish_date: str = ""          # 规范化为 YYYY-MM-DD, 取不到为空
    fetched_at: int = 0

    def content_sha(self) -> str:
        import hashlib
        return hashlib.sha256((self.title + self.content).encode("utf-8")).hexdigest()[:16]


@dataclass
class SourceStats:
    source: str
    label: str
    discovered: int = 0     # 列表页发现链接数
    new: int = 0            # 新入库
    updated: int = 0        # 内容变更重入
    skipped: int = 0        # 已存在且无变化
    failed: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------- 注册表 ----------------

def load_sources(path: str | Path | None = None,
                 only: list[str] | None = None,
                 include_disabled: bool = False) -> list[dict]:
    """加载源注册表. only 给名字白名单; include_disabled 才会带 enabled=false 的源."""
    p = Path(path) if path else DEFAULT_REGISTRY
    data = json.loads(p.read_text(encoding="utf-8"))
    out = []
    for src in data.get("sources", []):
        if not include_disabled and not src.get("enabled", False):
            continue
        if only and src["name"] not in only:
            continue
        out.append(src)
    return out


# ---------------- 纯解析函数 ----------------

def _domain_allowed(url: str, allowed: list[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in allowed)


def normalize_date(text: str) -> str:
    """从含日期线索的文本中抽取并规范化为 YYYY-MM-DD; 取不到返回 ''."""
    hint = _DATE_HINT.search(text or "")
    scan = hint.group(1) if hint else (text or "")
    for rx in _DATE_RES:
        m = rx.search(scan)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 1 <= mo <= 12 and 1 <= d <= 31:
                return f"{y:04d}-{mo:02d}-{d:02d}"
    # hint 未命中时在全文找一次
    for rx in _DATE_RES:
        m = rx.search(text or "")
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 1 <= mo <= 12 and 1 <= d <= 31:
                return f"{y:04d}-{mo:02d}-{d:02d}"
    return ""


def extract_links(html: str, base_url: str, list_cfg: dict,
                  allowed_domains: list[str]) -> list[tuple[str, str]]:
    """从列表页 HTML 抽取 (标题, 绝对URL), 按出现顺序去重.

    过滤: 域名白名单 + link_pattern 正则 + 标题长度窗口.
    """
    soup = BeautifulSoup(html, "lxml")
    pattern = re.compile(list_cfg.get("link_pattern", ".+"))
    tmin = int(list_cfg.get("title_min", 4))
    tmax = int(list_cfg.get("title_max", 100))

    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if not href or href.startswith(("javascript:", "#", "mailto:")):
            continue
        url = urljoin(base_url, href)
        if not url.startswith(("http://", "https://")):
            continue
        if not _domain_allowed(url, allowed_domains):
            continue
        if not pattern.search(url):
            continue
        title = (a.get("title") or a.get_text(" ", strip=True)).strip()
        title = re.sub(r"\s+", " ", title)
        if not (tmin <= len(title) <= tmax):
            continue
        # 去掉标题尾部的日期尾巴
        title = re.sub(r"\s*20\d{2}[-./年]\d{1,2}[-./月]\d{1,2}日?\s*$", "", title)
        if url in seen:
            continue
        seen.add(url)
        out.append((title, url))
    return out


def _clean_text(node) -> str:
    for tag in node.find_all(_NOISE_TAGS):
        tag.decompose()
    # 段落/换行: 块级元素后补换行, 避免条款粘连
    for block in node.find_all(["p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4"]):
        block.append("\n")
    text = node.get_text()
    lines = []
    for ln in text.splitlines():
        ln = re.sub(r"[ \t\u3000]+", " ", ln).strip()
        if not ln or _NOISE_LINES.match(ln):
            continue
        lines.append(ln)
    # 合并相邻重复行
    deduped: list[str] = []
    for ln in lines:
        if not deduped or deduped[-1] != ln:
            deduped.append(ln)
    return "\n".join(deduped).strip()


_META_DATE_NAMES = {"pubdate", "publishdate", "article:published_time",
                    "weibo:article:create_at", "date"}


def extract_publish_date(soup, body_node=None) -> str:
    """按可信度取发布日期: meta PubDate > 正文头部带标签日期 > 标题邻近日期.

    不扫整页 HTML: 政府站模板常有静态"星期"日期块/相关链接日期, 直接扫会误中.
    """
    for m in soup.find_all("meta"):
        name = (m.get("name") or m.get("property") or "").strip().lower()
        if name in _META_DATE_NAMES:
            d = normalize_date(m.get("content") or "")
            if d:
                return d
    if body_node is not None:
        d = normalize_date(body_node.get_text(" ", strip=True)[:800])
        if d:
            return d
    h1 = soup.find("h1")
    if h1 is not None and h1.parent is not None:
        d = normalize_date(h1.parent.get_text(" ", strip=True)[:600])
        if d:
            return d
    return ""


def parse_detail(html: str, source: dict, url: str,
                 fallback_title: str = "") -> WebArticle | None:
    """解析详情页 → WebArticle; 正文过短视为无效返回 None.

    正文容器按配置的 class 关键词在全页候选中取文本最长者,
    全部未命中时退回 <article> 或全文最大 <div>.
    """
    soup = BeautifulSoup(html, "lxml")

    # 标题
    title = ""
    for sel in source.get("detail", {}).get("title_selectors", ["h1"]):
        node = soup.find(sel)
        if node and node.get_text(strip=True):
            title = node.get_text(" ", strip=True)
            break
    if not title:
        t = soup.find("title")
        title = t.get_text(strip=True) if t else fallback_title
    title = re.sub(r"[\s_|-]*(中华人民共和国住房和城乡建设部|财政部|中国政府采购网)\s*$",
                   "", title).strip() or fallback_title

    # 正文容器
    cfg_classes = source.get("detail", {}).get("content_classes", [])
    candidates = []
    for node in soup.find_all(attrs={"class": True}):
        cls = " ".join(node.get("class", []))
        if any(tok.lower() in cls.lower() for tok in cfg_classes):
            candidates.append(node)
    if soup.find("article"):
        candidates.append(soup.find("article"))
    body_node = None
    if candidates:
        body_node = max(candidates, key=lambda n: len(n.get_text(strip=True)))
    else:
        divs = [d for d in soup.find_all("div") if d.get_text(strip=True)]
        if divs:
            body_node = max(divs, key=lambda n: len(n.get_text(strip=True)))
    if body_node is None:
        return None
    content = _clean_text(body_node)
    min_len = int(source.get("detail", {}).get("min_content_chars", 200))
    if len(content) < min_len:
        return None

    return WebArticle(
        source=source["name"],
        source_label=source.get("label", source["name"]),
        url=url,
        title=title[:120],
        content=content,
        business_line=source.get("business_line", "regulation"),
        publish_date=extract_publish_date(soup, body_node),
        fetched_at=int(time.time()),
    )


# ---------------- 网络抓取 ----------------

class RobotsCache:
    """轻量 robots 缓存; robots 获取失败(404/超时)视为允许."""

    def __init__(self):
        self._cache: dict[str, RobotFileParser | None] = {}

    def allowed(self, url: str, user_agent: str = _UA) -> bool:
        parts = urlparse(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._cache:
            rp = RobotFileParser()
            rp.set_url(urljoin(origin, "/robots.txt"))
            try:
                r = requests.get(urljoin(origin, "/robots.txt"), timeout=8,
                                 headers={"User-Agent": user_agent},
                                 proxies={"http": None, "https": None}, verify=False)
                if r.status_code >= 400:
                    self._cache[origin] = None          # 无 robots, 允许
                    return True
                rp.parse(r.text.splitlines())
                self._cache[origin] = rp
            except requests.RequestException:
                self._cache[origin] = None
                return True
        rp = self._cache[origin]
        return True if rp is None else rp.can_fetch(user_agent, url)


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    # 绕过系统失效代理(内网直连), 不影响环境变量
    s.trust_env = False
    s.proxies = {"http": None, "https": None}
    return s


def fetch(session: requests.Session, url: str, source: dict,
          retries: int = 2) -> str:
    """带超时/重试/编码探测地抓取页面文本."""
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            r = session.get(url, timeout=source.get("timeout_sec", 15),
                            verify=source.get("verify_tls", False))
            enc = source.get("encoding") or r.apparent_encoding or r.encoding
            r.encoding = enc or "utf-8"
            if r.status_code == 200 and r.text:
                return r.text
            last_exc = RuntimeError(f"HTTP {r.status_code}")
        except requests.RequestException as e:
            last_exc = e
        if attempt < retries:
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"抓取失败 {url}: {last_exc}")


# ---------------- 单源爬取 ----------------

def crawl_source(source: dict, state: dict, *, max_per_source: int = 10,
                 dry_run: bool = False, ignore_robots: bool = False,
                 session: requests.Session | None = None,
                 robots: RobotsCache | None = None,
                 fetcher=fetch, sleep: bool = True) -> tuple[SourceStats, list[WebArticle]]:
    """爬取单个源. 返回 (统计, 新/变更文章列表).

    state: {url: {"content_sha": ..., ...}} 原地更新, 由调用方持久化.
    """
    stats = SourceStats(source=source["name"], label=source.get("label", source["name"]))
    articles: list[WebArticle] = []
    session = session or make_session()
    robots = robots or RobotsCache()
    delay = float(source.get("request_delay_sec", 1.5))

    list_html = fetcher(session, source["entry_url"], source)
    links = extract_links(list_html, source["entry_url"],
                          source.get("list", {}), source.get("allowed_domains", []))
    stats.discovered = len(links)
    logger.info("[%s] 列表发现 %d 个链接", source["name"], len(links))

    for title, url in links[:max_per_source]:
        if not ignore_robots and not robots.allowed(url):
            logger.info("[%s] robots 禁止, 跳过 %s", source["name"], url)
            continue
        if sleep:
            time.sleep(delay)
        try:
            html = fetcher(session, url, source)
            article = parse_detail(html, source, url, fallback_title=title)
            if article is None:
                stats.failed += 1
                stats.errors.append(f"正文抽取失败(过短): {url}")
                continue
            sha = article.content_sha()
            prev = state.get(url)
            if dry_run:
                stats.new += 0 if prev else 1
                articles.append(article)
                continue
            if prev and prev.get("content_sha") == sha:
                stats.skipped += 1
                continue
            if prev:
                stats.updated += 1
            else:
                stats.new += 1
            articles.append(article)
            state[url] = {
                "content_sha": sha,
                "title": article.title,
                "publish_date": article.publish_date,
                "source": source["name"],
                "last_seen": int(time.time()),
            }
        except Exception as e:
            stats.failed += 1
            stats.errors.append(f"{url} :: {type(e).__name__}: {e}")
            logger.warning("[%s] %s 抓取失败: %s", source["name"], url, e)
    return stats, articles


def run(sources: list[dict], state: dict, *, max_per_source: int = 10,
        dry_run: bool = False, ignore_robots: bool = False) -> tuple[list[SourceStats], list[WebArticle]]:
    """串行爬取多个源(共享一个 session), 汇总结果."""
    session = make_session()
    robots = RobotsCache()
    all_stats: list[SourceStats] = []
    all_articles: list[WebArticle] = []
    for src in sources:
        try:
            sub_state = state.setdefault(src["name"], {})
            stats, articles = crawl_source(
                src, sub_state,
                max_per_source=max_per_source, dry_run=dry_run,
                ignore_robots=ignore_robots, session=session, robots=robots)
        except Exception as e:
            stats = SourceStats(source=src["name"], label=src.get("label", src["name"]),
                                failed=1, errors=[f"列表页失败: {e}"])
            articles = []
            logger.error("[%s] 源级失败: %s", src["name"], e)
        all_stats.append(stats)
        all_articles.extend(articles)
    return all_stats, all_articles
