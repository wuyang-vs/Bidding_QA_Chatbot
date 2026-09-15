from __future__ import annotations
"""多 Agent 协作 — 主管调度模式, 零新依赖.

架构:
  CoordinatorAgent (主管)
    ├─ LawRetrievalAgent    → 查法规条文
    ├─ CaseRetrievalAgent   → 查案例/标的物
    ├─ PriceAnalysisAgent   → 价格分析 + 竞品
    └─ WritingAgent         → 综合各方结果写最终回答

每个专家 Agent 复用现有 LLM client + tool executors, 只是 system prompt 和
可用工具子集不同. 主管 Agent 负责拆解问题 → 调度专家 → 合并结果.
"""
import logging
import time
from enum import Enum

from src.agent.prompts import SYSTEM_PROMPT
from src.clients.llm_factory import get_llm_client
from src.tools.base import ToolRunner
from src.tools.rag_tools import TOOL_EXECUTORS, ALL_TOOLS

logger = logging.getLogger(__name__)


class AgentRole(str, Enum):
    COORDINATOR = "coordinator"
    LAW = "law_retrieval"
    CASE = "case_retrieval"
    PRICE = "price_analysis"
    WRITER = "writing"


# 每个专家 Agent 的 system prompt
ROLE_PROMPTS: dict[AgentRole, str] = {
    AgentRole.COORDINATOR: (
        "你是一个招投标领域的多 Agent 协作主管.\n"
        "你的任务:\n"
        "1. 分析用户问题, 判断需要调度哪些专家 Agent\n"
        "2. 给每个被调度的专家一个清晰的子任务描述\n"
        "3. 收集所有专家的结果, 综合成最终回答\n\n"
        "可用专家:\n"
        "- LAW: 法规检索专家, 查招投标法/政府采购法/条例\n"
        "- CASE: 案例检索专家, 查历史中标案例/标的物信息\n"
        "- PRICE: 价格分析专家, 分析价格走势/竞品格局/报价建议\n\n"
        "回复格式 (严格 JSON, 不要 markdown):\n"
        '{"specialists": ["LAW", "CASE", "PRICE"], "sub_tasks": {"LAW": "...", "CASE": "...", "PRICE": "..."}}'
    ),
    AgentRole.LAW: (
        "你是招投标法规检索专家. 你的任务是基于用户问题, 调用工具检索相关法规条文.\n"
        "重点关注: 招标投标法 / 政府采购法 / 各类实施条例 / 地方规定\n"
        "回答要: 引用具体法规名称和条款号, 给出条文摘要.\n"
        "如果没有相关法规, 明确说'未找到相关法规'."
    ),
    AgentRole.CASE: (
        "你是招投标案例检索专家. 你的任务是基于用户问题, 调用工具检索历史中标案例.\n"
        "重点关注: 同类标的物的中标情况 / 供应商 / 采购人 / 中标金额 / 时间\n"
        "回答要: 列出 3-5 个最相关案例, 每个包含标的物/供应商/金额/时间.\n"
        "如果没有相关案例, 明确说'未找到相关案例'."
    ),
    AgentRole.PRICE: (
        "你是价格分析专家. 你的任务是基于用户问题, 调用工具分析价格走势和竞品格局.\n"
        "重点关注: 历史成交价格分布 / 价格趋势 / 供应商竞争格局 / 报价建议区间\n"
        "回答要: 给出 P25/P50/P75 价格区间, 主要供应商, 报价建议.\n"
        "如果数据不足, 明确说明数据局限性."
    ),
    AgentRole.WRITER: (
        "你是一个专业的招投标报告撰写专家. 你会收到来自其他专家的分析结果.\n"
        "你的任务: 综合所有专家的结果, 写成一份结构清晰、逻辑严谨的最终回答.\n"
        "格式要求:\n"
        "1. 先给简明结论\n"
        "2. 再分点展开分析\n"
        "3. 标注每个断言的来源 [资料N]\n"
        "4. 结尾给出行动建议\n"
        "不要编造, 只基于提供的专家结果撰写."
    ),
}

