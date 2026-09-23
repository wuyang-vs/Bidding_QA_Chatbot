"""构造 ReAct 工具调用 SFT 轨迹 — 80 条多轮对话。

从 sources_seed.jsonl (shenlan_qa 80条种子) 构造工具调用轨迹，
assistant 工具调用用 OpenAI JSON 文本形态 (与 tool_defense.py _JSON_RE 对齐)。

用法:
    python scripts/sft/build_toolcall_sft.py

输出: sft_toolcall.json (LLaMA-Factory sharegpt 多轮格式)
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
OUT_DIR = Path(__file__).resolve().parent


# ── 导入 system prompt 和工具定义 ──
from src.agent.prompts import SYSTEM_PROMPT

# 工具 schema (ALL_TOOLS + bid agent tools)
try:
    from src.tools.rag_tools import ALL_TOOLS
except Exception:
    ALL_TOOLS = []

TOOL_SCHEMAS = []
for t in ALL_TOOLS:
    TOOL_SCHEMAS.append({
        "name": t.name,
        "description": t.description,
        "parameters": t.parameters,
    })

# ── 场景路由: 根据问题内容选择工具 ──
def _pick_tool(question: str, answer: str) -> str:
    """根据问题内容选择合适的工具名"""
    q = question + " " + answer
    if any(k in q for k in ("关系", "频次", "采购人", "供应商", "标的物", "图谱")):
        return "search_knowledge_graph"
    if any(k in q for k in ("统计", "排名", "金额合计", "汇总", "总金额", "时间范围")):
        return "search_postgresql"
    if any(k in q for k in ("写标书", "生成投标", "起草", "技术方案", "商务方案")):
        return "generate_bid_draft"
    if any(k in q for k in ("最新", "公告", "更新", "联网")):
        return "search_web"
    # 默认: 知识库检索
    return "search_bidding_knowledge"


def _build_observation(question: str, answer: str, tool: str) -> str:
    """构造工具返回结果 (observation)"""
    if tool == "search_knowledge_graph":
        return f"知识图谱检索结果:\n{answer[:500]}"
    if tool == "search_postgresql":
        return f"数据库查询结果:\n{answer[:500]}"
    if tool == "generate_bid_draft":
        return f"标书章节草稿:\n{answer[:500]}"
    if tool == "search_web":
        return f"联网搜索结果:\n{answer[:500]}"
    # search_bidding_knowledge
    return f"知识库检索到以下相关内容:\n{answer[:500]}"


def _build_tool_call_text(tool: str, question: str) -> str:
    """构造 OpenAI JSON 文本形态工具调用 (与 tool_defense _JSON_RE 对齐)"""
    # 构造合理的查询参数
    query = question[:80].replace('"', "'")
    if tool == "search_knowledge_graph":
        return json.dumps({
            "name": tool,
            "arguments": {"query_type": "search_entity", "keyword": query},
        }, ensure_ascii=False)
    if tool == "search_postgresql":
        return json.dumps({
            "name": tool,
            "arguments": {"query_type": "search_by_keyword", "keyword": query},
        }, ensure_ascii=False)
    if tool == "generate_bid_draft":
        return json.dumps({
            "name": tool,
            "arguments": {"db_id": 1, "section": "technical"},
        }, ensure_ascii=False)
    if tool == "search_web":
        return json.dumps({
            "name": tool,
            "arguments": {"query": query},
        }, ensure_ascii=False)
    # search_bidding_knowledge
    return json.dumps({
        "name": tool,
        "arguments": {"query": query},
    }, ensure_ascii=False)


def _build_final_answer(question: str, answer: str, tool: str) -> str:
    """构造基于检索结果的最终答案"""
    # 如果答案已经很好, 稍微包装一下引用来源
    a = answer.strip()
    if not a.startswith("根据") and not a.startswith("依据"):
        a = "根据检索结果，" + a
    return a


# ── 越界拒答场景 (不调工具, 直接拒答) ──
OUT_OF_SCOPE = [
    ("今天天气怎么样？", "抱歉，我是招投标智能问答助手，只能回答招投标、政府采购相关的问题。天气查询不在我的服务范围内，建议您使用天气预报应用查询。"),
    ("帮我写一首诗", "抱歉，我是招投标智能问答助手，只能回答招投标、政府采购相关的问题。写诗不在我的服务范围内。"),
    ("这道数学题怎么解：3x+5=20", "抱歉，我是招投标智能问答助手，只能回答招投标、政府采购相关的问题。数学题解答不在我的服务范围内，建议您咨询数学老师或使用专业工具。"),
    ("帮我推荐一部电影", "抱歉，我是招投标智能问答助手，只能回答招投标、政府采购相关的问题。电影推荐不在我的服务范围内。"),
    ("如何做红烧肉？", "抱歉，我是招投标智能问答助手，只能回答招投标、政府采购相关的问题。烹饪不在我的服务范围内。"),
]


def build_out_of_scope() -> list[dict]:
    """构造越界拒答轨迹 (不调工具)"""
    items = []
    for q, a in OUT_OF_SCOPE:
        items.append({
            "conversations": [
                {"from": "system", "value": SYSTEM_PROMPT},
                {"from": "human", "value": q},
                {"from": "gpt", "value": a},
            ]
        })
    return items


def main():
    # 加载种子 Q&A
    seed_path = OUT_DIR / "sources_seed.jsonl"
    if not seed_path.exists():
        print("sources_seed.jsonl 不存在, 请先运行 extract_sources.py")
        return

    seeds = []
    with open(seed_path, "r", encoding="utf-8") as f:
        for line in f:
            seeds.append(json.loads(line))
    print(f"加载 {len(seeds)} 条种子 Q&A")

    # 构造工具调用轨迹
    items = []
    for seed in seeds:
        q = seed["question"]
        a = seed["answer"]
        tool = _pick_tool(q, a)
        tool_call = _build_tool_call_text(tool, q)
        observation = _build_observation(q, a, tool)
        final_answer = _build_final_answer(q, a, tool)

        items.append({
            "conversations": [
                {"from": "system", "value": SYSTEM_PROMPT},
                {"from": "human", "value": q},
                {"from": "gpt", "value": tool_call},
                {"from": "observation", "value": observation},
                {"from": "gpt", "value": final_answer},
            ]
        })

    # 追加越界拒答
    items.extend(build_out_of_scope())

    # 统计工具分布
    tool_counts = {}
    for item in items:
        convs = item["conversations"]
        if len(convs) == 3:  # system + human + gpt (越界拒答)
            tool_counts["(直接回答)"] = tool_counts.get("(直接回答)", 0) + 1
        elif len(convs) >= 4:
            call_text = convs[2]["value"]
            m = re.search(r'"name":\s*"(search_\w+)"', call_text)
            if m:
                tool_counts[m.group(1)] = tool_counts.get(m.group(1), 0) + 1

    print(f"\n工具分布:")
    for tool, cnt in sorted(tool_counts.items(), key=lambda x: -x[1]):
        print(f"  {tool}: {cnt}")

    # 写出
    out_path = OUT_DIR / "sft_toolcall.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

    print(f"\n生成 {len(items)} 条工具调用轨迹 → {out_path}")


if __name__ == "__main__":
    main()
