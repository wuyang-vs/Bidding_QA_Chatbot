from __future__ import annotations
"""标书生成共享服务: 招标信息解析 + 同类案例检索.

供 HTTP 端点 (/api/bid/*) 与 Agent 工具复用, 保证两条链路的
行级权限、案例过滤行为一致。
"""
import logging

logger = logging.getLogger(__name__)


def row_to_tender(row: dict) -> dict:
    return {
        "project_name": row.get("project_name") or "",
        "project_code": row.get("project_code") or "",
        "purchaser": row.get("purchaser") or "",
        "subject_matter": row.get("subject_matter") or "",
        "budget": row.get("budget") or "",
        "qualification_requirements": row.get("qualification_requirements") or [],
        "scoring_criteria": row.get("scoring_criteria") or "",
        "deadline": row.get("deadline") or "",
    }


def resolve_tender(db_id: int | None, manual: dict | None = None,
                   include_raw: bool = False) -> dict:
    """db_id 优先从 PG 取完整招标信息; 取不到时回退到请求体手填字段。

    注意: 调用方必须先完成 _assert_doc_readable 行级校验。
    include_raw=True 时额外带 raw_text (响应对照矩阵用)。
    """
    manual = manual or {}
    if db_id is not None:
        from src.database.postgresql_client import postgresql_client
        if postgresql_client.ready:
            rows = postgresql_client._run(
                "SELECT * FROM bidding_documents WHERE id = :id", {"id": db_id})
            if rows:
                tender = row_to_tender(rows[0])
                if include_raw:
                    tender["raw_text"] = rows[0].get("raw_text") or ""
                return tender
    tender = {
        "project_name": manual.get("project_name", ""),
        "project_code": manual.get("project_code", ""),
        "purchaser": manual.get("purchaser", ""),
        "subject_matter": manual.get("subject_matter", ""),
        "budget": manual.get("budget", ""),
        "qualification_requirements": manual.get("qualification_requirements") or [],
        "scoring_criteria": manual.get("scoring_criteria", ""),
        "deadline": manual.get("deadline", ""),
    }
    if include_raw:
        tender["raw_text"] = manual.get("raw_text", "")
    return tender


def fetch_similar_cases(tender: dict, user: dict | None, top_k: int = 3) -> list[dict]:
    """按当前用户行级范围检索同类投标案例; 失败不阻断主流程。"""
    from src.rag.pipeline import rag_pipeline
    from src.auth.access_scope import use_access_scope
    if not (rag_pipeline.ready and tender.get("subject_matter")):
        return []
    try:
        with use_access_scope(user):
            return rag_pipeline.search(
                f"{tender['subject_matter']} 采购 投标 技术方案",
                top_k=top_k)[:top_k]
    except Exception as e:
        logger.warning("同类案例检索失败: %s", e)
        return []