# 每个专家可用的工具子集
ROLE_TOOLS: dict[AgentRole, list[str]] = {
    AgentRole.COORDINATOR: [],  # 主管不直接调工具
    AgentRole.LAW: ["search_bidding_knowledge", "search_web", "search_exa"],
    AgentRole.CASE: ["search_bidding_knowledge", "search_knowledge_graph",
                     "search_postgresql", "search_web"],
    AgentRole.PRICE: ["search_postgresql", "search_knowledge_graph", "search_web"],
    AgentRole.WRITER: [],  # 写作专家不调工具, 只用传入的上下文
}


class SpecialistAgent:
    """单个专家 Agent — 角色 prompt + 工具子集 + LLM."""

    def __init__(self, role: AgentRole, provider: str = "", deep_thinking: bool = False):
        self.role = role
        self.provider = provider
        self.deep_thinking = deep_thinking
        self._llm = None

    @property
    def llm(self):
        if self._llm is None:
            self._llm = get_llm_client(self.provider, self.deep_thinking)
        return self._llm

    @property
    def system_prompt(self) -> str:
        return SYSTEM_PROMPT + "\n\n" + ROLE_PROMPTS[self.role]

    @property
    def tool_schemas(self) -> list:
        tool_names = ROLE_TOOLS[self.role]
        return [t.to_openai_schema() for t in ALL_TOOLS if t.name in tool_names]

    def run(self, task: str, context: str = "", max_rounds: int = 3) -> dict:
        """执行专家任务, 返回 {role, answer, sources, round_trips, elapsed_ms}."""
        from src.agent.react_loop import ReActMixin
        # 复用 ReAct 循环
        messages = [{"role": "system", "content": self.system_prompt}]
        if context:
            messages.append({"role": "user",
                             "content": f"【已有上下文】\n{context}\n\n【你的任务】\n{task}"})
        else:
            messages.append({"role": "user", "content": task})

        t0 = time.time()
        all_sources = []
        last_tool = ""
        answer = ""

        for round_idx in range(1, max_rounds + 1):
            try:
                response = self.llm.chat_raw(messages, tools=self.tool_schemas)
            except Exception as e:
                logger.warning("[%s] LLM 调用失败: %s", self.role.value, e)
                break

            choice = response.choices[0]
            msg = choice.message
            tool_calls = getattr(msg, "tool_calls", None)

            if tool_calls:
                content = getattr(msg, "content", "") or ""
                messages.append({"role": "assistant", "content": content,
                                  "tool_calls": [tc.model_dump() if hasattr(tc, "model_dump") else tc
                                                 for tc in tool_calls]})
                results = ToolRunner.run_parallel(tool_calls, task, TOOL_EXECUTORS)
                for tc, r in zip(tool_calls, results):
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": r.text})
                    all_sources.extend(r.sources)
                    last_tool = r.name
                continue

            raw = getattr(msg, "content", "") or ""
            if raw:
                answer = raw
                break
            messages.append({"role": "user", "content": "请直接给出回答, 不要调用工具."})
        else:
            messages.append({"role": "user", "content": "请基于以上工具结果直接回答."})

        elapsed = int((time.time() - t0) * 1000)
        return {
            "role": self.role.value,
            "answer": answer[:2000],
            "sources": all_sources[:20],
            "tool_called": bool(last_tool),
            "tool_name": last_tool,
            "rounds": round_idx if 'round_idx' in dir() else max_rounds,
            "elapsed_ms": elapsed,
        }


