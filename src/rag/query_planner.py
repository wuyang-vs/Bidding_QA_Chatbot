"""Query 规划: 受控变体生成 + 会话补全"""
import logging
import re

logger = logging.getLogger(__name__)

# 招投标领域的常见缩写/同义词映射, 用于生成受控变体
_SYNONYM_MAP = [
    ("招标", ["招标", "招投标", "公开招标", "邀请招标"]),
    ("投标", ["投标", "竞标", "响应招标"]),
    ("采购", ["采购", "政府采购", "集中采购"]),
    ("中标", ["中标", "成交", "定标"]),
    ("废标", ["废标", "否决投标", "无效投标"]),
    ("保证金", ["保证金", "投标保证金", "履约保证金", "担保金"]),
    ("评标", ["评标", "评审", "打分"]),
    ("限额", ["限额", "金额限制", "资金门槛"]),
    ("公告", ["公告", "公示", "通知"]),
    ("合同", ["合同", "协议", "契约"]),
]


def _generate_variants_basic(question: str, max_variants: int = 3) -> list[str]:
    """基于同义词表生成受控查询变体.
    
    规则:
    - 只替换已知同义词表中的词
    - 最多生成 max_variants 个变体
    - 保留原查询
    """
    variants = [question]
    for term, syns in _SYNONYM_MAP:
        if term not in question:
            continue
        for syn in syns:
            if syn == term:
                continue
            variant = question.replace(term, syn)
            if variant not in variants:
                variants.append(variant)
            if len(variants) >= max_variants + 1:  # +1 for original
                return variants
    return variants


def _resolve_references(question: str, history: list[dict]) -> str:
    """会话补全: 用最近一轮用户消息消解指代.
    
    例如 history=[{role:"user", content:"招标流程是什么"}, ...], question="那投标呢?"
    → 补全为 "投标流程是什么"
    """
    if not history:
        return question

    # 取最近 3 条用户消息
    recent_user = [m for m in history if m.get("role") == "user"][-3:]
    if not recent_user:
        return question

    last_question = recent_user[-1].get("content", "")

    # 指代消解规则: "那...呢" / "那...呢?" / "...怎么样"
    patterns = [
        (r"^那(.+?)呢[?？]?$", lambda m: f"{m.group(1)}{_extract_tail(last_question)}"),
        (r"^那(.+?)(怎么样|如何)[?？]?$", lambda m: f"{m.group(1)}{_extract_tail(last_question)}"),
        (r"^(.+?)(怎么样|如何)[?？]?$", lambda m: f"{m.group(1)}{_extract_tail(last_question)}"),
    ]
    for pat, builder in patterns:
        m = re.match(pat, question.strip())
        if m:
            resolved = builder(m)
            logger.info("指代消解: '%s' → '%s'", question, resolved)
            return resolved

    return question


def _extract_tail(last_q: str) -> str:
    """从上次问题中提取尾部修饰词 (如 '流程是什么' → '流程是什么')."""
    # 简单取最后 4-8 个字符作为上下文补充
    tail = last_q[-8:] if len(last_q) > 8 else last_q
    # 去掉前面的疑问词
    tail = re.sub(r"^(什么|如何|为什么|那|请|请问)", "", tail).strip()
    return tail


def plan_query(question: str, history: list[dict] | None = None,
               max_variants: int = 3) -> list[str]:
    """一站式 Query 规划: 会话补全 + 受控变体.
    
    返回: [原始/补全后查询, 变体1, 变体2, ...] (去重, 不超过 max_variants+1)
    """
    resolved = _resolve_references(question, history or [])
    variants = _generate_variants_basic(resolved, max_variants)
    return variants
