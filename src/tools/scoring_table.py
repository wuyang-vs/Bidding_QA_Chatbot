"""评分辅助表生成 — 根据招标文件评分办法, 生成结构化打分表模板.

核心流程:
  1. 输入: 招标文件评分办法文本 (或 db_id 自动取 scoring_criteria)
  2. LLM 解析评分项: 评分维度 / 权重 / 满分 / 评分标准
  3. 输出: 结构化评分表 (可直接填入各投标人得分)

设计:
  - LLM 失败时按关键词降级 (价格/技术/商务/业绩等常见维度)
  - 权重和为 100, 否则提示异常
  - 前端可据此生成多人打分表并自动计算加权总分
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


_PARSE_SYSTEM = (
    "你是招投标评标专家. 根据招标文件评分办法, 解析出所有评分项.\n"
    "要求:\n"
    "1. 每个评分项包含: dimension(维度名称), weight(权重分值), max_score(该项满分), scoring_rule(评分标准简述)\n"
    "2. weight 和 max_score 通常相等 (权重即满分); 若不相等请如实填写\n"
    "3. 若有子项请拆成独立条目\n"
    "4. 只输出 JSON, 不要任何额外文字或代码块标记"
)


# 常见评分维度 (降级用)
_KNOWN_DIMENSIONS = [
    ("价格分", ["价格分", "报价分", "价格", "投标报价"]),
    ("技术分", ["技术分", "技术方案", "技术参数", "技术响应"]),
    ("商务分", ["商务分", "商务条款", "商务响应"]),
    ("业绩分", ["业绩分", "类似项目业绩", "企业业绩"]),
    ("资信分", ["资信", "资质", "信誉", "认证"]),
    ("服务分", ["服务", "售后", "运维", "培训"]),
]


def generate_scoring_table(
    scoring_text: str | dict,
    llm_client=None,
) -> dict[str, Any]:
    """根据评分办法文本生成评分辅助表.

    Args:
        scoring_text: 评分办法原文, 或 document_parser dict (自动取 scoring_criteria)
        llm_client: LLM 客户端

    Returns:
        {
            "total_score": 100,
            "items": [{"id","dimension","weight","max_score","scoring_rule"}],
            "note": "..." (可选),
        }
    """
    if isinstance(scoring_text, dict):
        scoring_text = scoring_text.get("scoring_criteria") or scoring_text.get("raw_text") or scoring_text.get("raw_text_preview", "")

    text = str(scoring_text or "").strip()
    if not text:
        return {"total_score": 0, "items": [], "note": "⚠️ 未找到评分办法内容, 请确认招标文件包含评分办法章节."}

    if llm_client is None:
        from src.clients.llm_factory import get_llm_client
        llm_client = get_llm_client()

    analyze = text[:6000]

    user_msg = (
        f"【评分办法】\n{analyze}\n\n"
        "请解析评分项, 输出 JSON:\n"
        '{"items": [\n'
        '  {"dimension": "评分维度名称",\n'
        '   "weight": 权重分值(数字),\n'
        '   "max_score": 该项满分(数字),\n'
        '   "scoring_rule": "评分标准简述(一句话)"}\n'
        "]}"
    )

    try:
        raw = llm_client.chat([
            {"role": "system", "content": _PARSE_SYSTEM},
            {"role": "user", "content": user_msg},
        ], temperature=0.1)
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)
        parsed = json.loads(cleaned)
        items_raw = parsed.get("items", [])
        degraded = False
    except Exception as e:
        logger.warning("评分办法解析 LLM 失败, 降级: %s", e)
        items_raw = _fallback_parse(text)
        degraded = True

    items: list[dict[str, Any]] = []
    total = 0
    for i, it in enumerate(items_raw, start=1):
        dim = str(it.get("dimension", "")).strip()
        if not dim:
            continue
        try:
            weight = float(it.get("weight", 0) or 0)
        except (TypeError, ValueError):
            weight = 0
        try:
            max_score = float(it.get("max_score", weight) or weight)
        except (TypeError, ValueError):
            max_score = weight
        total += weight
        items.append({
            "id": f"S{i}",
            "dimension": dim,
            "weight": weight,
            "max_score": max_score,
            "scoring_rule": str(it.get("scoring_rule", "")).strip(),
        })

    result: dict[str, Any] = {
        "total_score": round(total, 2),
        "items": items,
    }
    if degraded:
        result["note"] = "⚠️ LLM 解析失败, 以下为关键词降级结果, 可能不完整, 建议稍后重试"
    if items and abs(total - 100) > 0.5:
        result["note"] = (result.get("note", "") +
                          f"\n⚠️ 权重合计 {total} 分, 与 100 分不符, 请核对评分办法原文.").strip()
    return result


def _fallback_parse(text: str) -> list[dict[str, Any]]:
    """LLM 失败时按常见维度关键词+数字提取."""
    items: list[dict[str, Any]] = []
    for dim, kws in _KNOWN_DIMENSIONS:
        for kw in kws:
            idx = text.find(kw)
            if idx < 0:
                continue
            # 在关键词附近找数字
            snippet = text[max(0, idx - 5):idx + 30]
            m = re.search(r"(\d+(?:\.\d+)?)\s*分", snippet)
            score = float(m.group(1)) if m else 0
            if score > 0:
                items.append({
                    "dimension": dim,
                    "weight": score,
                    "max_score": score,
                    "scoring_rule": f"{kw}评分",
                })
            break
    return items
