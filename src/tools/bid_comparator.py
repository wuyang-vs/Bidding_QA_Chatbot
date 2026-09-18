"""多家投标对比 — 抽取多份投标文件的关键字段并并排对比.

核心流程:
  1. 输入: 多份投标文件 (每份含 bidder_name + text)
  2. LLM 从每份投标中抽取结构化关键字段:
     报价/工期/质保期/投标有效期/保证金/资质/关键技术参数/售后服务 等
  3. 输出: 字段 × 投标人 的对比矩阵, 便于横向比较

设计:
  - 每份投标独立抽取, 某份失败不影响其他
  - 字段统一, 缺失填 "未提及"
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# 需抽取的关键字段
_EXTRACT_FIELDS = [
    ("报价", "投标总报价金额 (含币种和单位)"),
    ("工期", "投标工期/交货期 (含单位)"),
    ("质保期", "质保/保修期 (含单位)"),
    ("投标有效期", "投标有效期天数"),
    ("保证金", "投标保证金金额及缴纳方式"),
    ("资质", "投标人具备的主要资质证书"),
    ("关键技术参数", "核心产品/技术参数的响应情况"),
    ("售后服务", "售后服务方案及响应时间"),
    ("付款方式", "对付款方式的响应"),
]


_EXTRACT_SYSTEM = (
    "你是投标文件分析专家. 根据投标文件内容, 提取指定的关键字段.\n"
    "要求:\n"
    "1. 每个字段如实填写原文内容, 找不到填 null\n"
    "2. 报价保留币种和单位 (如 '人民币 820 万元')\n"
    "3. 工期/质保保留单位 (如 '100 个日历天', '3 年')\n"
    "4. 只输出 JSON, 不要任何额外文字或代码块标记"
)


def _truncate(text: str, max_len: int = 6000) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len]


def compare_bids(
    bids: list[dict[str, str]],
    llm_client=None,
) -> dict[str, Any]:
    """对比多份投标文件.

    Args:
        bids: [{"bidder_name": "XX公司", "text": "投标全文"}, ...]
        llm_client: LLM 客户端

    Returns:
        {
            "fields": ["报价","工期",...],
            "bidders": [{"name","values":{field: value}, "raw": {...}}],
            "note": "...",
        }
    """
    if not bids:
        return {"fields": [], "bidders": [], "note": "⚠️ 请提供至少一份投标文件."}

    if llm_client is None:
        from src.clients.llm_factory import get_llm_client
        llm_client = get_llm_client()

    fields_schema = "\n".join(f'  "{k}": "string|null  // {desc}"' for k, desc in _EXTRACT_FIELDS)
    fields_list = [k for k, _ in _EXTRACT_FIELDS]

    bidders: list[dict[str, Any]] = []
    for bid in bids:
        name = (bid.get("bidder_name") or "未命名投标人").strip()
        text = bid.get("text", "")
        if not text.strip():
            bidders.append({"name": name, "values": {f: "未提供" for f in fields_list}})
            continue

        analyze = _truncate(text)
        user_msg = (
            f"【投标文件】\n{analyze}\n\n"
            "请提取以下字段, 输出 JSON:\n"
            "{\n" + fields_schema + "\n}"
        )
        try:
            raw = llm_client.chat([
                {"role": "system", "content": _EXTRACT_SYSTEM},
                {"role": "user", "content": user_msg},
            ], temperature=0.1)
            cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
            cleaned = re.sub(r"\s*```$", "", cleaned)
            parsed = json.loads(cleaned)
            values = {f: str(parsed.get(f) or "未提及") for f in fields_list}
        except Exception as e:
            logger.warning("投标字段抽取失败 (%s): %s", name, e)
            values = {f: "抽取失败" for f in fields_list}

        bidders.append({"name": name, "values": values})

    return {
        "fields": fields_list,
        "bidders": bidders,
    }
