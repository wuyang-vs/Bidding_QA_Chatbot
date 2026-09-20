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


# ============ 三业务线显式意图分类 (招投标/企业/法规) ============
# 设计原则: 确定性规则评分, 离线可测; 仅在"显著单域"时裁剪工具,
# 跨域(分差小)/弱信号/企业线(chat 无专属工具) 一律保守回退全集, 宁可多给工具不可误裁.

# (关键词, 权重); 强信号 2 分, 弱信号 1 分
_REGULATION_KW: list[tuple[str, int]] = [
    # 强信号: 法律法规/救济渠道/合规
    ("招标投标法", 2), ("政府采购法", 2), ("实施条例", 2), ("管理条例", 2),
    ("管理办法", 2), ("法律", 2), ("法规", 2), ("条例", 2), ("规章", 2),
    ("异议", 2), ("质疑", 2), ("投诉", 2), ("举报", 2), ("行政复议", 2),
    ("行政诉讼", 2), ("起诉", 2), ("违法", 2), ("违规", 2), ("合规", 2),
    ("处罚", 2), ("法律责任", 2), ("法律依据", 2), ("合法性", 2),
    ("示范文本", 2), ("范本", 2),
    # 弱信号: 通用规范词, 单独出现不足以定域
    ("法定", 1), ("条款", 1), ("规定", 1), ("期限", 1), ("时限", 1),
    ("办法", 1), ("允许吗", 1), ("合法吗", 1),
]

_TENDER_KW: list[tuple[str, int]] = [
    # 强信号: 标书制作/开评标动作/检测
    ("标书", 2), ("投标文件", 2), ("招标文件", 2), ("投标函", 2),
    ("技术方案", 2), ("商务标", 2), ("技术标", 2), ("评分办法", 2),
    ("评标办法", 2), ("唱标", 2), ("在线解密", 2), ("签章", 2),
    ("加密上传", 2), ("章节", 2), ("整本", 2), ("合稿", 2),
    ("对照表", 2), ("响应表", 2), ("围标", 2), ("串标", 2), ("陪标", 2),
    ("异常预警", 2), ("检测报告", 2), ("帮我写", 2), ("写一份", 2),
    ("废标", 2), ("流标", 2),
    # 弱信号: 招投标事实/通用环节词
    ("开标", 1), ("评标", 1), ("中标", 1), ("截标", 1), ("递交", 1),
    ("报名", 1), ("澄清", 1), ("控制价", 1), ("最高限价", 1), ("拦标价", 1),
    ("报价", 1), ("得分", 1), ("扣分", 1), ("项目", 1), ("采购人", 1),
    ("招标人", 1), ("代理机构", 1), ("中标人", 1), ("中标金额", 1),
    ("预算", 1), ("保证金", 1), ("截止时间", 1), ("开标时间", 1),
    ("工期", 1), ("标段", 1), ("工程", 1), ("采购", 1),
    ("资格预审", 1), ("资格审查", 1), ("资质要求", 1),
]

_ENTERPRISE_KW: list[tuple[str, int]] = [
    # 强信号: 企业主体/资质证照/企业资料
    ("营业执照", 2), ("资质证书", 2), ("安全生产许可证", 2), ("企业资料", 2),
    ("公司档案", 2), ("证照", 2), ("法定代表人", 2), ("法人代表", 2),
    ("银行账户", 2), ("开户行", 2), ("企业信用", 2), ("信用中国", 2),
    ("资质等级", 2), ("我们公司", 2), ("我司", 2), ("企业信息", 2),
    # 弱信号
    ("公司", 1), ("企业", 1), ("供应商", 1), ("厂家", 1), ("厂商", 1),
    ("承包商", 1), ("企业资质", 1), ("入库", 1), ("业绩", 1),
]

_DOMAIN_KEYWORDS = {
    "regulation": _REGULATION_KW,
    "tender": _TENDER_KW,
    "enterprise": _ENTERPRISE_KW,
}

