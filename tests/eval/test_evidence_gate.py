# -*- coding: utf-8 -*-
"""硬闸门纯函数离线测试: src.agent.evidence_gate
不依赖 HTTP / LLM / 向量库, 直接 python tests/eval/test_evidence_gate.py 运行。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.agent.evidence_gate import (  # noqa: E402
    NO_EVIDENCE_NOTICE, evidence_covers_question, gate_decision, is_chitchat,
    tool_provided_evidence,
)

failures = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


# ---------- is_chitchat ----------
for q in ["你好", "您好！", "hi", "Hello", "在吗？", "谢谢~", "再见",
          "你是谁", "你能做什么？", "你有什么功能", "帮助", "怎么用"]:
    check(f"寒暄放行: {q}", is_chitchat(q))

for q in ["投标保证金怎么退？", "你好，请问XX项目的投标截止时间是什么时候",
          "废标条款有哪些", "如何注册交易平台账号"]:
    check(f"知识问题不当寒暄: {q}", not is_chitchat(q))

# ---------- tool_provided_evidence ----------
rag_docs = [{"question": "q", "answer": "a", "score": 0.8}]
check("RAG有分片=有证据", tool_provided_evidence("search_bidding_knowledge", rag_docs, "【资料1】..."))
check("RAG空分片=无证据", not tool_provided_evidence("search_bidding_knowledge", [], "未检索到相关文档"))
# 跨领域无关问题会返回低分噪声 (实测均分 0.003 级别), 不得计为证据
low_docs = [{"question": "q", "answer": "a", "score": 0.006},
            {"question": "q2", "answer": "a2", "score": 0.003}]
check("RAG低相关噪声=无证据", not tool_provided_evidence(
    "search_bidding_knowledge", low_docs, "【资料1】..."))
mid_docs = [{"question": "q", "answer": "a", "score": 0.93},
            {"question": "q2", "answer": "a2", "score": 0.87}]
check("RAG高相关=有证据", tool_provided_evidence("search_bidding_knowledge", mid_docs, "【资料1】..."))
# 标书 Agent 工具
check("标书生成工具=有证据", tool_provided_evidence(
    "generate_bid_draft", [], "## 技术方案\n[公司全称]针对本项目..."))
check("标书列表有数据=有证据", tool_provided_evidence(
    "list_bid_documents", [], "共 5 份当前账号可见的招标文件:\n- id=7 | ..."))
check("标书列表空=无证据", not tool_provided_evidence(
    "list_bid_documents", [], "未找到关键词「月球」当前账号可见的招标文件"))
check("标书工具越权=无证据", not tool_provided_evidence(
    "generate_bid_draft", [], "无权访问招标文件 id=26, 该文档可能为他人内部文件"))
check("PG实质数据=有证据", tool_provided_evidence(
    "search_postgresql", [], "项目名称: 智慧园区 | 预算: 8600000"))
check("PG空结果=无证据", not tool_provided_evidence("search_postgresql", [], "未查询到数据"))
check("PG未连接=无证据", not tool_provided_evidence("search_postgresql", [], "PostgreSQL 未连接"))
check("图谱实质数据=有证据", tool_provided_evidence(
    "search_knowledge_graph", [], "{'entity': 'XX公司', 'type': '供应商'}"))
check("图谱空=无证据", not tool_provided_evidence("search_knowledge_graph", [], "未找到相关图谱数据"))
check("工具执行失败=无证据", not tool_provided_evidence(
    "search_bidding_knowledge", [], "执行失败: connection reset"))
check("未知工具=无证据", not tool_provided_evidence("hack_tool", [{"x": 1}], "data"))

# ---------- gate_decision 状态机 ----------
Q = "XX市智慧园区项目二期的投标截止时间是什么时候？"

# 1) 寒暄直接放行(无需工具)
check("寒暄→answer", gate_decision("你好", False, False, False) == "answer")

# 2) 有证据放行(无论是否调过工具)
check("有证据→answer", gate_decision(Q, True, True, False) == "answer")
check("强制后有证据→answer", gate_decision(Q, True, True, True) == "answer")

# 3) 未调工具直接作答 → 首次强制补检索
check("未取证首次→force_retrieval",
      gate_decision(Q, False, False, False) == "force_retrieval")

# 4) 强制过仍无工具/无证据 → 硬拒
check("强制后仍无→refuse", gate_decision(Q, False, False, True) == "refuse")

# 5) 调过工具但全部空 → 硬拒(不再浪费重试)
check("工具全空→refuse", gate_decision(Q, True, False, False) == "refuse")
check("工具全空(已强制)→refuse", gate_decision(Q, True, False, True) == "refuse")

# 5b) 证据文本覆盖问题特征词: 通用法规 FAQ 不能为虚构具体项目"背书"
Q_MOON = "月球表面氦3开采基地绿化景观工程的投标保证金缴纳比例和开标时间是怎么规定的？"
generic_law = ["问: 投标保证金的比例上限是多少？答: 根据招标投标法实施条例..."]
tender_hit = ["【招标文件】XX市智慧园区信息化建设项目（二期） 投标截止 2025年12月15日"]
check("虚构项目+通用法规文本=未覆盖", not evidence_covers_question(Q_MOON, generic_law))
check("真实项目+招标分片=覆盖", evidence_covers_question(Q, tender_hit))
check("通用概念问题不做覆盖约束", evidence_covers_question("投标保证金怎么退？", generic_law))
check("有高分证据但不覆盖具体项目→refuse",
      gate_decision(Q_MOON, True, True, False, evidence_texts=generic_law) == "refuse")
check("证据覆盖具体项目→answer",
      gate_decision(Q, True, True, False, evidence_texts=tender_hit) == "answer")

# 6) 固定话术不含任何具体业务事实, 且非空
check("固定话术有效", "未在本地权威知识库中检索到" in NO_EVIDENCE_NOTICE
      and "860" not in NO_EVIDENCE_NOTICE)

print("\n%s" % ("全部通过 ✅" if not failures else f"{len(failures)} 项失败 ❌: {failures}"))
sys.exit(1 if failures else 0)
