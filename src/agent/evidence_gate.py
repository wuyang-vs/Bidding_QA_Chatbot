from __future__ import annotations
"""服务端"无引用不生成"硬闸门 (有库才答, 无库不答)。

设计:
- 知识类问题必须有工具返回的权威证据(向量分片/联网来源/结构化库实质数据),
  否则禁止 LLM 自由生成, 直接返回固定话术 NO_EVIDENCE_NOTICE。
- LLM 当轮"忘记"调工具就直接作答(M2-01 波动根因)时, 服务端强制其补一次检索,
  而不是放行答案; 强制后仍无证据则硬拒。
- 纯寒暄/能力询问(is_chitchat)不需要证据, 放行。

本模块只放纯函数, 不导入重依赖, 便于离线单测。
"""
import re

# 硬闸门固定话术: 不随 LLM 波动, 不包含任何业务事实
NO_EVIDENCE_NOTICE = (
    "抱歉，我未在本地权威知识库中检索到与您问题直接相关的资料。"
    "为避免给出无依据或错误的信息，我不能凭空作答。\n\n"
    "您可以：\n"
    "1. 补充项目全称、招标文件名称或条款关键词后再提问；\n"
    "2. 换用更具体的表述（如具体时间、金额、资质名称）；\n"
    "3. 若确认该资料应在知识库中，请联系管理员核实文件是否已上传并对您的身份可见。"
)

# 纯寒暄/系统能力询问: 整句匹配才放行, 避免误放行"投标保证金怎么退"这类知识问题
_CHITCHAT_RE = re.compile(
    r"^\s*(你好|您好|嗨|哈喽|hi|hello|hey|在吗|在不在|早上好|上午好|中午好|下午好|晚上好|"
    r"谢谢|感谢|多谢|辛苦了|好的|嗯|收到|明白|知道了|ok|okay|"
    r"再见|拜拜|bye|goodbye|"
    r"你是谁|你叫什么|你是干嘛的|你是做什么的|你能做什么|你会什么|你有什么功能|"
    r"功能介绍|使用帮助|帮助|怎么用|如何使用)\s*"
    r"[，。！!？?~～.]*\s*$",
    re.IGNORECASE,
)

# 工具返回"空/失败/越权"的文本标记
_EMPTY_MARKERS = ("未找到", "未检索", "未查询", "未连接", "未返回", "查询失败",
                  "没有相关", "无相关", "执行失败", "执行超时", "参数解析失败",
                  "未知工具", "无权访问", "无权")

# 结构化库工具: sources 恒为空, 证据看文本是否为实质数据
_STRUCTURED_TOOLS = {"search_knowledge_graph", "search_postgresql"}
# 有依据的动作类工具: 返回内容直接基于本地招标文件生成/列举
_GROUNDED_ACTION_TOOLS = {"list_bid_documents", "generate_bid_draft"}
# 可作为权威证据的全部工具
_EVIDENCE_TOOLS = _STRUCTURED_TOOLS | _GROUNDED_ACTION_TOOLS | {
    "search_bidding_knowledge", "search_web", "search_exa"}

# RAG 检索均分低于该值视为"仅有低相关噪声", 不算证据
# (实测相关问题 0.9+, 跨领域无关问题 0.01 以下, 间隔极大)
_RAG_MIN_AVG_SCORE = 0.3

# 招投标通用词: 从问题中剔除后再提取特征 2-gram,
# 避免"投标保证金比例"这类通用 FAQ 文本为任意具体项目问题"冒充证据"
_GENERIC_WORDS = (
    "投标", "招标", "采购", "保证金", "开标", "评标", "中标", "项目", "工程",
    "截止", "时间", "金额", "比例", "规定", "条款", "要求", "资格", "技术",
    "商务", "报价", "合同", "供应商", "采购人", "缴纳", "文件", "是什么",
    "怎么", "如何", "什么", "是否", "可以", "需要", "请问", "一下", "我们",
    "你们", "分别", "目前", "现在", "以及", "相关", "内容", "信息", "情况",
    "方式", "标准", "条件", "流程", "办法", "规则", "说明",
)


def _question_signature(question: str) -> set[str]:
    """提取问题中的特征 2-gram (剔除招投标通用词/标点/数字/英文)。

    通用概念问题(如"投标保证金怎么退")剔除后为空集合 → 不做项目级覆盖约束。
    """
    s = question or ""
    for w in _GENERIC_WORDS:
        s = s.replace(w, "")
    grams = set()
    for i in range(len(s) - 1):
        pair = s[i:i + 2]
        if all("一" <= c <= "鿿" for c in pair):
            grams.add(pair)
    return grams


def evidence_covers_question(question: str, evidence_texts: list[str] | None) -> bool:
    """证据文本必须至少命中一个问题特征词。

    evidence_texts=None 表示调用方未提供(不做覆盖约束, 信任证据布尔值);
    空列表表示确实没有证据文本(严格按无覆盖处理)。
    """
    if evidence_texts is None:
        return True
    grams = _question_signature(question)
    if not grams:
        return True
    blob = "\n".join(evidence_texts)
    return any(g in blob for g in grams)


def is_chitchat(question: str) -> bool:
    """纯寒暄/询问助手能力 → 不需要证据。整句匹配, 知识问题中含"帮助"等词不影响。"""
    if not question:
        return False
    return bool(_CHITCHAT_RE.match(question.strip()))


def tool_provided_evidence(tool_name: str, sources: list | None,
                           text: str | None) -> bool:
    """判断单次工具调用是否返回了可作为答案依据的实质证据。"""
    if tool_name not in _EVIDENCE_TOOLS:
        return False
    if sources:
        # RAG: 分数全部很低 = 跨领域噪声召回, 不构成证据
        if tool_name == "search_bidding_knowledge":
            scores = [float(s.get("score") or 0) for s in sources]
            if not scores or sum(scores) / len(scores) < _RAG_MIN_AVG_SCORE:
                return False
        return True
    if tool_name in _STRUCTURED_TOOLS | _GROUNDED_ACTION_TOOLS:
        t = (text or "").strip()
        if not t:
            return False
        return not any(m in t for m in _EMPTY_MARKERS)
    return False


def gate_decision(question: str,
                  tool_attempted: bool,
                  evidence_found: bool,
                  forced_retry_used: bool,
                  evidence_texts: list[str] | None = None) -> str:
    """闸门判定纯函数。

    返回:
      "answer"           允许生成(寒暄 或 已有权威证据且覆盖问题特征词)
      "force_retrieval"  LLM 未调任何工具就作答 → 强制补检索(仅一次)
      "refuse"           无证据/证据不覆盖问题主体 → 返回固定话术, 不进 LLM
    """
    if is_chitchat(question):
        return "answer"
    if evidence_found and evidence_covers_question(question, evidence_texts):
        return "answer"
    if not tool_attempted and not forced_retry_used:
        return "force_retrieval"
    return "refuse"
