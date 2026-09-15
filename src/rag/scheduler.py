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
