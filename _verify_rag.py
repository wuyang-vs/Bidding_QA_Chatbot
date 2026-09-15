"""快速验证 RAG 检索: 用真实招投标问题测试 Qdrant + RRF + CrossEncoder 链路"""
import sys, time
sys.path.insert(0, r"d:\Bidding_QA_Chatbot")

from src.config import settings
from src.rag.embedder import embedder
from src.rag.vector_store import vector_store

QUERIES = [
    "国家广播电视总局282台的预算金额是多少？",
    "北京交通大学雄安校区智慧校园项目什么时候开标？",
    "遂宁市消防救援支队食材配送项目采购单位是谁？",
    "什么是废标？",  # 超出 ccgp 数据, 应该返回空或低质量
    "吉林大学中日联谊医院保安服务项目开标地点在哪里？",
    "大连理工大学数字化机器人手术实验平台代理机构？",
]

def main():
    print("=" * 70)
    print("🔍 RAG 检索验证 (BGE-M3 + RRF + bge-reranker-v2-m3)")
    print("=" * 70)

    # 1. 检查 Qdrant
    vc = vector_store._get_client()
    info = vc.get_collection(settings.qdrant_collection)
    print(f"\n📦 Qdrant: {info.points_count} points")

    # 2. 预热模型
    print("\n⏳ 预热嵌入模型 ...")
    _ = embedder.encode_query_dense("预热")
    print("   Dense OK")
    embedder.fit_sparse(["预热"])
    print("   Sparse OK")
    _ = embedder.rerank("预热", [{"answer": "测试"}], top_k=1)
    print("   Reranker OK")

    # 3. 逐条测试
    print("\n" + "=" * 70)
    print("🧪 检索测试")
    print("=" * 70)

    for q in QUERIES:
        print(f"\n❓ Q: {q}")
        t0 = time.time()

        # 编码
        dense = embedder.encode_query_dense(q)
        sparse = embedder.encode_query_sparse(q)

        # 混合检索 + RRF
        results = vector_store.hybrid_search(
            query_dense=dense, query_sparse=sparse,
            limit=6, question=q,
        )

        # CrossEncoder 精排
        results = embedder.rerank(q, results, top_k=3)

        dt = time.time() - t0
        print(f"   ⏱️  耗时 {dt:.1f}s")

        for i, r in enumerate(results):
            ans = r.get("answer", "")[:60]
            scr = r.get("score", 0)
            src = r.get("source_file", "")
            title = r.get("section_title", "")[:30]
            print(f"   [{i+1}] score={scr:.3f}  src={src}  title={title}")
            print(f"       A: {ans}")

        # 验证
        if "废标" in q:
            if not results or results[0]["score"] < 0.3:
                print("   ✅ 正确: 非招投标知识返回低质量结果 (边界诚实)")
            else:
                print("   ⚠️  异常: 非招投标问题也检索到高相关结果")
        else:
            if results and results[0]["score"] > 0.3:
                print(f"   ✅ 命中: top1 score={results[0]['score']:.3f}")
            else:
                print("   ❌ 未命中: top1 score 过低")

    print("\n" + "=" * 70)
    print("✅ 检索验证完成")

if __name__ == "__main__":
    main()
