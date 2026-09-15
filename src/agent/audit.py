"""回答审计: 引用溯源 + 真实性校验 (Hallucination Detection)"""
import logging
import re
from collections import Counter

logger = logging.getLogger(__name__)

# 匹配 [资料1] [资料1,2] [来源1] 等引用标记
_CITE_RE = re.compile(r"\[资料\s*([\d,\s]+)\]")
_SOURCE_ALIASES = {"资料", "来源", "文档", "参考", "ref", "source"}


def _parse_citations(text: str) -> list[dict]:
    """从 LLM 输出中提取引用标记, 映射到 sources 索引.
    
    返回: [{"raw": "[资料1]", "indices": [0], "count": 3}, ...]
    """
    results = []
    for m in _CITE_RE.finditer(text):
        raw = m.group(0)
        indices = []
        for part in m.group(1).split(","):
            part = part.strip()
            if part.isdigit():
                idx = int(part) - 1  # [资料1] → sources[0]
                if idx >= 0:
                    indices.append(idx)
        if indices:
            results.append({"raw": raw, "indices": indices, "count": len(indices)})
    return results


def _extract_sentences(text: str) -> list[str]:
    """中文分句: 句号/问号/感叹号/分号"""
    parts = re.split(r"[。！？；\n]+", text)
    return [s.strip() for s in parts if s.strip()]


def _tokens(text: str) -> set[str]:
    """简单分词: 2-4 字符滑动窗口, 足够覆盖招投标术语"""
    text = re.sub(r"[\s\W]+", "", text)
    if len(text) < 2:
        return {text}
    tokens = set()
    for n in (2, 3, 4):
        for i in range(len(text) - n + 1):
            tokens.add(text[i : i + n])
    return tokens


def audit_answer(answer: str, sources: list[dict]) -> dict:
    """一站式审计: 引用解析 + 真实性校验.
    
    返回 dict:
      citations      - 引用解析结果 [{raw, indices, count}]
      cited_source_indices - 被引用的 sources 索引集合
      faithfulness_score   - 句级真实性均分 [0, 1]
      sentence_audits      - 每句审计结果 [{sentence, overlap, faithful}]
      total_sentences      - 句子数
      hallucinated_count   - 疑似编造句子数
    """
    result = {
        "citations": [],
        "cited_source_indices": set(),
        "faithfulness_score": 0.0,
        "sentence_audits": [],
        "total_sentences": 0,
        "hallucinated_count": 0,
    }

    if not answer or not sources:
        return result

    # ---- 引用解析 ----
    result["citations"] = _parse_citations(answer)
    for c in result["citations"]:
        result["cited_source_indices"].update(c["indices"])

    # ---- 真实性校验 ----
    # 收集所有 source tokens
    source_tokens = set()
    for s in sources:
        source_tokens |= _tokens(s.get("question", "") + s.get("answer", ""))

    sentences = _extract_sentences(answer)
    result["total_sentences"] = len(sentences)

    overlap_scores = []
    for sent in sentences:
        sent_tokens = _tokens(sent)
        if not sent_tokens:
            continue
        overlap = len(sent_tokens & source_tokens) / len(sent_tokens)
        faithful = overlap >= 0.15  # 15% token 重叠即认为有依据
        overlap_scores.append(overlap)
        if not faithful:
            result["hallucinated_count"] += 1
        result["sentence_audits"].append({
            "sentence": sent[:60] + ("..." if len(sent) > 60 else ""),
            "overlap": round(overlap, 3),
            "faithful": faithful,
        })

    result["faithfulness_score"] = round(
        sum(overlap_scores) / len(overlap_scores), 3) if overlap_scores else 0.0

    # cited_source_indices 转 list 方便 JSON 序列化
    result["cited_source_indices"] = sorted(result["cited_source_indices"])

    return result


def build_citation_prompt_suffix(sources: list[dict]) -> str:
    """构建引用提示, 注入最终生成的 system 消息."""
    if not sources:
        return ""
    lines = ["\n资料编号对应如下（回答时请用 [资料N] 标注来源）:"]
    for i, s in enumerate(sources, 1):
        q = s.get("question", "")[:40]
        a = s.get("answer", "")[:40]
        lines.append(f"  [资料{i}] 问: {q}...  答: {a}...")
    lines.append("回答中的每个关键断言都应标注来源，如「招标分为公开招标和邀请招标[资料1]」。")
    return "\n".join(lines)
