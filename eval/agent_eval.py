"""Agent 端到端评估: 工具选择准确率 + 延迟"""
import json
import statistics
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from src.agent.core import bidding_agent

CASES = json.loads((Path(__file__).parent / "test_cases.json").read_text(encoding="utf-8"))


def main():
    if not CASES:
        print("测试用例为空")
        return 1
    bidding_agent.initialize()
    correct, latencies, failures = 0, [], []
    for i, case in enumerate(CASES, 1):
        try:
            t0 = time.time()
            result = bidding_agent.chat(case["question"])
            latencies.append(time.time() - t0)
            if result.get("tool_name") == case.get("expected_tool", ""):
                correct += 1
        except Exception as e:
            failures.append((i, case["question"], str(e)))

    total = len(CASES)
    print("=" * 60)
    print(f"  测试用例     : {total}")
    print(f"  工具选择准确率: {correct}/{total} ({correct/total*100:.0f}%)")
    if latencies:
        print(f"  平均延迟     : {statistics.mean(latencies):.1f}s")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
