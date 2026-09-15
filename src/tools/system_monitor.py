"""系统监控: CPU / 内存 / 磁盘 / GPU (可选降级).

后台线程每 5 秒采样一次, 维护 60 秒滚动窗口时间序列.
API 返回当前值 + 最近趋势 + 组件健康状态.

设计原则:
  - 轻量: 只用 psutil (纯 Python, 跨平台)
  - 降级: GPU 用 pynvml, 非 NVIDIA 环境自动跳过不崩
  - 解耦: 独立模块, 不耦合 Agent/RAG 主流程
  - 可关: enable 开关 + 采样间隔/窗口长度可配
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

try:
    import psutil  # type: ignore
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore

try:
    import pynvml  # type: ignore
    _HAS_NVML = True
except Exception:  # pragma: no cover - 非 NVIDIA 环境
    pynvml = None  # type: ignore
    _HAS_NVML = False


@dataclass
class MetricSample:
    timestamp: float
    cpu_percent: float
    memory_percent: float
    memory_used_mb: float
    memory_total_mb: float
    disk_percent: float
    disk_used_gb: float
    disk_total_gb: float
    gpu_percent: float | None = None
    gpu_memory_percent: float | None = None


@dataclass
class SystemMonitor:
    """后台采样 + 时间序列缓存."""

    enabled: bool = True
    interval: float = 5.0  # 采样间隔 (秒)
    window_seconds: float = 60.0  # 时间序列窗口
    max_samples: int = 12  # window / interval

    # 时间序列 deque (线程安全, maxlen 自动淘汰)
    _series: deque[MetricSample] = field(init=False)
    _thread: threading.Thread | None = field(init=False, default=None)
    _stop_event: threading.Event = field(init=False)
    _lock: threading.Lock = field(init=False)
    _ready: bool = field(init=False, default=False)

    def __post_init__(self):
        self._series = deque(maxlen=self.max_samples)
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    # ── 后台线程 ──────────────────────────────────────────

    def start(self) -> None:
        """启动后台采样线程 (幂等)."""
        if not self.enabled or psutil is None:
            logger.info("SystemMonitor: 未启用 (enabled=%s, psutil=%s)", self.enabled, psutil is not None)
            self._ready = False
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="SystemMonitor", daemon=True)
        self._thread.start()
        self._ready = True
        logger.info("SystemMonitor: 后台线程已启动 (interval=%.1fs, window=%.0fs)", self.interval, self.window_seconds)

    def stop(self, timeout: float = 5.0) -> None:
        """停止后台线程, 等待 timeout 秒."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        self._ready = False
        logger.info("SystemMonitor: 已停止")

    def _run(self) -> None:
        # 首次 cpu_percent 必须带 interval=None 先初始化 (返回 0.0)
        try:
            psutil.cpu_percent(interval=None)
        except Exception:
            pass
        while not self._stop_event.is_set():
            try:
                sample = self._sample_once()
                with self._lock:
                    self._series.append(sample)
            except Exception as e:
                logger.warning("SystemMonitor 采样失败: %s", e)
            self._stop_event.wait(self.interval)

    # ── 采样 ──────────────────────────────────────────────

    def _sample_once(self) -> MetricSample:
        # CPU
        try:
            cpu = float(psutil.cpu_percent(interval=None))
        except Exception:
            cpu = -1.0

        # 内存
        try:
            mem = psutil.virtual_memory()
            mem_pct = float(mem.percent)
            mem_used_mb = float(mem.used / (1024 * 1024))
            mem_total_mb = float(mem.total / (1024 * 1024))
        except Exception:
            mem_pct = mem_used_mb = mem_total_mb = -1.0

        # 磁盘 (系统盘)
        try:
            disk = psutil.disk_usage(self._system_drive())
            disk_pct = float(disk.percent)
            disk_used_gb = float(disk.used / (1024 ** 3))
            disk_total_gb = float(disk.total / (1024 ** 3))
        except Exception:
            disk_pct = disk_used_gb = disk_total_gb = -1.0

        # GPU (可选)
        gpu_pct, gpu_mem_pct = self._sample_gpu()

        return MetricSample(
            timestamp=time.time(),
            cpu_percent=cpu,
            memory_percent=mem_pct,
            memory_used_mb=mem_used_mb,
            memory_total_mb=mem_total_mb,
            disk_percent=disk_pct,
            disk_used_gb=disk_used_gb,
            disk_total_gb=disk_total_gb,
            gpu_percent=gpu_pct,
            gpu_memory_percent=gpu_mem_pct,
        )

    def _sample_gpu(self) -> tuple[float | None, float | None]:
        if not _HAS_NVML:
            return None, None
        try:
            pynvml.nvmlInit()
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            gpu_pct = float(util.gpu)
            gpu_mem_pct = float(mem.used / mem.total * 100.0) if mem.total > 0 else None
            return gpu_pct, gpu_mem_pct
        except Exception:
            return None, None

    @staticmethod
    def _system_drive() -> str:
        import os
        drive = os.environ.get("SystemDrive") or "C:"
        if os.name == "nt":
            return f"{drive}\\"
        return "/"

    # ── 对外 API ──────────────────────────────────────────

    def snapshot(self) -> dict:
        """返回完整监控快照 (当前值 + 趋势 + 系统信息)."""
        with self._lock:
            series = list(self._series)

        if not series:
            # 无后台线程或采样不够, 手动采一次
            try:
                cur = self._sample_once()
            except Exception:
                cur = None
            return self._format_empty(cur)

        cur = series[-1]
        trend = self._calc_trend(series)

        return {
            "ready": self._ready,
            "sampling_interval_sec": self.interval,
            "samples_count": len(series),
            "window_seconds": int(self.window_seconds),
            "current": self._sample_to_dict(cur),
            "trend": trend,
            "system": self._system_info(),
        }

    def _sample_to_dict(self, s: MetricSample | None) -> dict:
        if s is None:
            return {}
        return {
            "timestamp": s.timestamp,
            "cpu_percent": round(s.cpu_percent, 1),
            "memory_percent": round(s.memory_percent, 1),
            "memory_used_mb": round(s.memory_used_mb, 1),
            "memory_total_mb": round(s.memory_total_mb, 1),
            "disk_percent": round(s.disk_percent, 1),
            "disk_used_gb": round(s.disk_used_gb, 2),
            "disk_total_gb": round(s.disk_total_gb, 2),
            "gpu_percent": round(s.gpu_percent, 1) if s.gpu_percent is not None else None,
            "gpu_memory_percent": round(s.gpu_memory_percent, 1) if s.gpu_memory_percent is not None else None,
        }

    def _calc_trend(self, series: list[MetricSample]) -> dict:
        """简单趋势: 最早 vs 最新, 算 delta 百分比."""
        if len(series) < 2:
            return {}
        first = series[0]
        last = series[-1]

        def delta(cur: float | None, old: float | None) -> float | None:
            if cur is None or old is None or old == 0 or cur < 0 or old < 0:
                return None
            return round(cur - old, 1)

        return {
            "samples": len(series),
            "cpu_delta": delta(last.cpu_percent, first.cpu_percent),
            "memory_delta": delta(last.memory_percent, first.memory_percent),
            "disk_delta": delta(last.disk_percent, first.disk_percent),
            "gpu_delta": delta(last.gpu_percent, first.gpu_percent),
        }

    def _system_info(self) -> dict:
        try:
            boot = psutil.boot_time()
        except Exception:
            boot = None
        try:
            procs = len(psutil.pids())
        except Exception:
            procs = -1
        return {
            "platform": __import__("platform").platform(),
            "boot_time": boot,
            "uptime_sec": round(time.time() - boot, 1) if boot else None,
            "processes": procs,
            "gpu_available": _HAS_NVML,
        }

    def _format_empty(self, cur: MetricSample | None) -> dict:
        return {
            "ready": False,
            "sampling_interval_sec": self.interval,
            "samples_count": 0,
            "window_seconds": int(self.window_seconds),
            "current": self._sample_to_dict(cur) if cur else {},
            "trend": {},
            "system": self._system_info(),
        }


# ── 模块级单例 ────────────────────────────────────────────

system_monitor = SystemMonitor()
