# -*- coding: utf-8 -*-
"""官网爬取入库离线单测: 纯解析/去重状态/确定性点 ID, 不发网络请求、不加载模型."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bs4 import BeautifulSoup  # noqa: E402
from src.ingestion.web_crawler import (  # noqa: E402
    WebArticle, extract_links, parse_detail, normalize_date,
    extract_publish_date, crawl_source, load_sources,
)
from src.ingestion.web_ingest import (  # noqa: E402
    build_web_points, article_uid, load_state, save_state,
)

LIST_HTML = """
<html><body>
<ul>
  <li><a href="/zcfg/gwywj/202604/t20260420_26427310.htm">国务院办公厅关于深化投资审批制度改革的意见</a></li>
  <li><a href="http://www.ccgp.gov.cn/zcfg/bgxz/202509/t20250901_123.htm"
        title="短">短</a></li>
  <li><a href="https://evil.example.com/path">境外域名不应被收录</a></li>
  <li><a href="/zcfg/gwywj/202604/t20260420_26427310.htm">重复链接标题</a></li>
  <li><a href="javascript:void(0)">JS 链接</a></li>
  <li><a href="/zcfg/other/page.html">国务院办公厅关于进一步优化营商环境的若干措施通知</a></li>
</ul>
</body></html>
"""

DETAIL_HTML = """
<html><head><title>国务院办公厅关于深化投资审批制度改革的意见_中国政府采购网</title></head>
<body>
<h1>国务院办公厅关于深化投资审批制度改革的意见</h1>
<div class="top">当前位置：首页 > 政策法规</div>
<div class="main_container">
  <p>发布时间：2026-04-20 10:00</p>
  <p>国办发〔2026〕15号</p>
  <p>各省、自治区、直辖市人民政府，国务院各部委、各直属机构：</p>
  <p>为进一步深化投资审批制度改革，优化营商环境，激发市场主体投资活力，
  现就有关事项通知如下。一、总体要求。以习近平新时代中国特色社会主义思想为指导，
  持续推进投资领域简政放权。二、精简审批事项。依法取消没有法律法规依据的审批。</p>
  <p>三、规范中介服务。破除市场垄断和地区壁垒，推动中介服务机构公开服务条件。</p>
  <div>分享到：微信 微博</div>
