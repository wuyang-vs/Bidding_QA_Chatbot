"""意图前置检测: 超范围拒答 + 模糊问题引导补充"""
import re

# 招投标领域关键词（命中任一 = 领域内）
DOMAIN_KEYWORDS = [
    "招标", "投标", "中标", "废标", "开标", "评标", "定标", "投标保证金",
    "履约保证金", "采购", "竞争性谈判", "竞争性磋商", "询价", "单一来源",
    "公开招标", "邀请招标", "资质", "资格预审", "联合体", "分包", "转包",
    "不可抗力", "质疑", "投诉", "索赔", "工期", "质量保证金", "验收",
    "标段", "标包", "控制价", "最高限价", "拦标价", "标底",
    "采购人", "招标人", "投标人", "中标人", "招标代理",
    "招投标", "招标文件", "投标文件", "中标通知书",
    "预算", "金额", "决算", "结算", "合同", "供应商", "承包商",
    "建设单位", "施工单位", "竣工", "审计", "评审", "批复",
    "采购单位", "代理机构", "采购项目", "改造项目", "建设工程",
    "资格要求", "技术参数", "交货期", "保修期", "质保金",
]

# 模糊问题判定: 过短 + 无上下文 + 含指代/疑问词但缺实体
_VAGUE_PRONOUN = re.compile(r"(这个|那个|它|他|她|这|那|该|此|怎么|如何|什么|哪|几|多少|为什么|是不是|有没有)")
_MIN_QUESTION_LEN = 6  # 字符数


def is_out_of_scope(question: str, history: list | None = None) -> bool:
    """判断问题是否超出招投标领域.
from __future__ import annotations
    
    规则:
    - 无领域关键词
    - 且无历史上下文承接（history 为空或最后一条不是同领域）
    """
    if not question or not question.strip():
        return True
    has_domain = any(kw in question for kw in DOMAIN_KEYWORDS)
    if has_domain:
        return False
    # 历史上下文: 如果上一轮用户消息含领域关键词, 视为追问
    if history:
        for msg in reversed(history):
            if msg.get("role") == "user":
                if any(kw in msg.get("content", "") for kw in DOMAIN_KEYWORDS):
                    return False
                break  # 只看最近一条用户消息
    return True


def is_vague_question(question: str, history: list | None = None) -> bool:
    """判断问题是否信息不足/表述模糊.
    
    规则:
    - 问题过短 (< 6 字符) 且不含领域关键词
    - 含指代但无历史上下文支撑
    - 纯疑问词无实体 (如 "怎么办" "为什么")
    """
    if not question or not question.strip():
        return True
    q = question.strip()
    has_domain = any(kw in q for kw in DOMAIN_KEYWORDS)
    # 过短 (但含领域关键词不算)
    if len(q) < _MIN_QUESTION_LEN and not has_domain:
        return True
    # 含指代但无上下文
    has_pronoun = bool(_VAGUE_PRONOUN.search(q))
    if has_pronoun and not history:
        # 有指代 + 无历史 = 模糊 (但如果含领域关键词则不算)
        if not any(kw in q for kw in DOMAIN_KEYWORDS):
            return True
    # 纯疑问词无实体: 去掉疑问词后剩余 < 2 字符
    stripped = _VAGUE_PRONOUN.sub("", q).strip()
    if len(stripped) < 2 and not any(kw in q for kw in DOMAIN_KEYWORDS):
        return True
    return False


def scope_rejection_message(question: str) -> str:
    """超范围拒答模板"""
    return (
        f"抱歉，「{question[:30]}」不属于招投标/政府采购领域的问题，"
        "我是招投标智能问答助手，只能回答招投标相关的法规、流程、数据查询等问题。"
        "欢迎向我提问招投标相关内容。"
    )


def vague_guidance_message(question: str) -> str:
    """模糊问题引导模板"""
    return (
        f"您的问题「{question[:30]}」信息不太充分，"
        "能否补充一下具体场景或关键信息？比如涉及哪个项目、哪个环节、有什么具体疑问？"
    )
