"""R14: 范本智能推荐 — 静态范本库 + 关键词匹配推荐算法。

覆盖三类范本: 招标文件范本 / 合同范本 / 业务表单。
每条范本含 category / name / project_types / keywords / summary /
sections / source_url，按 query 与 project_types+keywords 的词命中数打分排序。
"""
from __future__ import annotations
from typing import Any

TEMPLATES: list[dict[str, Any]] = [
    # ============ 招标文件范本 ============
    {
        "id": "TPL-BID-001",
        "category": "招标文件",
        "name": "工程建设项目施工招标文件范本（公开招标）",
        "project_types": ["工程施工", "建筑工程", "市政工程", "施工招标"],
        "keywords": ["施工", "工程", "建筑", "市政", "土建", "公开招标", "招标"],
        "summary": "适用于工程建设项目施工公开招标，含招标公告、投标人须知、评标办法、合同条款、工程量清单、图纸等标准章节。",
        "sections": ["招标公告", "投标人须知", "评标办法（综合评估法/经评审最低投标价法）", "合同条款及格式", "工程量清单", "图纸", "技术标准和要求"],
        "source_url": "http://www.mohurd.gov.cn 建设工程施工合同示范文本",
    },
    {
        "id": "TPL-BID-002",
        "category": "招标文件",
        "name": "政府采购货物和服务招标文件范本",
        "project_types": ["货物采购", "服务采购", "政府采购", "货物招标"],
        "keywords": ["货物", "服务", "政府采购", "集中采购", "公开招标"],
        "summary": "适用于各级政府采购货物和服务公开招标项目，严格遵循《政府采购法》及财政部令第87号。",
        "sections": ["投标邀请", "投标人须知", "评标方法和标准", "采购需求", "合同条款", "投标文件格式"],
        "source_url": "http://www.ccgp.gov.cn 中国政府采购网",
    },
    {
        "id": "TPL-BID-003",
        "category": "招标文件",
        "name": "设计服务招标文件范本",
        "project_types": ["设计招标", "工程设计", "勘察设计", "方案设计"],
        "keywords": ["设计", "勘察", "方案", "施工图", "BIM"],
        "summary": "适用于工程勘察、方案设计、初步设计、施工图设计等服务类招标，重点考察设计方案与团队配置。",
        "sections": ["招标公告", "投标人须知", "评标办法（综合评估法，设计方案权重高）", "设计任务书", "合同条款"],
        "source_url": "住建部设计招标文件示范文本",
    },
    {
        "id": "TPL-BID-004",
        "category": "招标文件",
        "name": "设备采购招标文件范本",
        "project_types": ["设备采购", "机电设备", "仪器设备", "专用设备"],
        "keywords": ["设备", "机电", "仪器", "机械", "采购"],
        "summary": "适用于机电设备、专用仪器等货物采购，含技术参数、供货范围、安装调试、验收标准等章节。",
        "sections": ["招标公告", "投标人须知", "评标办法", "技术规格与要求", "供货范围", "安装调试与验收"],
        "source_url": "机电产品采购国际招标文件范本",
    },

    # ============ 合同范本 ============
    {
        "id": "TPL-CON-001",
        "category": "合同范本",
        "name": "建设工程施工合同（示范文本）",
        "project_types": ["工程施工", "建筑工程", "施工合同"],
        "keywords": ["施工合同", "工程", "施工", "承包", "总包"],
        "summary": "住建部与国家工商总局联合发布的建设工程施工合同示范文本（GF-2017-0201），含协议书、通用条款、专用条款。",
        "sections": ["协议书", "通用合同条款", "专用合同条款", "附件（承包人承揽工程项目一览表等）"],
        "source_url": "GF-2017-0201 建设工程施工合同（示范文本）",
    },
    {
        "id": "TPL-CON-002",
        "category": "合同范本",
        "name": "政府采购合同范本",
        "project_types": ["货物采购", "服务采购", "政府采购"],
        "keywords": ["政府采购", "合同", "货物", "服务"],
        "summary": "适用于政府采购货物和服务项目的合同签订，明确采购内容、金额、履行期限、验收标准、违约责任。",
        "sections": ["合同主体", "采购标的", "合同金额", "履行期限与地点", "验收标准", "付款方式", "违约责任", "争议解决"],
        "source_url": "财政部政府采购合同示范文本",
    },
    {
        "id": "TPL-CON-003",
        "category": "合同范本",
        "name": "技术咨询/服务合同范本",
        "project_types": ["咨询服务", "技术服务", "设计咨询", "监理服务"],
        "keywords": ["咨询", "技术服务", "监理", "设计咨询"],
        "summary": "适用于技术咨询、工程监理、设计咨询等服务类合同，重点约定服务内容、成果交付、知识产权。",
        "sections": ["服务内容与要求", "服务期限", "报酬及支付", "成果交付与验收", "知识产权", "保密条款"],
        "source_url": "技术服务合同（示范文本）",
    },

    # ============ 业务表单 ============
    {
        "id": "TPL-FRM-001",
        "category": "业务表单",
        "name": "投标函（标准格式）",
        "project_types": ["工程施工", "货物采购", "服务采购", "通用投标"],
        "keywords": ["投标函", "投标书", "报价函", "承诺"],
        "summary": "投标文件必备的投标函标准格式，含投标报价、工期、质量承诺、投标有效期等核心声明。",
        "sections": ["致招标人", "投标报价（大写+数字）", "工期/交付期", "质量标准", "投标有效期", "履约担保承诺", "投标人签章"],
        "source_url": "招标文件范本附投标函格式",
    },
    {
        "id": "TPL-FRM-002",
        "category": "业务表单",
        "name": "资格审查申请文件格式",
        "project_types": ["资格预审", "资格审查", "通用投标"],
        "keywords": ["资格审查", "资格预审", "资质", "业绩"],
        "summary": "适用于资格预审项目，含企业资质、财务状况、类似业绩、项目管理机构等证明材料清单。",
        "sections": ["资格预审申请函", "法定代表人身份证明", "企业资质证书", "财务状况表", "近年类似项目业绩", "项目管理机构"],
        "source_url": "工程建设项目施工招标资格预审文件示范文本",
    },
    {
        "id": "TPL-FRM-003",
        "category": "业务表单",
        "name": "技术参数响应表",
        "project_types": ["设备采购", "货物采购", "服务采购", "通用投标"],
        "keywords": ["响应表", "技术参数", "偏离表", "商务偏离"],
        "summary": "逐条响应招标文件技术/商务参数的标准表格，标注正偏离/无偏离/负偏离。",
        "sections": ["序号", "招标文件要求", "投标响应", "偏离说明（正偏离/无偏离/负偏离）"],
        "source_url": "招标文件范本附技术响应表格式",
    },
    {
        "id": "TPL-FRM-004",
        "category": "业务表单",
        "name": "投标保证金缴纳凭证格式",
        "project_types": ["工程施工", "货物采购", "服务采购", "通用投标"],
        "keywords": ["投标保证金", "保函", "保证金", "凭证"],
        "summary": "投标保证金缴纳证明格式，含银行转账凭证或银行保函。",
        "sections": ["银行回单（电汇/转账）", "或银行保函（不可撤销、见索即付）", "保证金金额与到账时间"],
        "source_url": "招标文件范本附保证金格式",
    },
]