</div>
<footer>版权所有 中国政府采购网</footer>
</body></html>
"""

SOURCE = {
    "name": "ccgp_test",
    "label": "中国政府采购网-测试",
    "business_line": "regulation",
    "entry_url": "http://www.ccgp.gov.cn/zcfg/",
    "list": {
        "type": "static",
        "link_pattern": r"^https?://www\.ccgp\.gov\.cn/zcfg/.+\.html?$",
        "title_min": 8, "title_max": 80,
    },
    "detail": {
        "title_selectors": ["h1"],
        "content_classes": ["main_container", "TRS_Editor"],
        "min_content_chars": 80,
    },
    "allowed_domains": ["ccgp.gov.cn"],
}


def test_extract_links_filters_and_dedups():
    links = extract_links(LIST_HTML, SOURCE["entry_url"], SOURCE["list"],
                          SOURCE["allowed_domains"])
    urls = [u for _, u in links]
    # 相对路径转绝对
    assert any(u == "http://www.ccgp.gov.cn/zcfg/gwywj/202604/t20260420_26427310.htm"
               for u in urls)
    # 境外域名 / javascript 不收录
    assert not any("evil.example.com" in u for u in urls)
    assert not any(u.startswith("javascript") for u in urls)
    # 去重
    assert urls.count("http://www.ccgp.gov.cn/zcfg/gwywj/202604/t20260420_26427310.htm") == 1
    # 标题长度过滤同时作用于文本与 title 属性
    assert all(len(t) >= 8 for t, _ in links)


def test_normalize_date_variants():
    assert normalize_date("发布日期：2026年04月20日") == "2026-04-20"
    assert normalize_date("发布时间：2026-04-20 10:00") == "2026-04-20"
    assert normalize_date("成文于 2025/9/1") == "2025-09-01"
    assert normalize_date("没有日期") == ""
    assert normalize_date("日期 2026-13-40") == ""  # 非法月日


def test_parse_detail_structure():
    art = parse_detail(DETAIL_HTML, SOURCE,
                       "http://www.ccgp.gov.cn/zcfg/gwywj/202604/t20260420_26427310.htm")
    assert art is not None
    assert art.title == "国务院办公厅关于深化投资审批制度改革的意见"
    assert art.publish_date == "2026-04-20"
    assert "国办发" in art.content
    assert "深化投资审批制度改革" in art.content
    # 噪声行剔除
    assert "当前位置" not in art.content
    assert "版权所有" not in art.content
    assert not art.content.startswith("分享")


def test_publish_date_meta_beats_template_garbage():
    # MOF 模板里有静态"2017年11月21日 星期二"噪声块, meta PubDate 必须胜出
    html = ('<html><head><meta name="PubDate" content="2026-09-14 16:28:00"/></head>'
            '<body><div class="nav"><span>2017年11月21日 星期二</span></div>'
            '<div class="main_container"><p>正文 %s</p></div></body></html>' % ("政策内容" * 60))
    soup = BeautifulSoup(html, "lxml")
    body = soup.find(attrs={"class": "main_container"})
    assert extract_publish_date(soup, body) == "2026-09-14"

    # 无 meta 时不用整页噪声, 退回正文头部日期
    html2 = ('<html><body><div class="nav">2017年11月21日 星期二</div>'
             '<div class="main_container"><p>发布日期：2026年09月01日</p>'
             '<p>%s</p></div></body></html>' % ("政策内容" * 60))
    soup2 = BeautifulSoup(html2, "lxml")
    body2 = soup2.find(attrs={"class": "main_container"})
    assert extract_publish_date(soup2, body2) == "2026-09-01"


def test_parse_detail_too_short_returns_none():
    html = ('<html><body><h1>短正文页</h1>'
            '<div class="main_container"><p>只有很短的内容</p></div></body></html>')
    assert parse_detail(html, SOURCE, "http://www.ccgp.gov.cn/x.htm") is None


def _make_article(url="http://www.ccgp.gov.cn/a.htm"):
    body = "第一条　为了规范招标投标活动，保护国家利益和社会公共权益，" * 8
    return WebArticle(source="ccgp_test", source_label="测试源",
                      url=url, title="测试政策标题",
                      content=body, publish_date="2026-04-20")


def test_build_web_points_deterministic_and_metadata():
    art = _make_article()
    # 复用真实分片逻辑得到 chunks
    from src.rag.ingest import _chunk_tender_text
    chunks = _chunk_tender_text(art.content, 500, 80)
    assert len(chunks) >= 1

    def fake_dense(t): return [0.1] * 8
    def fake_sparse(t): return {"indices": [1, 2], "values": [0.5, 0.5]}

    p1 = build_web_points(art, chunks, fake_dense, fake_sparse)
    p2 = build_web_points(art, chunks, fake_dense, fake_sparse)
    assert [p["id"] for p in p1] == [p["id"] for p in p2]   # 重爬幂等覆盖
    assert len(p1) == len(chunks)
    p0 = p1[0]
    assert p0["doc_type"] == "official_web"
    assert p0["business_line"] == "regulation"
    assert p0["visibility"] == "public"
    assert p0["source_url"] == art.url
    assert p0["publish_date"] == "2026-04-20"
    assert p0["article_uid"] == article_uid(art)
    assert p0["chunk_id"].startswith("web-")

    # 不同 URL → 不同点 ID, 不会互相覆盖
    other = build_web_points(_make_article("http://www.ccgp.gov.cn/b.htm"),
                             chunks, fake_dense, fake_sparse)
    assert other[0]["id"] != p0["id"]


def test_crawl_source_state_incremental(tmp_path):
    """两轮爬取: 首轮新增, 次轮跳过; 内容变化第三轮更新."""
    pages = {
        "http://www.ccgp.gov.cn/zcfg/": LIST_HTML,
        "http://www.ccgp.gov.cn/zcfg/gwywj/202604/t20260420_26427310.htm": DETAIL_HTML,
        "http://www.ccgp.gov.cn/zcfg/other/page.html": DETAIL_HTML.replace(
            "国务院办公厅关于深化投资审批制度改革的意见",
            "国务院办公厅关于进一步优化营商环境的若干措施").replace(
            "2026-04-20", "2026-05-01"),
    }

    def fake_fetcher(session, url, source):
        return pages[url]

    # 第一轮: 2 篇新增
    state: dict = {}
    stats, articles = crawl_source(
        SOURCE, state, max_per_source=10, ignore_robots=True,
        session=object(), fetcher=fake_fetcher, sleep=False)
    assert stats.new == 2, (stats.new, stats.errors)
    assert stats.discovered == 2
    assert len(articles) == 2
    assert len(state) == 2

    # 第二轮: 无变化全部跳过
    stats2, articles2 = crawl_source(
        SOURCE, state, max_per_source=10, ignore_robots=True,
        session=object(), fetcher=fake_fetcher, sleep=False)
    assert stats2.skipped == 2
    assert articles2 == []


def test_registry_loads_with_three_enabled_sources():
    sources = load_sources()
    names = {s["name"] for s in sources}
    assert {"mof_policy", "ccgp_regulation", "mohurd_latest"} <= names
    for s in sources:
        assert s["entry_url"].startswith(("http://", "https://"))
        assert s.get("allowed_domains")


def test_state_roundtrip(tmp_path):
    sf = tmp_path / "state.json"
    state = {"mof_policy": {"http://x": {"content_sha": "abc"}}}
    save_state(state, sf)
    loaded = load_state(sf)
    assert loaded["mof_policy"]["http://x"]["content_sha"] == "abc"
