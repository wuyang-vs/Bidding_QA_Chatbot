"""运行看板: feedback 汇总 + 检索缓存统计"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from src.database.postgresql_client import postgresql_client
from src.rag.pipeline import RAGPipeline


def main():
    postgresql_client.initialize()
    print("=" * 50)
    if postgresql_client.ready:
        rows = postgresql_client._run("SELECT COUNT(*) AS total FROM conversations")
        print(f"  总对话数     : {rows[0]['total'] if rows else 0}")
        fb = postgresql_client._run(
            "SELECT rating, COUNT(*) AS cnt FROM feedback GROUP BY rating")
        up = next((r["cnt"] for r in fb if r["rating"] == "up"), 0)
        down = next((r["cnt"] for r in fb if r["rating"] == "down"), 0)
        print(f"  用户反馈     : {up + down} 条")
        print(f"    👍 满意     : {up}")
        print(f"    👎 不满意   : {down}")
    else:
        print("  PostgreSQL 未连接")
    info = RAGPipeline.cache_info()
    print(f"  检索缓存     : {info}")
    print("=" * 50)


if __name__ == "__main__":
    main()
