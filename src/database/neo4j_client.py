from __future__ import annotations
"""Neo4j 图谱查询 (6 类模板)"""
import logging
from neo4j import GraphDatabase

from src.config import settings

logger = logging.getLogger(__name__)

QUERIES = {
    "search_entity": """
        MATCH (n) WHERE (n:SubjectMatter OR n:Purchaser OR n:Supplier)
          AND n.name CONTAINS $keyword
        RETURN labels(n)[0] AS type, n.name AS name LIMIT 20
    """,
    "items_by_entity": """
        MATCH (s:SubjectMatter)-[r]->(e) WHERE e.name CONTAINS $keyword
        RETURN s.name AS subject_matter, type(r) AS relation, e.name AS entity LIMIT 30
    """,
    "top_traded": """
        MATCH (s:SubjectMatter) RETURN s.name AS name, s.tradeFrequency AS freq
        ORDER BY freq DESC LIMIT 10
    """,
    "entity_detail": """
        MATCH (s:SubjectMatter {name: $keyword})
        OPTIONAL MATCH (s)-[:PURCHASED_BY]->(p:Purchaser)
        OPTIONAL MATCH (s)-[:SUPPLIED_BY]->(sup:Supplier)
        RETURN s.name AS subject, collect(DISTINCT p.name) AS purchasers,
               collect(DISTINCT sup.name) AS suppliers LIMIT 5
    """,
    "list_entities": """
        MATCH (s:SubjectMatter) RETURN s.name AS name, s.tradeFrequency AS freq
        ORDER BY freq DESC LIMIT 30
    """,
    "graph_stats": """
        MATCH (n) RETURN labels(n)[0] AS label, count(*) AS cnt
    """,
    # --- 竞争对手分析 ---
    "suppliers_for_subject": """
        MATCH (sup:Supplier)-[:SUPPLIED_BY]->(s:SubjectMatter)
        WHERE s.name CONTAINS $keyword
        RETURN sup.name AS supplier, count(*) AS related_relations
        ORDER BY related_relations DESC LIMIT 15
    """,
    "top_competitors": """
        MATCH (competitor:Supplier)-[:SUPPLIED_BY]->(sm:SubjectMatter)
        OPTIONAL MATCH (competitor)-[:COMPETES_WITH]->(peer:Supplier)
        WHERE sm.name CONTAINS $keyword
        RETURN competitor.name AS supplier, collect(DISTINCT sm.name) AS subjects,
               count(DISTINCT sm) AS subject_count,
               collect(DISTINCT peer.name) AS competitors
        ORDER BY subject_count DESC LIMIT 10
    """,
    "market_concentration": """
        MATCH (sup:Supplier)-[:SUPPLIED_BY]->(s:SubjectMatter)
        WHERE s.name CONTAINS $keyword
        WITH s, collect(DISTINCT sup.name) AS suppliers
        RETURN s.name AS subject, size(suppliers) AS supplier_count, suppliers
        ORDER BY supplier_count DESC LIMIT 10
    """,
}


class Neo4jClient:
    def __init__(self):
        self._driver = None
        self._ready = False

    def initialize(self) -> None:
        try:
            self._driver = GraphDatabase.driver(
                settings.neo4j_uri, auth=(settings.neo4j_username, settings.neo4j_password),
                max_connection_pool_size=50, max_connection_lifetime=3600,
                connection_timeout=60)
            self._driver.verify_connectivity()
            self._ready = True
        except Exception as e:
            logger.warning("Neo4j 连接失败(降级): %s", e)
            self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    def query(self, query_type: str, **kwargs) -> list[dict]:
        if not self._ready or query_type not in QUERIES:
            return []
        try:
            with self._driver.session(database=settings.neo4j_database) as session:
                tx = session.begin_transaction(timeout=30)
                try:
                    result = tx.run(QUERIES[query_type], **kwargs)
                    rows = [dict(r) for r in result]
                    tx.commit()
                    return rows
                finally:
                    tx.close()
        except Exception as e:
            logger.warning("Neo4j 查询失败: %s", e)
            return []


neo4j_client = Neo4jClient()
