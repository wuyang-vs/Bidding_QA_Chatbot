# -*- coding: utf-8 -*-
"""官网文章 → Qdrant 知识库增量入库.

- 复用 src.rag.ingest 的滑动窗口分片与 embedder/vector_store;
- 点 ID 由 (url, chunk_idx) 哈希确定性生成: 同一文章重爬覆盖旧点, 无需 ID 段管理;
- 入库前按 article_uid 清理该文章旧分片(兼容文章变短的情况);
- 爬取状态落 data/web/.crawl_state.json, 重启不重复爬取/入库。
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

from src.ingestion.web_crawler import WebArticle
from src.rag.ingest import _chunk_tender_text, _heading_of

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "data" / "web"
STATE_FILE = WEB_DIR / ".crawl_state.json"

_CHUNK_SIZE = 500
_CHUNK_OVERLAP = 80
_U63 = (1 << 63) - 1


def article_uid(article: WebArticle) -> str:
    return hashlib.sha1(article.url.encode("utf-8")).hexdigest()[:16]


def _point_id(uid: str, idx: int) -> int:
    h = hashlib.md5(f"web::{uid}::{idx}".encode("utf-8")).hexdigest()
    return int(h[:15], 16) & _U63


def load_state(path: Path | None = None) -> dict:
    """结构: {source_name: {url: {content_sha, title, publish_date, chunks, ...}}}."""
    p = path or STATE_FILE
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("爬取状态文件损坏, 重新开始")
    return {}


def save_state(state: dict, path: Path | None = None) -> None:
    p = path or STATE_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _article_header(article: WebArticle) -> str:
    header = f"{article.title} ({article.source_label}"
    if article.publish_date:
        header += f", {article.publish_date}"
    return header + ")"


def build_web_points(article: WebArticle, chunks: list[str],
                     encode_dense, encode_sparse) -> list[dict]:
    """纯函数: 文章 + 分片 + 注入的编码器 → Qdrant point 列表(可离线单测)."""
    uid = article_uid(article)
    source_file = f"{article.source_label}"
    header = _article_header(article)
    points = []
    for i, ch in enumerate(chunks):
        heading = _heading_of(ch)
        combined = f"{header}\n{ch}"
        points.append({
            "id": _point_id(uid, i),
            "dense": encode_dense(combined),
            "sparse": encode_sparse(combined),
            "question": f"【政策法规】{article.title} - {heading}",
            "answer": ch,
            "source_file": source_file[:200],
            "section_title": heading[:100],
            "doc_type": "official_web",
            "chunk_id": f"web-{uid}-{i}",
            "business_line": article.business_line or "regulation",
            "visibility": "public",
            "source_url": article.url,
            "article_uid": uid,
            **({"publish_date": article.publish_date} if article.publish_date else {}),
        })
    return points


def _snapshot(article: WebArticle) -> None:
    """落一份 JSONL 快照供审计/离线复跑(文件入 .gitignore)."""
    day = time.strftime("%Y%m%d")
    d = WEB_DIR / "articles" / day
    d.mkdir(parents=True, exist_ok=True)
    rec = {
        "source": article.source, "source_label": article.source_label,
        "url": article.url, "title": article.title,
        "publish_date": article.publish_date, "content": article.content,
        "fetched_at": article.fetched_at,
    }
    with (d / f"{article.source}.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def ingest_articles(articles: list[WebArticle], state: dict,
                    *, snapshot: bool = True) -> dict:
    """批量入库并回写 state. 统计 {ingested_articles, ingested_chunks, failed}.

    sparse 词表按本批全部分片统一 fit 一次(与 FAQ 全量入库路径一致),
    避免逐篇 fit 用单文章小语料覆盖全局词表。
    """
    from src.rag.embedder import embedder
    from src.rag.vector_store import vector_store

    stats = {"ingested_articles": 0, "ingested_chunks": 0, "failed": 0}

    prepared: list[tuple[WebArticle, list[str]]] = []
    for art in articles:
        chunks = _chunk_tender_text(art.content, _CHUNK_SIZE, _CHUNK_OVERLAP)
        if chunks:
            prepared.append((art, chunks))
        else:
            stats["failed"] += 1
            state.setdefault(art.source, {}).setdefault(art.url, {})["status"] = "empty"
    if not prepared:
        return stats

    if not vector_store.collection_exists():
        vector_store.create_collection(force=False)

    # 本批词表统一 fit
    corpus = [f"{_article_header(art)}\n{ch}" for art, chunks in prepared for ch in chunks]
    embedder.fit_sparse(corpus)
    embedder.save_vocab()

    for art, chunks in prepared:
        sub = state.setdefault(art.source, {})
        try:
            uid = article_uid(art)
            # 清旧分片: 覆盖更新且兼容"文章变短"产生的残余分片
            vector_store.delete_by_payload("article_uid", uid)
            points = build_web_points(
                art, chunks,
                embedder.encode_document_dense, embedder.encode_document_sparse)
            vector_store.upsert_points(points)
            n = len(points)
            prev = sub.get(art.url, {})
            sub[art.url] = {
                "content_sha": art.content_sha(),
                "title": art.title,
                "publish_date": art.publish_date,
                "chunks": n,
                "first_seen": prev.get("first_seen", art.fetched_at or int(time.time())),
                "last_seen": int(time.time()),
                "status": "ok",
            }
            if snapshot:
                _snapshot(art)
            stats["ingested_articles"] += 1
            stats["ingested_chunks"] += n
            logger.info("[%s] 《%s》入库 %d 分片", art.source, art.title[:30], n)
        except Exception as e:
            stats["failed"] += 1
            sub.setdefault(art.url, {})["status"] = "failed"
            sub[art.url]["last_error"] = f"{type(e).__name__}: {e}"
            logger.exception("文章入库失败 %s", art.url)
    return stats
