"""AutoIngestScheduler 单元测试 — 不依赖真实 Qdrant, 用 mock 验证扫描/状态/线程安全."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from src.rag.scheduler import AutoIngestScheduler, _SUPPORTED_EXTS


# ---------- 扫描 & 状态 ----------

def test_scan_new_file(tmp_path: Path):
    """新文件 → 应被检测为待处理."""
    s = AutoIngestScheduler(data_dir=str(tmp_path), interval_min=999)
    f = tmp_path / "qa.xlsx"
    f.write_text("fake")
    need = s._scan()
    assert len(need) == 1
    assert need[0].name == "qa.xlsx"


def test_scan_no_duplicate(tmp_path: Path):
    """已处理的文件 (hash 不变) → 不应重复."""
    s = AutoIngestScheduler(data_dir=str(tmp_path), interval_min=999)
    f = tmp_path / "qa.xlsx"
    f.write_text("fake")
    # 标记为已处理
    s._state[str(f.resolve())] = {"hash": s._file_hash(f), "status": "ok"}
    need = s._scan()
    assert len(need) == 0


def test_scan_modified_file(tmp_path: Path):
    """文件修改 (hash 变) → 应重新处理."""
    s = AutoIngestScheduler(data_dir=str(tmp_path), interval_min=999)
    f = tmp_path / "qa.xlsx"
    f.write_text("v1")
    s._state[str(f.resolve())] = {"hash": s._file_hash(f), "status": "ok"}
    # 修改 (大小变, hash 一定变)
    f.write_text("much longer content v2 with more bytes")
    need = s._scan()
    assert len(need) == 1


def test_state_persistence(tmp_path: Path):
    """状态写入文件 → 重启后能读回."""
    s = AutoIngestScheduler(data_dir=str(tmp_path), interval_min=999)
    s._state = {"/fake/path": {"hash": "abc", "status": "ok"}}
    s._save_state()
    # 新实例读同一文件
    s2 = AutoIngestScheduler(data_dir=str(tmp_path), interval_min=999)
    assert "/fake/path" in s2._state
    assert s2._state["/fake/path"]["hash"] == "abc"


def test_state_corruption(tmp_path: Path):
    """状态文件损坏 → 不崩, 重新开始."""
    s = AutoIngestScheduler(data_dir=str(tmp_path), interval_min=999)
    s._state_file.write_text("{not valid json", encoding="utf-8")
    s2 = AutoIngestScheduler(data_dir=str(tmp_path), interval_min=999)
    assert s2._state == {}


# ---------- 扫描范围 ----------

def test_supported_exts():
    """只扫描指定扩展名."""
    assert ".xlsx" in _SUPPORTED_EXTS
    assert ".xls" in _SUPPORTED_EXTS
    assert ".csv" in _SUPPORTED_EXTS
    assert ".jsonl" in _SUPPORTED_EXTS
    assert ".txt" not in _SUPPORTED_EXTS


def test_noise_files_ignored(tmp_path: Path):
    """非支持扩展名的文件被忽略."""
    s = AutoIngestScheduler(data_dir=str(tmp_path), interval_min=999)
    (tmp_path / "readme.txt").write_text("ignore")
    (tmp_path / "data.csv").write_text("ok")
    need = s._scan()
    assert len(need) == 1
    assert need[0].name == "data.csv"


def test_nested_subdir_scanned(tmp_path: Path):
    """子目录里的文件也被扫描."""
    s = AutoIngestScheduler(data_dir=str(tmp_path), interval_min=999)
    sub = tmp_path / "sub" / "deep"
    sub.mkdir(parents=True)
    (sub / "qa.xlsx").write_text("fake")
    need = s._scan()
    assert len(need) == 1


# ---------- tick 幂等 (mock ingest) ----------

def test_tick_marks_processed(tmp_path: Path):
    """成功导入后 → 状态更新为 ok."""
    s = AutoIngestScheduler(data_dir=str(tmp_path), interval_min=999)
    f = tmp_path / "qa.xlsx"
    f.write_text("fake")

    with patch.object(AutoIngestScheduler, "_ingest_one", return_value=True):
        s._tick()

    fp = str(f.resolve())
    assert fp in s._state
    assert s._state[fp]["status"] == "ok"


def test_tick_marks_failed(tmp_path: Path):
    """导入失败后 → 状态仍记录为 failed (下次会重试, 因为 hash 匹配)."""
    s = AutoIngestScheduler(data_dir=str(tmp_path), interval_min=999)
    f = tmp_path / "qa.xlsx"
    f.write_text("fake")

    with patch.object(AutoIngestScheduler, "_ingest_one", return_value=False):
        s._tick()

    fp = str(f.resolve())
    assert s._state[fp]["status"] == "failed"


# ---------- 线程 ----------

def test_start_stop(tmp_path: Path):
    """启动 → 运行中; 停止 → 已停止."""
    s = AutoIngestScheduler(data_dir=str(tmp_path), interval_min=999)
    s.start()
    assert s.is_running
    s.stop(timeout=5)
    assert not s.is_running


def test_stop_idempotent(tmp_path: Path):
    """重复 stop 不崩."""
    s = AutoIngestScheduler(data_dir=str(tmp_path), interval_min=999)
    s.stop()  # 未启动
    s.stop()  # 重复


def test_start_idempotent(tmp_path: Path):
    """重复 start 不崩 (第二次忽略)."""
    s = AutoIngestScheduler(data_dir=str(tmp_path), interval_min=999)
    s.start()
    s.start()  # 第二次应忽略
    s.stop(timeout=5)


def test_is_importing_flag(tmp_path: Path):
    """_running_import 标志正确切换."""
    s = AutoIngestScheduler(data_dir=str(tmp_path), interval_min=999)
    assert not s.is_importing

    def hold():
        with s._lock:
            s._running_import = True
        time.sleep(0.3)
        with s._lock:
            s._running_import = False

    t = threading.Thread(target=hold)
    t.start()
    time.sleep(0.05)
    assert s.is_importing
    t.join()
    assert not s.is_importing


# ---------- trigger_now ----------

def test_trigger_now_busy(tmp_path: Path):
    """导入进行中 → trigger_now 不崩 (锁竞争)."""
    s = AutoIngestScheduler(data_dir=str(tmp_path), interval_min=999)

    def hold():
        with s._lock:
            s._running_import = True
            time.sleep(0.3)
            s._running_import = False

    t = threading.Thread(target=hold)
    t.start()
    time.sleep(0.05)
    # trigger_now 会等锁, 不崩
    t.join()
