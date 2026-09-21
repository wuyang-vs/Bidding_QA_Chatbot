"""知识库自动更新: 定时扫描 data/ 目录, 新/变文件增量导入 Qdrant.

设计:
  - 进程内后台线程, 无外部依赖 (不要求 APScheduler)
  - 文件变化检测: mtime + size (不依赖 inotify, Windows/Linux 通用)
  - 处理幂等: 已处理文件写入 .ingest_state.json, 重启不重复导入
  - 增量导入: 调 ingest_real.py 的逻辑, --no-force 追加模式
  - 优雅关闭: FastAPI lifespan shutdown 时停止线程, 不打断正在进行的导入

使用:
  from src.rag.scheduler import start_auto_ingest, stop_auto_ingest
  start_auto_ingest()   # 启动后台线程
  stop_auto_ingest()    # 停止
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SUPPORTED_EXTS = {".xlsx", ".xls", ".csv", ".jsonl"}


class AutoIngestScheduler:
    """定时扫描 + 增量导入, 进程内单例."""

    def __init__(self, data_dir: str | None = None, interval_min: int = 30):
        from src.config import settings
        self._data_dir = Path(data_dir or settings.auto_ingest_data_dir)
        if not self._data_dir.is_absolute():
            self._data_dir = Path.cwd() / self._data_dir
        self._interval = interval_min * 60
        self._state_file = self._data_dir / ".ingest_state.json"
        self._state: dict[str, dict[str, Any]] = self._load_state()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._running_import = False

    # ---------- 状态持久化 ----------
    def _load_state(self) -> dict[str, dict[str, Any]]:
        if self._state_file.exists():
            try:
                return json.loads(self._state_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.warning("状态文件损坏, 重新开始")
        return {}

    def _save_state(self) -> None:
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            self._state_file.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.warning("保存状态失败: %s", e)

    @staticmethod
    def _file_hash(path: Path) -> str:
        """快速指纹: mtime + size (不读整个文件, 大文件也快)."""
        try:
            st = path.stat()
            return f"{int(st.st_mtime)}_{st.st_size}"
        except OSError:
            return ""

    # ---------- 扫描 ----------
    def _scan(self) -> list[Path]:
        """扫描 data_dir, 返回需要处理的文件 (新/变)."""
        if not self._data_dir.exists():
            return []
        need: list[Path] = []
        for ext in _SUPPORTED_EXTS:
            for p in self._data_dir.rglob(f"*{ext}"):
                fp = str(p.resolve())
                h = self._file_hash(p)
                prev = self._state.get(fp, {}).get("hash")
                if prev != h:
                    need.append(p)
                    logger.info("  待处理: %s", p.name)
        return need

    # ---------- 单次导入 ----------
    def _ingest_one(self, path: Path) -> bool:
        """对单个文件执行增量导入. 返回是否成功."""
        try:
            from src.rag.ingest import read_qa_data
            from src.rag.embedder import embedder
            from src.rag.vector_store import vector_store

            df, _ = read_qa_data(path)
            if df.empty:
                logger.warning("  %s: 清洗后无有效数据, 跳过", path.name)
                return False

            # 增量: 不 force, 追加到现有 collection
            embedder.fit_sparse(df["answer"].tolist())
            embedder.save_vocab()

            dense_vecs = embedder.encode_query_dense_batch(df["question"].tolist())
            sparse_vecs = embedder.encode_query_sparse_batch(df["answer"].tolist())

            points = []
            for i, row in df.iterrows():
                points.append({
                    "question": row["question"],
                    "answer": row["answer"],
                    "source_file": row.get("source_file", path.name),
                    "section_title": row.get("section_title", ""),
                    "doc_type": row.get("doc_type", "auto"),
                    "chunk_id": f"{path.stem}-{i}",
                    "dense": dense_vecs[i],
                    "sparse": sparse_vecs[i],
                })

            vector_store.upsert_points(points)
            logger.info("  ✅ %s: %d 条已导入", path.name, len(points))
            return True
        except Exception as e:
            logger.error("  ❌ %s 导入失败: %s", path.name, e)
            return False

    # ---------- 定时循环 ----------
    def _loop(self) -> None:
        logger.info("🔄 知识库自动更新已启动 (扫描间隔 %d min, 目录: %s)",
                    self._interval // 60, self._data_dir)
        # 启动后立即跑一次
        self._tick()
        while not self._stop.wait(self._interval):
            self._tick()
        logger.info("🔄 知识库自动更新已停止")

    def _tick(self) -> None:
        with self._lock:
            self._running_import = True
        try:
            need = self._scan()
            if not need:
                logger.debug("扫描完成, 无新文件")
                return
            logger.info("发现 %d 个待处理文件", len(need))
            for p in need:
                ok = self._ingest_one(p)
                fp = str(p.resolve())
                if ok:
                    self._state[fp] = {
                        "hash": self._file_hash(p),
                        "last_ingest": int(time.time()),
                        "status": "ok",
                    }
                else:
                    self._state[fp] = {
                        "hash": self._file_hash(p),
                        "last_ingest": int(time.time()),
                        "status": "failed",
                    }
            self._save_state()
        finally:
            with self._lock:
                self._running_import = False

    # ---------- 公共 API ----------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            logger.warning("自动更新已在运行")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="auto-ingest")
        self._thread.start()

    def stop(self, timeout: float = 10) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
            self._thread = None

    def trigger_now(self) -> dict[str, Any]:
        """手动触发一次扫描导入 (API 端点用)."""
        self._tick()
        processed = sum(1 for v in self._state.values() if v.get("status") == "ok")
        failed = sum(1 for v in self._state.values() if v.get("status") == "failed")
        return {"processed_ok": processed, "processed_failed": failed, "total_tracked": len(self._state)}

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def is_importing(self) -> bool:
        return self._running_import


# ---------- 官网爬取定时调度(默认关闭) ----------
class WebCrawlScheduler:
    """按小时间隔爬取官网权威信息源并入向量库, 进程内单例."""

    def __init__(self, interval_hours: int = 24, max_per_source: int = 10):
        self._interval = interval_hours * 3600
        self._max_per_source = max_per_source
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_result: dict[str, Any] | None = None

    def _tick(self) -> dict[str, Any]:
        result = execute_web_crawl(self._max_per_source)
        self._last_result = result
        if result.get("status") != "busy":
            logger.info("官网定时爬取完成: %s", result)
        return result

    def _loop(self) -> None:
        logger.info("🕷️ 官网定时爬取已启动 (间隔 %d h)", self._interval // 3600)
        self._tick()
        while not self._stop.wait(self._interval):
            self._tick()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="web-crawl")
        self._thread.start()

    def stop(self, timeout: float = 10) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
            self._thread = None

    def trigger_now(self) -> dict[str, Any]:
        return self._tick()

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def is_crawling(self) -> bool:
        return _manual_lock.locked()

    @property
    def last_result(self) -> dict[str, Any] | None:
        return self._last_result


_web_scheduler: WebCrawlScheduler | None = None
_manual_lock = threading.Lock()


def execute_web_crawl(max_per_source: int = 10) -> dict:
    """执行一轮官网爬取入库(定时线程与管理端点共用, 进程内互斥)."""
    if not _manual_lock.acquire(blocking=False):
        return {"status": "busy", "message": "已有爬取任务在执行"}
    try:
        from src.ingestion.web_crawler import load_sources, run as crawl_run
        from src.ingestion.web_ingest import load_state, save_state, ingest_articles

        sources = load_sources()
        state = load_state()
        stats_list, articles = crawl_run(sources, state,
                                         max_per_source=max_per_source)
        ingested = {"ingested_articles": 0, "ingested_chunks": 0, "failed": 0}
        if articles:
            ingested = ingest_articles(articles, state)
            save_state(state)
        return {
            "status": "ok",
            "sources": len(sources),
            "per_source": [
                {"source": s.source, "discovered": s.discovered, "new": s.new,
                 "updated": s.updated, "skipped": s.skipped, "failed": s.failed}
                for s in stats_list],
            "articles": ingested["ingested_articles"],
            "chunks": ingested["ingested_chunks"],
            "skipped": sum(s.skipped for s in stats_list),
            "failed": sum(s.failed for s in stats_list) + ingested["failed"],
            "ran_at": int(time.time()),
        }
    except Exception as e:
        logger.exception("官网爬取失败: %s", e)
        return {"status": "error", "message": str(e)}
    finally:
        _manual_lock.release()


# 管理端点手动触发(与定时线程共用 execute_web_crawl)
run_web_crawl_once = execute_web_crawl


def start_web_crawl() -> WebCrawlScheduler | None:
    from src.config import settings
    global _web_scheduler
    if not settings.web_crawl_enabled:
        logger.info("WEB_CRAWL_ENABLED=false, 跳过官网定时爬取")
        return None
    if _web_scheduler is None:
        _web_scheduler = WebCrawlScheduler(
            interval_hours=settings.web_crawl_interval_hours,
            max_per_source=settings.web_crawl_max_per_source)
    _web_scheduler.start()
    return _web_scheduler


def stop_web_crawl() -> None:
    global _web_scheduler
    if _web_scheduler:
        _web_scheduler.stop()
        _web_scheduler = None


def get_web_crawl_scheduler() -> WebCrawlScheduler | None:
    return _web_scheduler


# ---------- 单例 ----------
_scheduler: AutoIngestScheduler | None = None


def start_auto_ingest() -> AutoIngestScheduler | None:
    from src.config import settings
    global _scheduler
    if not settings.auto_ingest_enabled:
        logger.info("AUTO_INGEST_ENABLED=false, 跳过自动更新")
        return None
    if _scheduler is None:
        _scheduler = AutoIngestScheduler(
            data_dir=settings.auto_ingest_data_dir,
            interval_min=settings.auto_ingest_interval_min,
        )
    _scheduler.start()
    return _scheduler


def stop_auto_ingest() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.stop()
        _scheduler = None


def get_scheduler() -> AutoIngestScheduler | None:
    return _scheduler
