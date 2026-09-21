# -*- coding: utf-8 -*-
"""官网权威信息源爬取 → 结构化抽取 → 向量库增量入库 (CLI).

用法:
  python scripts/crawl_official_sources.py --list                 # 列出注册源
  python scripts/crawl_official_sources.py --all-enabled          # 爬所有启用源(默认每源10篇)
  python scripts/crawl_official_sources.py --source mof_policy --max-per-source 5
  python scripts/crawl_official_sources.py --all-enabled --dry-run  # 只爬不入库
  python scripts/crawl_official_sources.py --all-enabled --ignore-robots
  python scripts/crawl_official_sources.py --reset-state --all-enabled  # 清状态全量重爬

可挂 Windows 任务计划/crontab 实现每日自动更新。
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("crawl")


def main() -> int:
    ap = argparse.ArgumentParser(description="政府官网政策法规爬取入库")
    ap.add_argument("--list", action="store_true", help="列出注册的信息源")
    ap.add_argument("--source", action="append", default=[],
                    help="指定源 name(可多次); 不给则用全部启用源")
    ap.add_argument("--all-enabled", action="store_true", help="爬取所有 enabled=true 的源")
    ap.add_argument("--max-per-source", type=int, default=10, help="每源最多抓详情数(默认10)")
    ap.add_argument("--dry-run", action="store_true", help="只发现/抽取, 不写入向量库与状态")
    ap.add_argument("--ignore-robots", action="store_true", help="跳过 robots.txt 约束")
    ap.add_argument("--reset-state", action="store_true", help="先清空爬取状态(全量重爬)")
    args = ap.parse_args()

    from src.ingestion.web_crawler import load_sources, run as crawl_run
    from src.ingestion.web_ingest import (STATE_FILE, load_state, save_state,
                                          ingest_articles)

    include_disabled = bool(args.source) and not args.all_enabled
    sources = load_sources(only=args.source or None, include_disabled=include_disabled)

    if args.list:
        for s in load_sources(include_disabled=True):
            flag = "启用" if s.get("enabled") else "停用"
            print(f"  [{flag}] {s['name']:<18} {s.get('label','')}  -> {s['entry_url']}")
        return 0

    if not sources:
        logger.error("没有匹配的信息源(用 --list 查看)")
        return 1

    if args.reset_state and STATE_FILE.exists():
        STATE_FILE.unlink()
        logger.warning("已清空爬取状态: %s", STATE_FILE)

    state = load_state()
    logger.info("开始爬取 %d 个源, 每源上限 %d 篇 (dry_run=%s, ignore_robots=%s)",
                len(sources), args.max_per_source, args.dry_run, args.ignore_robots)

    stats_list, articles = crawl_run(
        sources, state,
        max_per_source=args.max_per_source,
        dry_run=args.dry_run,
        ignore_robots=args.ignore_robots)

    for st in stats_list:
        logger.info("[%s] 发现=%d 新增=%d 更新=%d 跳过=%d 失败=%d",
                    st.source, st.discovered, st.new, st.updated,
                    st.skipped, st.failed)
        for err in st.errors[:5]:
            logger.warning("    %s", err)

    if args.dry_run:
        logger.info("dry-run: 抽取 %d 篇, 未入库", len(articles))
        for a in articles[:10]:
            logger.info("    《%s》 %s (%d字) %s",
                        a.title[:40], a.publish_date, len(a.content), a.url)
        return 0

    if not articles:
        logger.info("无新增/变更文章, 向量库保持不变")
        return 0

    # 初始化本地嵌入模型
    from src.rag.embedder import embedder
    if not embedder.load_vocab():
        logger.error("vocab.json 不存在, 请先完成基础数据入库")
        return 2
    # sparse 词表由 ingest_articles 按本批语料统一 fit; 仅需加载 dense 模型
    embedder._load_dense()

    ing = ingest_articles(articles, state)
    save_state(state)

    from src.rag.vector_store import vector_store
    logger.info("完成: 文章入库=%d (%d 分片), 失败=%d; Qdrant 总点数=%d",
                ing["ingested_articles"], ing["ingested_chunks"],
                ing["failed"], vector_store.count())
    return 0 if ing["failed"] == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
