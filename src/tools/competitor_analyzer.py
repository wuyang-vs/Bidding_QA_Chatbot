"""竞争对手分析 — Neo4j 图谱 + PostgreSQL 聚合 + LLM 解读.

数据流:
  1. Neo4j: 供应商-标的物关系图 (关联哪些供应商、市场集中度、潜在竞品)
  2. PG: 中标供应商聚合 (中标次数、中标金额分布)
  3. LLM: 综合解读, 给出竞品画像

降级策略:
  - Neo4j 未连接 → 只用 PG
  - PG 未连接 → 只用 Neo4j
  - 都未 → 返回降级提示
"""
from __future__ import annotations

import logging
from typing import Any

from src.database.postgresql_client import postgresql_client
from src.database.neo4j_client import neo4j_client

logger = logging.getLogger(__name__)


def _convert_row(row: dict) -> dict:
    """把 Neo4j/PG 混合行统一转原生 Python 类型."""
    out = {}
    for k, v in row.items():
        if isinstance(v, list):
            out[k] = [str(x) for x in v]
        elif hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif hasattr(v, "__float__") and not isinstance(v, (int, float)):
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                out[k] = v
        else:
            out[k] = v
    return out


def analyze_competitors(
    subject_matter: str,
    top_n: int = 10,
    llm_client=None,
) -> dict[str, Any]:
    """执行竞争对手分析.

    Args:
        subject_matter: 标的物关键词 (如 "空调", "服务器", "办公软件")
        top_n: 返回 TOP N 供应商

    Returns:
        {
            "subject_matter": str,
            "top_suppliers": [PG 聚合, 含 win_count / avg_amount],
            "graph_competitors": [Neo4j 图查询, 含 subject_count / 潜在竞品],
            "market_concentration": [每个标的物的供应商数量],
            "data_sources": ["postgresql", "neo4j"],
            "llm_comment": str,
        }
    """
    pg_available = postgresql_client.ready
    neo_available = neo4j_client.ready

    result: dict[str, Any] = {
        "subject_matter": subject_matter,
        "top_suppliers": [],
        "graph_competitors": [],
        "market_concentration": [],
        "data_sources": [],
        "llm_comment": "",
    }

    if not pg_available and not neo_available:
        result["llm_comment"] = (
            "⚠️ PostgreSQL 和 Neo4j 均未连接, 无法进行竞争对手分析. "
            "请先部署数据库并导入数据."
        )
        return result

    # ---- PG: 中标 TOP N ----
    if pg_available:
        pg_rows = postgresql_client.query(
            "top_suppliers_by_subject", subject_matter=subject_matter, limit=top_n)
        result["top_suppliers"] = [_convert_row(r) for r in pg_rows]
        result["data_sources"].append("postgresql")

    # ---- Neo4j: 图谱查询 ----
    if neo_available:
        neo_competitors = neo4j_client.query(
            "top_competitors", keyword=subject_matter)
        result["graph_competitors"] = [_convert_row(r) for r in neo_competitors]

        neo_conc = neo4j_client.query(
            "market_concentration", keyword=subject_matter)
        result["market_concentration"] = [_convert_row(r) for r in neo_conc]

        neo_suppliers = neo4j_client.query(
            "suppliers_for_subject", keyword=subject_matter)
        result["graph_suppliers_flat"] = [_convert_row(r) for r in neo_suppliers]

        result["data_sources"].append("neo4j")

    # ---- LLM 解读 ----
    if llm_client is None:
        from src.clients.llm_factory import get_llm_client
        llm_client = get_llm_client()

    try:
        result["llm_comment"] = _llm_interpret(subject_matter, result, llm_client)
    except Exception as e:
        logger.warning("LLM 竞争对手解读失败: %s", e)
        result["llm_comment"] = "（LLM 解读暂时不可用, 以上数据可直接参考）"

    return result


def _llm_interpret(
    subject: str, data: dict, llm_client,
) -> str:
    top_suppliers = data.get("top_suppliers", [])
    competitors = data.get("graph_competitors", [])
    concentration = data.get("market_concentration", [])

    pg_text = ""
    for s in top_suppliers[:5]:
        pg_text += (
            f"  - {s.get('supplier')}: 中标{s.get('win_count')}次, "
            f"均价{s.get('avg_amount')}元, 总额{s.get('total_amount')}元\n"
        )

    neo_text = ""
    for c in competitors[:5]:
        neo_text += (
            f"  - {c.get('supplier')}: 覆盖{c.get('subject_count')}个标的物, "
            f"潜在竞品: {c.get('competitors', [])[:3]}\n"
        )

    conc_text = ""
    for c in concentration[:5]:
        conc_text += f"  - {c.get('subject')}: {c.get('supplier_count')} 家供应商\n"

    prompt = (
        f"【分析标的物】{subject}\n\n"
        f"【中标供应商 TOP 5 (来自 PostgreSQL)】\n{pg_text or '  (无数据)'}\n\n"
        f"【图谱视角: 竞品覆盖 (来自 Neo4j)】\n{neo_text or '  (无数据)'}\n\n"
        f"【市场集中度 (每个标的物的供应商数量)】\n{conc_text or '  (无数据)'}\n\n"
        f"请用 250-350 字输出:\n"
        f"1. 竞品格局 (是否垄断、主要竞争者)\n"
        f"2. 市场集中度 (是否充分竞争)\n"
        f"3. 潜在合作伙伴 (中标次数少但价格有竞争力)\n"
        f"4. 投标策略建议 (正面竞争 / 差异化 / 联盟)\n\n"
        f"用 Markdown, 数据引用要准确."
    )
    return llm_client.chat([
        {"role": "system", "content": "你是招投标市场分析专家, 擅长从供应商图谱和中标数据解读竞争格局."},
        {"role": "user", "content": prompt},
    ], temperature=0.3)
