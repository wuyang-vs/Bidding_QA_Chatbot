"""系统监控测试 — mock psutil, 验证降级/格式/趋势."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from src.tools.system_monitor import MetricSample, SystemMonitor


def _make_sample(cpu=20.0, mem_pct=50.0, disk_pct=60.0, gpu=None) -> MetricSample:
    return MetricSample(
        timestamp=time.time(),
        cpu_percent=cpu,
        memory_percent=mem_pct,
        memory_used_mb=4096.0,
        memory_total_mb=8192.0,
        disk_percent=disk_pct,
        disk_used_gb=300.0,
        disk_total_gb=500.0,
        gpu_percent=gpu,
        gpu_memory_percent=None,
    )


class TestSystemMonitor:
    def test_snapshot_format_no_samples(self):
        """无后台线程 + 无历史样本 → 返回 ready=False, 手动采一次."""
        m = SystemMonitor(enabled=True)
        data = m.snapshot()

        assert "ready" in data
        assert "current" in data
        assert "trend" in data
        assert "system" in data
        assert "samples_count" in data

    def test_snapshot_with_samples(self):
        """有历史样本 → current = 最新, trend = 首尾 delta."""
        m = SystemMonitor(enabled=True, interval=1.0, window_seconds=10.0, max_samples=10)
        # 手动往 deque 塞几条
        s1 = _make_sample(cpu=10.0)
        s2 = _make_sample(cpu=30.0)
        s3 = _make_sample(cpu=50.0)
        with m._lock:
            m._series.append(s1)
            m._series.append(s2)
            m._series.append(s3)
        m._ready = True

        data = m.snapshot()
        assert data["ready"] is True
        assert data["samples_count"] == 3
        # current 是最新的 cpu=50
        assert data["current"]["cpu_percent"] == 50.0
        # trend: 50 - 10 = +40
        assert data["trend"]["cpu_delta"] == 40.0

    def test_disabled_returns_ready_false(self):
        m = SystemMonitor(enabled=False)
        data = m.snapshot()
        assert data["ready"] is False

    def test_trend_single_sample(self):
        """只有 1 条样本 → trend 为空 (不够算 delta)."""
        m = SystemMonitor(enabled=True)
        with m._lock:
            m._series.append(_make_sample())
        data = m.snapshot()
        assert data["trend"] == {}

    def test_gpu_none_when_no_nvml(self):
        """无 pynvml 时, current.gpu_percent = None."""
        m = SystemMonitor(enabled=True)
        # 手动构造不带 gpu 的 sample
        s = _make_sample(gpu=None)
        with m._lock:
            m._series.append(s)
        data = m.snapshot()
        assert data["current"]["gpu_percent"] is None
        assert data["system"]["gpu_available"] is False

    def test_series_maxlen_auto_evict(self):
        """deque(maxlen=3) 超过后自动淘汰旧样本."""
        m = SystemMonitor(enabled=True, max_samples=3)
        for i in range(5):
            with m._lock:
                m._series.append(_make_sample(cpu=float(i * 10)))
        with m._lock:
            assert len(m._series) == 3
            assert m._series[0].cpu_percent == 20.0  # 淘汰了 0, 1
            assert m._series[-1].cpu_percent == 40.0

    def test_snapshot_system_info(self):
        """system 字段包含 platform/uptime/processes."""
        m = SystemMonitor(enabled=True)
        data = m.snapshot()
        sys_info = data["system"]
        assert "platform" in sys_info
        assert "boot_time" in sys_info
        assert "processes" in sys_info
        assert "gpu_available" in sys_info


class TestSystemMonitorLifecycle:
    def test_start_stop_idempotent(self):
        """start/stop 幂等, 多次调用不崩."""
        m = SystemMonitor(enabled=True, interval=60.0)  # 长间隔, 线程很快退出
        m.start()
        m.start()  # 第二次应该是 no-op
        assert m._thread is not None
        assert m._thread.is_alive()
        m.stop(timeout=2.0)
        assert not m._ready
        m.stop()  # 再次 stop 也不崩

    def test_start_disabled_no_thread(self):
        m = SystemMonitor(enabled=False)
        m.start()
        assert m._thread is None
        assert m._ready is False


class TestSystemMonitorSampling:
    @patch("src.tools.system_monitor.psutil", create=True)
    def test_sample_psutil_error_degrades_gracefully(self, mock_psutil):
        """psutil 完全不可用时, _sample_once 返回全 -1 不崩."""
        mock_psutil.cpu_percent.side_effect = RuntimeError("no cpu")
        mock_psutil.virtual_memory.side_effect = RuntimeError("no mem")
        mock_psutil.disk_usage.side_effect = RuntimeError("no disk")

        from src.tools.system_monitor import SystemMonitor as _SM
        m = _SM(enabled=True)
        s = m._sample_once()
        assert s.cpu_percent == -1.0
        assert s.memory_percent == -1.0
        assert s.disk_percent == -1.0

    @patch("src.tools.system_monitor.psutil", create=True)
    def test_sample_gpu_skipped_without_nvml(self, mock_psutil):
        """无 pynvml 时 gpu_percent = None, 其他正常采."""
        mock_psutil.cpu_percent.return_value = 35.0
        mock_psutil.virtual_memory.return_value = MagicMock(
            percent=60.0, used=4 * 1024**3, total=8 * 1024**3
        )
        mock_psutil.disk_usage.return_value = MagicMock(
            percent=70.0, used=300 * 1024**3, total=500 * 1024**3
        )

        # 确保 pynvml 不可用
        import src.tools.system_monitor as sm_mod
        with patch.object(sm_mod, "_HAS_NVML", False):
            m = SystemMonitor(enabled=True)
            s = m._sample_once()
            assert s.cpu_percent == 35.0
            assert s.gpu_percent is None
            assert s.gpu_memory_percent is None

    def test_sample_to_dict_rounding(self):
        """_sample_to_dict 数值四舍五入正确."""
        m = SystemMonitor(enabled=True)
        s = _make_sample(cpu=33.567, mem_pct=50.0, disk_pct=60.0)
        d = m._sample_to_dict(s)
        assert d["cpu_percent"] == 33.6  # round(33.567, 1)
        assert d["disk_used_gb"] == 300.0