class CoordinatorAgent:
    """主管 Agent — 拆解问题, 调度专家, 合并结果."""

    def __init__(self, provider: str = "", deep_thinking: bool = False):
        self.provider = provider
        self.deep_thinking = deep_thinking
        self._llm = None

    @property
    def llm(self):
        if self._llm is None:
            self._llm = get_llm_client(self.provider, self.deep_thinking)
        return self._llm

    def plan(self, question: str) -> dict:
        """用 LLM 拆解问题, 返回 {specialists: [...], sub_tasks: {...}}."""
        messages = [
            {"role": "system", "content": ROLE_PROMPTS[AgentRole.COORDINATOR]},
            {"role": "user", "content": f"问题: {question}\n\n请决定调度哪些专家 Agent."},
        ]
        try:
            response = self.llm.chat_raw(messages, tools=None)
            raw = getattr(response.choices[0].message, "content", "") or ""
            import re
            json_match = re.search(r"\{[\s\S]*\}", raw)
            if json_match:
                import json
                plan = json.loads(json_match.group(0))
                specialists = plan.get("specialists", [])
                sub_tasks = plan.get("sub_tasks", {})
                # 校验专家名
                valid = {"LAW", "CASE", "PRICE"}
                specialists = [s for s in specialists if s in valid]
                return {"specialists": specialists, "sub_tasks": sub_tasks}
        except Exception as e:
            logger.warning("Coordinator plan 失败: %s", e)

        # fallback: 调度所有专家
        return {
            "specialists": ["LAW", "CASE", "PRICE"],
            "sub_tasks": {"LAW": question, "CASE": question, "PRICE": question},
        }


def run_multi_agent_workflow(question: str, provider: str = "",
                              deep_thinking: bool = False) -> dict:
    """完整多 Agent 工作流: 主管拆解 → 专家并行 → 写作专家综合 → 返回."""
    t_total = time.time()
    coordinator = CoordinatorAgent(provider, deep_thinking)
    plan = coordinator.plan(question)

    specialist_map = {
        "LAW": AgentRole.LAW,
        "CASE": AgentRole.CASE,
        "PRICE": AgentRole.PRICE,
    }

    # 并行执行专家 (简单线程池)
    import concurrent.futures
    specialists_to_run = [specialist_map[s] for s in plan["specialists"] if s in specialist_map]

    results: list[dict] = []
    if specialists_to_run:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(specialists_to_run)) as pool:
            futures = {}
            for role in specialists_to_run:
                task_desc = plan.get("sub_tasks", {}).get(role.value.replace("retrieval", "").replace("analysis", "").upper()[:4], question)
                # 简化: 直接用 sub_tasks 里对应 key
                key = role.value
                if role == AgentRole.LAW:
                    key = "LAW"
                elif role == AgentRole.CASE:
                    key = "CASE"
                elif role == AgentRole.PRICE:
                    key = "PRICE"
                task_desc = plan.get("sub_tasks", {}).get(key, question)
                agent = SpecialistAgent(role, provider, deep_thinking)
                futures[pool.submit(agent.run, task_desc)] = role

            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())

    # 写作专家综合
    writer = SpecialistAgent(AgentRole.WRITER, provider, deep_thinking)
    expert_context_parts = []
    for r in results:
        role_label = {"law_retrieval": "法规专家", "case_retrieval": "案例专家", "price_analysis": "价格专家"}.get(r["role"], r["role"])
        expert_context_parts.append(f"【{role_label}】\n{r['answer']}")
    expert_context = "\n\n".join(expert_context_parts)
    if not expert_context:
        expert_context = "没有其他专家的结果, 请直接基于问题回答."

    final = writer.run(question, context=expert_context)

    # 合并所有来源
    all_sources = []
    seen = set()
    for r in results + [final]:
        for s in r.get("sources", []):
            key = (s.get("question", ""), s.get("answer", ""))
            if key not in seen:
                seen.add(key)
                all_sources.append(s)

    return {
        "question": question,
        "plan": plan,
        "expert_results": results,
        "final_answer": final["answer"],
        "sources": all_sources,
        "total_elapsed_ms": int((time.time() - t_total) * 1000),
        "specialists_count": len(specialists_to_run),
    }
