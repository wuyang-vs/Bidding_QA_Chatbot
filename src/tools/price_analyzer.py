"""价格分析与对标 — 历史中标价格分布 + 趋势 + LLM 解读.

数据源:
  - PostgreSQL bidding_procurement (含 winning_amount / subject_matter / winning_time)
  - 如果 PG 未连接, 降级返回空 stats (不崩)

API:
  analyze_price(subject_matter) → {distribution, trend, suggested_price_range, llm_comment}
"""
from __future__ import annotations

import logging
from typing import Any

from src.database.postgresql_client import postgresql_client

logger = logging.getLogger(__name__)


def _format_amount(val: float | int | None) -> str:
    """金额格式化: 原始元 → 万元 (更直观)."""
    if val is None:
        return "-"
    try:
        v = float(val)
    except (TypeError, ValueError):
        return str(val)
    if abs(v) >= 10000:
        return f"{v / 10000:.2f} 万元"
    return f"{v:.2f} 元"


def _normalize_row(row: dict) -> dict:
    """把 PG 返回的 Decimal / datetime 转成 Python 原生类型 (API 序列化友好)."""
    out = {}
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif hasattr(v, "__float__"):
            out[k] = float(v)
        elif hasattr(v, "__int__") and not isinstance(v, int):
            out[k] = int(v)
        else:
            out[k] = v
    return out


def analyze_price(
    subject_matter: str,
    time_range: tuple[str, str] | None = None,
    llm_client=None,
) -> dict[str, Any]:
    """执行价格分析.

    Args:
        subject_matter: 标的物关键词 (如 "空调", "服务器")
        time_range: (start, end) 可选时间过滤, 空则不限
        llm_client: LLM 客户端, 用于解读

    Returns:
        {
            "subject_matter": str,
            "data_source": "postgresql" | "none",
            "distribution": {cnt, avg, p25, p50, p75, p90, min, max, stddev, ...},
            "trend": [{"period": "...", "cnt": N, "avg_amount": X}, ...],
            "suggested_range": {"low": p25, "mid": p50, "high": p75},
            "llm_comment": "LLM 解读文本 (PG 无数据或 LLM 失败时为空)",
        }
    """
    result = {
        "subject_matter": subject_matter,
        "data_source": "none",
        "distribution": {},
        "trend": [],
        "suggested_range": {},
        "llm_comment": "",
        "count_total": 0,
    }

    if not postgresql_client.ready:
        logger.warning("PG 未连接, 价格分析降级")
        result["llm_comment"] = (
            "⚠️ 当前 PostgreSQL 未连接, 无法拉取历史价格数据. "
            "请先部署 PG 并导入 bidding_procurement 数据."
        )
        return result

    # 1. 价格分布
    dist_rows = postgresql_client.query(
        "price_distribution", subject_matter=subject_matter)
    dist = _normalize_row(dist_rows[0]) if dist_rows else {}

    if not dist or dist.get("cnt", 0) == 0:
        result["llm_comment"] = (
            f"⚠️ 数据库中未找到与「{subject_matter}」相关的中标价格记录, 无法进行对标分析."
        )
        return result

    # 2. 时间趋势
    trend_rows = postgresql_client.query(
        "price_trend", subject_matter=subject_matter, granularity="month")
    trend = [_normalize_row(r) for r in trend_rows]

    # 3. TOP 供应商 (价格维度)
    top_suppliers = postgresql_client.query(
        "top_suppliers_by_subject", subject_matter=subject_matter, limit=5)
    top_suppliers = [_normalize_row(r) for r in top_suppliers]

    result.update({
        "data_source": "postgresql",
        "count_total": int(dist.get("cnt", 0)),
        "distribution": dist,
        "trend": trend,
        "top_suppliers": top_suppliers,
        "suggested_range": {
            "low": dist.get("p25"),
            "mid": dist.get("p50"),
            "high": dist.get("p75"),
            "description": (
                f"建议报价区间: {_format_amount(dist.get('p25'))} ~ {_format_amount(dist.get('p75'))}, "
                f"中位价位 {_format_amount(dist.get('p50'))}"
            ),
        },
    })

    # 4. LLM 解读
    if llm_client is None:
        from src.clients.llm_factory import get_llm_client
        llm_client = get_llm_client()

    try:
        result["llm_comment"] = _llm_interpret(subject_matter, dist, trend, llm_client)
    except Exception as e:
        logger.warning("LLM 价格解读失败: %s", e)
        result["llm_comment"] = "（LLM 解读暂时不可用, 以上数据可直接参考）"

    return result


def _llm_interpret(
    subject: str, dist: dict, trend: list[dict], llm_client,
) -> str:
    """把统计数据喂给 LLM, 生成自然语言解读."""
    trend_summary = ""
    for t in trend[:6]:
        period = t.get("period", "")[:7] if isinstance(t.get("period"), str) else t.get("period", "")
        trend_summary += f"  {period}: 中标{t.get('cnt')}次, 均价{t.get('avg_amount')}\n"

    prompt = (
        f"【标的物】{subject}\n\n"
        f"【历史中标统计】\n"
        f"  样本数: {dist.get('cnt', 0)}\n"
        f"  均价: {dist.get('avg_amount')} 元\n"
        f"  P25: {dist.get('p25')} 元\n"
        f"  P50(中位数): {dist.get('p50')} 元\n"
        f"  P75: {dist.get('p75')} 元\n"
        f"  P90: {dist.get('p90')} 元\n"
        f"  最低: {dist.get('min_amount')} 元\n"
        f"  最高: {dist.get('max_amount')} 元\n"
        f"  标准差: {dist.get('stddev_amount')} 元\n\n"
        f"【近期趋势 (最近6期)】\n{trend_summary}\n\n"
        f"请用 200-300 字回答:\n"
        f"1. 价格水平总结 (偏高/偏低/分布是否集中)\n"
        f"2. 合理报价区间建议 (给出具体数字)\n"
        f"3. 价格趋势判断 (上涨/下降/稳定)\n"
        f"4. 投标报价策略建议 (低价中标/性价比/高端溢价)\n\n"
        f"用 Markdown 格式, 不要额外文字."
    )
    return llm_client.chat([
        {"role": "system", "content": "你是招投标价格分析专家, 擅长解读历史数据并给出报价建议."},
        {"role": "user", "content": prompt},
    ], temperature=0.3)
