from __future__ import annotations
"""来源多样性: 限制同源文档数量, 避免单一来源垄断 top_k"""
import logging
from collections import Counter

logger = logging.getLogger(__name__)


def apply_source_diversity(docs: list[dict], max_per_source: int = 2,
                           source_key: str = "source_file") -> list[dict]:
    """对 rerank 后的 docs 应用来源多样性约束.
    
    策略: 贪心遍历 rerank 排序后的 docs, 每个来源最多保留 max_per_source 条,
    超出的跳过, 用后续不同来源的文档补充.
    
    Args:
        docs: rerank 排序后的文档列表 (含 score)
        max_per_source: 每个来源最多保留条数
        source_key: 用于分组的 payload 字段
    
    Returns:
        过滤后的文档列表 (保持 score 降序, 长度 ≤ 原长度)
    """
    if not docs or max_per_source <= 0:
        return docs

    source_counts: Counter[str] = Counter()
    diversified = []
    skipped = 0

    for d in docs:
        source = d.get(source_key) or d.get("section_title") or "__no_source__"
        if source_counts[source] < max_per_source:
            diversified.append(d)
            source_counts[source] += 1
        else:
            skipped += 1

    if skipped > 0:
        logger.info("来源多样性: 跳过 %d 条同源文档, 保留 %d 条", skipped, len(diversified))

    return diversified
