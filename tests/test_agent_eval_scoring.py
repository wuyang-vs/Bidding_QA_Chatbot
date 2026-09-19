"""Agent 端到端评测打分器离线单测 (纯函数, 毫秒级)。"""
from __future__ import annotations

from src.agent.eval_scoring import (
    aggregate, fact_group_satisfied, score_case, score_facts, score_tools,
)


class TestFactGroup:
    def test_string_term(self):
        assert fact_group_satisfied("单一来源", "什么是单一来源采购") == (True, ["单一来源"])
        assert fact_group_satisfied("竞争性谈判", "只有单一来源")[0] is False

    def test_any_group(self):
        ok, matched = fact_group_satisfied({"any": ["860万", "8,600,000"]},
                                           "预算 8,600,000 元")
        assert ok and matched == ["8,600,000"]

    def test_all_group(self):
        g = {"all": ["2%", "17.2万"]}
        assert fact_group_satisfied(g, "比例2%，上限17.2万")[0] is True
        assert fact_group_satisfied(g, "只有2%")[0] is False

    def test_case_insensitive_latin(self):
        assert fact_group_satisfied("EPC", "采用 epc 总承包")[0] is True


class TestScoreFacts:
    def test_hit_rate_groups_equal_weight(self):
        groups = ["单一来源", {"any": ["x", "保证金"]}, "不存在词"]
        r = score_facts(groups, "单一来源 保证金 已退还")
        assert r["total"] == 3 and r["hit"] == 2
        assert r["hit_rate"] == round(2 / 3, 4)

    def test_empty_groups_na(self):
        r = score_facts([], "任意答案")
        assert r["hit_rate"] is None and r["total"] == 0


class TestScoreTools:
    def test_required_and_any(self):
        case = {"tools_any": ["search_knowledge_graph", "search_postgresql"],
                "tools_required": ["search_bidding_knowledge"]}
        r = score_tools(case, ["search_bidding_knowledge", "search_web"])
        assert r["any_hit"] is False
        assert r["required_recall"] == 1.0
        r2 = score_tools(case, ["search_bidding_knowledge", "search_postgresql"])
        assert r2["any_hit"] is True and r2["required_miss"] == []

    def test_missing_required(self):
        r = score_tools({"tools_required": ["a", "b"]}, ["a"])
        assert r["required_recall"] == 0.5 and r["required_miss"] == ["b"]

    def test_no_expectations_na(self):
        r = score_tools({}, ["anything"])
        assert r["any_hit"] is None and r["required_recall"] is None


class TestScoreCase:
    def _case(self):
        return {"id": "X1", "category": "cross_domain",
                "tools_any": ["search_bidding_knowledge"],
                "facts": [{"any": ["860万"]}, {"any": ["12月15日"]}]}

    def test_pass(self):
        r = score_case(self._case(), "预算860万，截止12月15日",
                       ["search_bidding_knowledge"])
        assert r["passed"] and r["tool_ok"] and r["fact_ok"]

    def test_tool_wrong_fails(self):
        r = score_case(self._case(), "预算860万，截止12月15日",
                       ["search_postgresql"])
        assert not r["passed"] and not r["tool_ok"] and r["fact_ok"]

    def test_fact_below_threshold_fails(self):
        r = score_case(self._case(), "只提到860万",
                       ["search_bidding_knowledge"], fact_threshold=0.6)
        # 两组中一组 → 0.5 < 0.6
        assert not r["passed"] and r["fact"]["hit_rate"] == 0.5

    def test_empty_answer_fails(self):
        r = score_case(self._case(), "", ["search_bidding_knowledge"])
        assert not r["passed"] and not r["answer_ok"]

    def test_no_facts_only_tool_gates(self):
        case = {"id": "X2", "category": "multi_hop",
                "tools_any": ["search_postgresql"]}
        r = score_case(case, "有内容的回答", ["search_postgresql"])
        assert r["passed"] and r["fact"]["hit_rate"] is None


class TestAggregate:
    def test_by_category(self):
        cases = [
            {"id": "A", "category": "single_hop", "tools_any": ["t1"], "facts": ["x"]},
            {"id": "B", "category": "single_hop", "tools_any": ["t1"], "facts": ["y"]},
            {"id": "C", "category": "cross_domain", "tools_any": ["t2"], "facts": ["z"]},
        ]
        results = [
            score_case(cases[0], "x", ["t1"]),
            score_case(cases[1], "miss", ["t1"]),
            score_case(cases[2], "z", ["t2"]),
        ]
        s = aggregate(results)
        assert s["overall"]["cases"] == 3 and s["overall"]["passed"] == 2
        assert s["overall"]["pass_rate"] == round(2 / 3, 4)
        assert s["by_category"]["single_hop"]["cases"] == 2
        assert s["by_category"]["single_hop"]["pass_rate"] == 0.5
        assert s["by_category"]["cross_domain"]["passed"] == 1