# 用于匹配的中文分词简易词典（项目类型+关键词中出现的高频词）
_TOKEN_DICT: set[str] = set()
for _t in TEMPLATES:
    _TOKEN_DICT.update(_t.get("project_types", []))
    _TOKEN_DICT.update(_t.get("keywords", []))


def _tokenize(query: str) -> list[str]:
    """简易中文分词: 按标点拆分 + 与词典最大逆向匹配（贪心 4 字→1 字）。"""
    if not query:
        return []
    import re
    parts = re.split(r"[\s,，。、；;：:·\-_/\\（）()【】\[\]]+", query)
    tokens: list[str] = []
    for part in parts:
        if not part:
            continue
        i = 0
        n = len(part)
        while i < n:
            matched = None
            for size in range(min(6, n - i), 0, -1):
                piece = part[i:i + size]
                if piece in _TOKEN_DICT:
                    matched = piece
                    break
            if matched:
                tokens.append(matched)
                i += len(matched)
            else:
                i += 1
    return tokens


def recommend_templates(query: str, category: str | None = None,
                        top_k: int = 5) -> list[dict[str, Any]]:
    """按 query 推荐范本，返回 top_k（含 score）。"""
    tokens = _tokenize(query)
    token_set = set(tokens)
    scored: list[tuple[float, dict[str, Any]]] = []
    for tpl in TEMPLATES:
        if category and tpl["category"] != category:
            continue
        haystack = set(tpl.get("project_types", [])) | set(tpl.get("keywords", []))
        # 命中数 + 命名加权（name 中命中额外加分）
        hits = token_set & haystack
        score = float(len(hits))
        # name 命中加成 (权重低, 避免类别核心词被名称淹没)
        name_hits = sum(1 for tok in tokens if tok and tok in tpl["name"])
        score += name_hits * 0.25
        if score <= 0:
            continue
        scored.append((score, {**tpl, "score": round(score, 2)}))
    scored.sort(key=lambda x: (-x[0], x[1]["id"]))
    return [t[1] for t in scored[:top_k]]


def get_template(tid: str) -> dict[str, Any] | None:
    for t in TEMPLATES:
        if t["id"] == tid:
            return t
    return None


def list_categories() -> list[str]:
    return sorted({t["category"] for t in TEMPLATES})
