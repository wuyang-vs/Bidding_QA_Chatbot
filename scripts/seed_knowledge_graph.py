"""知识图谱种子: 从 bidding_procurement 中标记录聚合生成子图.

数据流: PG 聚合 → Neo4j (与检索侧 search_knowledge_graph / 图谱可视化页同 schema):
  (SubjectMatter {name, tradeFrequency})-[:PURCHASED_BY]->(Purchaser)
  (SubjectMatter)-[:SUPPLIED_BY]->(Supplier)
  (Supplier)-[:COMPETES_WITH]->(Supplier)   # 同标的物竞争对手

幂等: MERGE 写入, 重复运行仅更新 tradeFrequency; --reset 先清空全图重建.
用法: .venv\\Scripts\\python.exe scripts\\seed_knowledge_graph.py [--reset]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import settings
from src.database.neo4j_client import neo4j_client
from src.database.postgresql_client import postgresql_client


def main() -> None:
    ap = argparse.ArgumentParser(description="从 PG 中标记录生成知识图谱子图")
    ap.add_argument("--reset", action="store_true", help="清空后重建")
    args = ap.parse_args()

    neo4j_client.initialize()
    postgresql_client.initialize()
    if not neo4j_client.ready:
        print("Neo4j 未就绪, 请检查 .env 中 NEO4J_* 配置与服务是否启动")
        sys.exit(1)
    if not postgresql_client.ready:
        print("PostgreSQL 未就绪")
        sys.exit(1)

    rows = postgresql_client._run(
        "SELECT subject_matter, purchaser, winning_bidder FROM bidding_procurement "
        "WHERE subject_matter IS NOT NULL AND subject_matter <> ''")
    if not rows:
        print("bidding_procurement 无数据, 请先运行 seed_bidding_procurement.py")
        sys.exit(1)

    freq: dict[str, int] = {}
    links: dict[str, dict] = {}
    for r in rows:
        sm = (r.get("subject_matter") or "").strip()
        if not sm:
            continue
        freq[sm] = freq.get(sm, 0) + 1
        d = links.setdefault(sm, {"p": set(), "s": set()})
        if r.get("purchaser"):
            d["p"].add(r["purchaser"].strip())
        if r.get("winning_bidder"):
            d["s"].add(r["winning_bidder"].strip())

    with neo4j_client._driver.session(database=settings.neo4j_database) as session:
        if args.reset:
            session.run("MATCH (n) DETACH DELETE n")
            print("已清空旧图")
        for sm, n in freq.items():
            session.run("MERGE (s:SubjectMatter {name:$name}) SET s.tradeFrequency=$freq",
                        name=sm, freq=n)
            for p in links[sm]["p"]:
                session.run("MERGE (p:Purchaser {name:$p}) "
                            "MERGE (s:SubjectMatter {name:$sm}) "
                            "MERGE (s)-[:PURCHASED_BY]->(p)", p=p, sm=sm)
            for sup in links[sm]["s"]:
                session.run("MERGE (x:Supplier {name:$x}) "
                            "MERGE (s:SubjectMatter {name:$sm}) "
                            "MERGE (s)-[:SUPPLIED_BY]->(x)", x=sup, sm=sm)
        session.run("MATCH (s:SubjectMatter)-[:SUPPLIED_BY]->(a:Supplier), "
                    "(s)-[:SUPPLIED_BY]->(b:Supplier) WHERE a.name < b.name "
                    "MERGE (a)-[:COMPETES_WITH]->(b)")
        nodes = session.run("MATCH (n) RETURN labels(n)[0] AS label, count(*) AS cnt ORDER BY label").data()
        rels = session.run("MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS c ORDER BY t").data()
    print("节点:", nodes)
    print("关系:", rels)


if __name__ == "__main__":
    main()
