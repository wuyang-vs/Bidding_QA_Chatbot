"""multi_agent 多 Agent 工作流离线单测: LLM 全部 mock, 零网络。

覆盖:
  - CoordinatorAgent.plan 的 JSON 解析/非法专家过滤/异常与脏数据回退;
  - run_multi_agent_workflow 端到端编排(主管→并行专家→写作)的结果结构;
  - 行级隔离 ContextVar 经 copy_context 传播到专家工作线程。
"""
from __future__ import annotations

from types import SimpleNamespace


def _fake_response(content: str):
    msg = SimpleNamespace(content=content, tool_calls=None)
    choice = SimpleNamespace(message=msg)
    return SimpleNamespace(choices=[choice])


class _FakeLLM:
    def __init__(self, content: str = "", raise_exc: Exception | None = None):
        self.content = content
        self.raise_exc = raise_exc

    def chat_raw(self, messages, tools=None):
        if self.raise_exc:
            raise self.raise_exc
        return _fake_response(self.content)


class TestCoordinatorPlan:
    def test_parse_valid_json_and_filter(self, monkeypatch):
        from src.agent import multi_agent as ma
        raw = '前缀文字 {"specialists": ["LAW", "PRICE", "UNKNOWN"], ' \
              '"sub_tasks": {"LAW": "查法规", "PRICE": "算价格"}} 后缀'
        monkeypatch.setattr(ma, "get_llm_client", lambda *a, **k: _FakeLLM(raw))
        plan = ma.CoordinatorAgent().plan("某问题")
        assert plan["specialists"] == ["LAW", "PRICE"]
        assert plan["sub_tasks"]["LAW"] == "查法规"

    def test_fallback_on_garbage(self, monkeypatch):
        from src.agent import multi_agent as ma
        monkeypatch.setattr(ma, "get_llm_client",
                            lambda *a, **k: _FakeLLM("没有JSON"))
        plan = ma.CoordinatorAgent().plan("问题")
        assert set(plan["specialists"]) == {"LAW", "CASE", "PRICE"}

    def test_fallback_on_llm_exception(self, monkeypatch):
        from src.agent import multi_agent as ma
        monkeypatch.setattr(
            ma, "get_llm_client",
            lambda *a, **k: _FakeLLM(raise_exc=RuntimeError("500")))
        plan = ma.CoordinatorAgent().plan("问题")
        assert len(plan["specialists"]) == 3


class TestWorkflow:
    def _fake_run_factory(self, seen_scopes: list, barrier=None):
        from src.auth.access_scope import get_current_scope
        from src.agent.multi_agent import AgentRole

        def fake_run(self, task: str, context: str = "", max_rounds: int = 3):
            # 强制 3 个专家线程并发进入各自上下文, 复现"同一 Context 被并发 run"
            if barrier is not None and self.role != AgentRole.WRITER:
                barrier.wait(timeout=5)
            # 在工作线程内读取行级隔离范围, 验证 copy_context 传播
            seen_scopes.append((self.role, get_current_scope()))
            if self.role == AgentRole.WRITER:
                return {"role": "writing", "answer": "综合答复", "sources": [],
                        "tool_called": False, "tool_name": "", "rounds": 1,
                        "elapsed_ms": 1}
            return {
                "role": self.role.value,
                "answer": f"{self.role.value} 的分析",
                "sources": [{"question": f"q-{self.role.value}",
                             "answer": f"a-{self.role.value}"}],
                "tool_called": True, "tool_name": "search_bidding_knowledge",
                "rounds": 2, "elapsed_ms": 10,
            }
        return fake_run

    def test_workflow_structure_and_scope_propagation(self, monkeypatch):
        import threading
        from src.agent import multi_agent as ma

        seen_scopes: list = []
        barrier = threading.Barrier(3)  # 三专家必须并发在场才放行
        monkeypatch.setattr(ma.CoordinatorAgent, "plan",
                            lambda self, q: {"specialists": ["LAW", "CASE", "PRICE"],
                                             "sub_tasks": {}})
        monkeypatch.setattr(ma.SpecialistAgent, "run",
                            self._fake_run_factory(seen_scopes, barrier))

        # bidder 用户 → owner 范围; 专家工作线程必须读到同一范围而非 None/匿名
        from src.auth.access_scope import use_access_scope
        user = {"id": 7, "role": "bidder"}
        with use_access_scope(user):
            out = ma.run_multi_agent_workflow("跨域问题")

        assert out["final_answer"] == "综合答复"
        assert out["specialists_count"] == 3
        assert len(out["expert_results"]) == 3
        assert set(out["plan"]["specialists"]) == {"LAW", "CASE", "PRICE"}
        # 三个专家来源 + writer 无来源
        assert len(out["sources"]) == 3
        assert out["total_elapsed_ms"] >= 0

        expert_scopes = {role: scope for role, scope in seen_scopes
                         if role != ma.AgentRole.WRITER}
        assert set(expert_scopes) == {ma.AgentRole.LAW, ma.AgentRole.CASE,
                                      ma.AgentRole.PRICE}
        for scope in expert_scopes.values():
            assert scope == ("owner", 7), f"专家线程行级隔离丢失: {scope}"

    def test_sources_dedup_across_experts(self, monkeypatch):
        from src.agent import multi_agent as ma

        shared = {"question": "同一问题", "answer": "同一证据"}

        def fake_run(self, task, context="", max_rounds=3):
            return {"role": getattr(self.role, "value", "writing"),
                    "answer": "x",
                    "sources": [dict(shared)] if self.role != ma.AgentRole.WRITER else [],
                    "tool_called": True, "tool_name": "t", "rounds": 1,
                    "elapsed_ms": 1}

        monkeypatch.setattr(ma.CoordinatorAgent, "plan",
                            lambda self, q: {"specialists": ["LAW", "CASE", "PRICE"],
                                             "sub_tasks": {}})
        monkeypatch.setattr(ma.SpecialistAgent, "run", fake_run)
        out = ma.run_multi_agent_workflow("q")
        # 三专家返回同一证据 → 合并去重为 1 条
        assert out["sources"] == [shared]
