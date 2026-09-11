"""LLM-as-Judge RAG 质量评估 (Faithfulness / Relevancy / Recall)"""
import json
import statistics
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from src.rag.pipeline import rag_pipeline
from src.clients.llm_factory import get_llm_client

QUESTIONS = json.loads((Path(__file__).parent / "test_questions.json").read_text(encoding="utf-8"))


def llm_score(prompt: str) -> float | None:
    llm = get_llm_client()
    try:
        out = llm.chat([{"role": "user", "content": prompt}])
        for token in out.split():
            try:
                return max(0.0, min(1.0, float(token.strip(".,%"))))
            except ValueError:
                continue
    except Exception:
        return None
    return None


def main():
    if not QUESTIONS:
        print("测试题目为空")
        return 1
    rag_pipeline.initialize()
    faith, rel, rec = [], [], []
    failures = []
    for i, q in enumerate(QUESTIONS, 1):
        try:
            result = rag_pipeline.ask(q, top_k=5)
            answer = result["answer"]
            contexts = "\n".join(d["answer"] for d in result["sources"])
            f = llm_score(f"答案是否忠于资料？0-1 打分，只输出数字。\n资料:{contexts}\n答案:{answer}")
            r = llm_score(f"答案是否回答了问题？0-1 打分，只输出数字。\n问题:{q}\n答案:{answer}")
            c = llm_score(f"资料是否包含回答问题所需信息？0-1 打分，只输出数字。\n问题:{q}\n资料:{contexts}")
            if f is not None: faith.append(f)
            if r is not None: rel.append(r)
            if c is not None: rec.append(c)
        except Exception as e:
            failures.append((i, q, str(e)))

    print("=" * 60)
    print(f"  测试用例: {len(QUESTIONS)}  有效 {len(faith)}")
    if faith: print(f"  Faithfulness : {statistics.mean(faith):.2f}")
    if rel:   print(f"  Relevancy    : {statistics.mean(rel):.2f}")
    if rec:   print(f"  Recall       : {statistics.mean(rec):.2f}")
    if failures:
        print(f"  失败用例: {len(failures)}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
