"""截止日期监控 — 从 bidding_documents 表扫描临近截止项目.

预警等级:
  - 🔴 紧急 (< 1 天)
  - 🟠 警告 (1-3 天)
  - 🟡 提示 (3-7 天)
  - ⚪ 已过期 (> deadline)

使用:
  monitor = DeadlineMonitor()
  alerts = monitor.check(within_days=7)  # 查 7 天内
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


# 中文日期解析: 招标公告日期格式杂, 尽量覆盖常见写法
_DATE_PATTERNS = [
    re.compile(r"(\d{4})[年\-/.](\d{1,2})[月\-/.](\d{1,2})[日号]?"),
    re.compile(r"(\d{1,2})[月/\-](\d{1,2})[日号]?"),  # 缺年份 → 补当前年
    re.compile(r"(\d{4})(\d{2})(\d{2})"),  # YYYYMMDD
]


def parse_deadline(text: str) -> datetime | None:
    """从 deadline 字段原文解析日期. 解析失败返回 None."""
    if not text:
        return None
    text = str(text).strip()

    # 带时分秒
    has_time = re.search(r"(\d{1,2})[:：](\d{2})", text)

    for pat in _DATE_PATTERNS:
        m = pat.search(text)
        if m:
            groups = m.groups()
            try:
                if len(groups) == 3:
                    y, mo, d = int(groups[0]), int(groups[1]), int(groups[2])
                elif len(groups) == 2:
                    now = datetime.now()
                    y, mo, d = now.year, int(groups[0]), int(groups[1])
                else:
                    continue
                dt = datetime(y, mo, d)
                if has_time:
                    hh = int(has_time.group(1))
                    mm = int(has_time.group(2))
                    dt = dt.replace(hour=hh, minute=mm)
                return dt
            except ValueError:
                continue
    return None


def classify_urgency(days_left: float) -> dict[str, str]:
    """根据剩余天数分等级."""
    if days_left < 0:
        return {"level": "expired", "emoji": "⚪", "label": "已过期"}
    if days_left < 1:
        return {"level": "critical", "emoji": "🔴", "label": "紧急"}
    if days_left <= 3:
        return {"level": "warning", "emoji": "🟠", "label": "警告"}
    if days_left <= 7:
        return {"level": "notice", "emoji": "🟡", "label": "提示"}
    return {"level": "normal", "emoji": "🟢", "label": "正常"}


class DeadlineMonitor:
    """截止日期监控 — 查询 bidding_documents, 输出预警列表."""

    def check(self, within_days: int = 7, include_expired: bool = True) -> list[dict[str, Any]]:
        """扫描数据库, 返回预警列表.

        Args:
            within_days: 查询多少天内截止 (含已过期)
            include_expired: 是否包含已过期项目
        """
        from src.database.postgresql_client import postgresql_client
        if not postgresql_client.ready:
            logger.warning("PostgreSQL 未连接, DeadlineMonitor 降级")
            return []

        try:
            rows = postgresql_client._run(
                "SELECT id, project_name, purchaser, deadline, source_file, created_at "
                "FROM bidding_documents WHERE deadline IS NOT NULL AND deadline != '' "
                "ORDER BY created_at DESC LIMIT 200"
            )
        except Exception as e:
            logger.error("查询 deadline 失败: %s", e)
            return []

        now = datetime.now()
        alerts = []
        for row in rows:
            dl = parse_deadline(row.get("deadline", ""))
            if dl is None:
                continue
            delta = dl - now
            days_left = delta.total_seconds() / 86400.0

            if not include_expired and days_left < 0:
                continue
            if days_left > within_days:
                continue

            urgency = classify_urgency(days_left)
            alerts.append({
                "doc_id": row["id"],
                "project_name": row.get("project_name") or "(未命名)",
                "purchaser": row.get("purchaser") or "",
                "deadline_raw": row.get("deadline", ""),
                "deadline_parsed": dl.strftime("%Y-%m-%d %H:%M"),
                "days_left": round(days_left, 1),
                "source_file": row.get("source_file", ""),
                **urgency,
            })

        # 排序: 紧急 → 警告 → 提示 → 过期
        urgency_order = {"critical": 0, "warning": 1, "notice": 2, "normal": 3, "expired": 4}
        alerts.sort(key=lambda x: (urgency_order.get(x["level"], 99), x["days_left"]))
        return alerts

    def summary(self) -> dict[str, Any]:
        """汇总统计."""
        alerts = self.check(within_days=30, include_expired=True)
        counts = {"critical": 0, "warning": 0, "notice": 0, "normal": 0, "expired": 0}
        for a in alerts:
            counts[a["level"]] = counts.get(a["level"], 0) + 1
        return {
            "total_tracked": len(alerts),
            "within_7_days": sum(1 for a in alerts if a["days_left"] <= 7 and a["days_left"] >= 0),
            "counts": counts,
            "critical_alerts": [a for a in alerts if a["level"] == "critical"],
        }


monitor = DeadlineMonitor()