# 显著单域阈值: 最高分 >= _MIN_DOMAIN_SCORE 且领先第二名 >= _DOMAIN_MARGIN
_MIN_DOMAIN_SCORE = 2
_DOMAIN_MARGIN = 2

# 跨域底座工具: 三业务线问答都可能命中同一知识库(法规 FAQ 也在其中,
# 证据门依赖其证据), 任何子集都必须保留
_CROSS_CUTTING_TOOLS = ["search_bidding_knowledge"]

# 业务线 -> 工具子集 (仅列需要收窄的域; tender/general 使用全集)
REGULATION_TOOLS = _CROSS_CUTTING_TOOLS + ["consult_appeal", "recommend_template"]
ENTERPRISE_TOOLS = _CROSS_CUTTING_TOOLS + [
    "search_knowledge_graph", "search_postgresql", "list_bid_documents",
    "generate_bid_draft", "recommend_template", "guide_operation",
]
# tender 为核心域, 工具最全 = 全集; general 同样全集(不收窄)
TENDER_TOOLS: list[str] = []  # 空表示沿用全集, 在 select 函数中特殊处理


def _domain_scores(text: str) -> tuple[dict[str, int], dict[str, bool]]:
    """对单段文本计算三业务线命中分.

    返回 (总分表, 强信号表): 不同关键词命中分累加;
    strong[domain]=是否命中过至少 1 个权重 2 的强信号词.
    """
    scores = {"tender": 0, "regulation": 0, "enterprise": 0}
    strong = {"tender": False, "regulation": False, "enterprise": False}
    if not text:
        return scores, strong
    for domain, kws in _DOMAIN_KEYWORDS.items():
        for kw, weight in kws:
            if kw in text:
                scores[domain] += weight
                if weight >= 2:
                    strong[domain] = True
    return scores, strong


def classify_domain(question: str, history: list | None = None) -> dict:
    """显式三业务线意图分类.

    返回 {"domain": tender|regulation|enterprise|general,
          "scores": {tender, regulation, enterprise},
          "confident": bool, "inherited": bool}.
    显著单域条件:
      - 命中至少 1 个强信号词且总分 >= 2;
      - 次高域也有强信号且分差 < 2 时视为跨域 → general(不收窄);
      - 次高域仅弱信号不构成跨域, 信任最高域.
    其他跨域/弱信号 → general; 当前问题完全无域信号时继承最近一条
    用户消息的域(追问承接).
    """
    q = (question or "").strip()
    scores, strong = _domain_scores(q)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top_domain, top_score = ranked[0]
    second_domain, second_score = ranked[1]

    domain, confident, inherited = "general", False, False
    cross_domain = (
        second_score >= _MIN_DOMAIN_SCORE
        and strong[second_domain]
        and top_score - second_score < _DOMAIN_MARGIN
    )
    if (top_score >= _MIN_DOMAIN_SCORE and strong[top_domain]
            and not cross_domain):
        domain, confident = top_domain, True
    elif top_score == 0 and history:
        # 追问无任何域信号: 继承最近一条用户消息的分类
        for msg in reversed(history):
            if msg.get("role") == "user":
                prev = classify_domain(msg.get("content", ""), None)
                if prev["confident"]:
                    domain, confident, inherited = prev["domain"], True, True
                    scores = prev["scores"]
                break
    return {"domain": domain, "scores": scores,
            "confident": confident, "inherited": inherited}


def select_tools_for_domain(domain: str, base_tool_names: list[str]) -> list[str]:
    """按业务线从基础工具集中裁剪子集, 保持原顺序.

    tender/general/未知域 → 全集; regulation/enterprise → 收窄子集;
    跨域底座工具(search_bidding_knowledge)恒保留.
    """
    if domain == "regulation":
        allowed = set(REGULATION_TOOLS)
    elif domain == "enterprise":
        allowed = set(ENTERPRISE_TOOLS)
    else:  # tender / general / 未知
        return list(base_tool_names)
    cross = set(_CROSS_CUTTING_TOOLS)
    return [n for n in base_tool_names if n in allowed or n in cross]
