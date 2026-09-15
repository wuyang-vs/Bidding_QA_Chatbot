"""快速评测: Recall@20 (基于 test.xlsx 自举 ground truth)"""
import sys
sys.path.insert(0, r"d:\Bidding_QA_Chatbot")

import pandas as pd
from src.rag.pipeline import rag_pipeline

df = pd.read_excel(r"d:\Bidding_QA_Chatbot\data\test.xlsx")
corpus = df.to_dict("records")

# 自举 ground truth: 每条 corpus 的 question 作为 query, 期望答案就是它自己
test_set = [{"question": c["question"], "gt_question": c["question"]} for c in corpus]

recalls_5 = []
recalls_10 = []
recalls_20 = []

for tc in test_set:
    q = tc["question"]
    gt_q = tc["gt_question"]
    results = rag_pipeline.search(q, top_k=20)
    retrieved_qs = [r.get("question", "") for r in results]

    r5 = int(gt_q in retrieved_qs[:5])
    r10 = int(gt_q in retrieved_qs[:10])
    r20 = int(gt_q in retrieved_qs[:20])
    recalls_5.append(r5)
    recalls_10.append(r10)
    recalls_20.append(r20)
    print(f"  Q: \"{q}\"")
    print(f"    top5  hit={r5}  top10 hit={r10}  top20 hit={r20}")

n = len(test_set)
print(f"\n=== Recall@5  = {sum(recalls_5)/n:.1%} ===")
print(f"=== Recall@10 = {sum(recalls_10)/n:.1%} ===")
print(f"=== Recall@20 = {sum(recalls_20)/n:.1%} ===")
print(f"({sum(recalls_20)}/{n})")
