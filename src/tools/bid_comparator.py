"""多家投标对比 — 逐份结构化抽取后形成字段 × 投标人对比矩阵.

核心流程:
  1. 输入: 多份投标文件 (每份含 bidder_name + text)
  2. 复用 bid_parser.parse_bid 抽取商务/技术/资格字段
  3. 输出: 字段 × 投标人 的对比矩阵, 便于横向比较

设计:
  - 每份投标独立解析, 某份失败不影响其他
  - 字段统一, 缺失填 "未提及"
"""
from __future__ import annotations

import logging
from typing import Any

from src.tools.bid_parser import COMPARE_FIELDS, parse_bid

logger = logging.getLogger(__name__)


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
            "bidders": [{"name","values":{field: value}}],
            "parsed": [...完整 parse_bid 结果...],
        }
    """
    fields_list = [k for k, _ in COMPARE_FIELDS]
    if not bids:
        return {"fields": fields_list, "bidders": [], "parsed": [],
                "note": "⚠️ 请提供至少一份投标文件."}

    if llm_client is None:
        from src.clients.llm_factory import get_llm_client
        llm_client = get_llm_client()

    bidders: list[dict[str, Any]] = []
    parsed_all: list[dict[str, Any]] = []
    for bid in bids:
        name = (bid.get("bidder_name") or "未命名投标人").strip()
        text = bid.get("text", "")
        if not (text or "").strip():
            bidders.append({"name": name,
                            "values": {f: "未提供" for f in fields_list}})
            continue

        parsed = parse_bid(text, bidder_name=name, llm_client=llm_client)
        # parse_bid 在 name 已给时回填, 以外部名为准保证矩阵对齐
        parsed["bidder_name"] = name
        parsed_all.append(parsed)

        if parsed.get("parse_status") != "ok":
            values = {f: "解析失败" for f in fields_list}
        else:
            values = {f: (str(parsed["fields"].get(f)) if parsed["fields"].get(f)
                          is not None else "未提及") for f in fields_list}
        bidders.append({"name": name, "values": values})

    return {"fields": fields_list, "bidders": bidders, "parsed": parsed_all}
