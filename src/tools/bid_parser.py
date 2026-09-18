"""投标文件解析器 — 单份投标文本 → 投标人维度结构化 JSON.

三个维度 (对应专项工具清单):
  - 商务响应: 报价 / 工期 / 质保期 / 投标有效期 / 保证金 / 付款方式
  - 技术方案: 方案概述 / 关键技术参数响应 / 售后服务 / 项目团队
  - 资格业绩: 资质证书 / 同类业绩

设计:
  - LLM 按固定 schema 抽取; JSON 解析失败降级, 不抛异常
  - 关键字段同时写入 fields (9 项), 供多家对比复用, 避免两套 prompt
"""
from __future__ import annotations

import json as _json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# 多家对比复用的扁平字段 (保持与 bid_comparator 历史契约一致)
COMPARE_FIELDS: list[tuple[str, str]] = [
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

_PARSE_SYSTEM = (
    "你是投标文件分析专家. 根据投标文件内容提取结构化信息.\n"
    "要求:\n"
    "1. 每个字段如实填写原文内容, 找不到填 null, 列表找不到填空数组\n"
    "2. 报价保留币种和单位 (如 '人民币 820 万元')\n"
    "3. 工期/质保保留单位 (如 '100 个日历天', '3 年')\n"
    "4. 技术方案概述用 100-200 字归纳核心技术路线, 不要照抄整段\n"
    "5. 只输出 JSON, 不要任何额外文字或代码块标记"
)

_PARSE_SCHEMA = """{
  "bidder_name": "string|null  // 投标人/投标单位全称",
  "project_name": "string|null  // 所投项目名称",
  "commercial": {
    "报价": "string|null",
    "工期": "string|null",
    "质保期": "string|null",
    "投标有效期": "string|null",
    "保证金": "string|null",
    "付款方式": "string|null"
  },
  "technical": {
    "技术方案概述": "string|null  // 核心技术路线/实施方案归纳",
    "关键技术参数": "string|null  // 对招标关键技术参数的响应",
    "售后服务": "string|null",
    "项目团队": "string|null  // 项目经理/主要人员配置"
  },
  "qualifications": ["资质证书/许可名称"],
  "performances": ["近年同类项目业绩 (项目名+金额, 如有)"],
  "fields": {
    "报价": "string|null", "工期": "string|null", "质保期": "string|null",
    "投标有效期": "string|null", "保证金": "string|null",
    "资质": "string|null  // 主要资质证书合并文本",
    "关键技术参数": "string|null", "售后服务": "string|null",
    "付款方式": "string|null"
  }
}"""


def _truncate(text: str, max_len: int = 8000) -> str:
    return text if len(text) <= max_len else text[:max_len]


def _empty_result(text: str, bidder_name: str = "") -> dict[str, Any]:
    return {
        "bidder_name": bidder_name, "project_name": None,
        "commercial": {k: None for k in
                       ("报价", "工期", "质保期", "投标有效期", "保证金", "付款方式")},
        "technical": {k: None for k in
                      ("技术方案概述", "关键技术参数", "售后服务", "项目团队")},
        "qualifications": [], "performances": [],
        "fields": {k: None for k, _ in COMPARE_FIELDS},
        "parse_status": "failed",
        "text_length": len(text or ""),
    }


def _normalize(parsed: dict[str, Any], text: str, bidder_name: str) -> dict[str, Any]:
    commercial = parsed.get("commercial") or {}
    technical = parsed.get("technical") or {}
    fields = parsed.get("fields") or {}

    # fields 缺省时从分维度回填, 保证 compare 字段齐全
    if not fields.get("报价"):
        fields["报价"] = commercial.get("报价")
    if not fields.get("关键技术参数"):
        fields["关键技术参数"] = technical.get("关键技术参数")
    if not fields.get("售后服务"):
        fields["售后服务"] = technical.get("售后服务")
    if not fields.get("资质"):
        quals = parsed.get("qualifications") or []
        if isinstance(quals, list) and quals:
            fields["资质"] = "; ".join(str(q) for q in quals)
    for k, _ in COMPARE_FIELDS:
        fields.setdefault(k, None)

    qs = parsed.get("qualifications") or []
    ps = parsed.get("performances") or []
    return {
        "bidder_name": parsed.get("bidder_name") or bidder_name or None,
        "project_name": parsed.get("project_name"),
        "commercial": {
            "报价": commercial.get("报价"),
            "工期": commercial.get("工期"),
            "质保期": commercial.get("质保期"),
            "投标有效期": commercial.get("投标有效期"),
            "保证金": commercial.get("保证金"),
            "付款方式": commercial.get("付款方式"),
        },
        "technical": {
            "技术方案概述": technical.get("技术方案概述"),
            "关键技术参数": technical.get("关键技术参数"),
            "售后服务": technical.get("售后服务"),
            "项目团队": technical.get("项目团队"),
        },
        "qualifications": [str(q) for q in qs] if isinstance(qs, list) else [],
        "performances": [str(p) for p in ps] if isinstance(ps, list) else [],
        "fields": {k: fields.get(k) for k, _ in COMPARE_FIELDS},
        "parse_status": "ok",
        "text_length": len(text or ""),
    }


def parse_bid(
    text: str,
    bidder_name: str = "",
    llm_client=None,
) -> dict[str, Any]:
    """解析单份投标文件.

    Args:
        text: 投标文件全文
        bidder_name: 外部已知的投标人名称 (文件名等), LLM 未抽到则回填
        llm_client: LLM 客户端

    Returns:
        投标人维度结构化数据 (commercial/technical/qualifications/performances/fields)
    """
    if not (text or "").strip():
        r = _empty_result(text, bidder_name)
        r["parse_status"] = "empty"
        return r

    if llm_client is None:
        from src.clients.llm_factory import get_llm_client
        llm_client = get_llm_client()

    user_msg = (
        f"【投标文件】\n{_truncate(text)}\n\n"
        f"参考投标人名称: {bidder_name or '(未提供, 请从正文提取)'}\n\n"
        "请提取信息, 输出 JSON:\n" + _PARSE_SCHEMA
    )
    try:
        raw = llm_client.chat([
            {"role": "system", "content": _PARSE_SYSTEM},
            {"role": "user", "content": user_msg},
        ], temperature=0.1)
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)
        parsed = _json.loads(cleaned)
        return _normalize(parsed, text, bidder_name)
    except Exception as e:
        logger.warning("投标文件解析失败: %s", e)
        result = _empty_result(text, bidder_name)
        result["error"] = str(e)[:200]
        return result
