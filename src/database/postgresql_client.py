from __future__ import annotations
"""PostgreSQL 查询 (6 类模板) + 会话/反馈 CRUD"""
import logging
import threading

from sqlalchemy import create_engine, text

from src.config import settings

logger = logging.getLogger(__name__)


class PostgreSQLQueryError(Exception):
    pass


ALLOWED_FIELDS = {
    "title", "project_name", "subject_matter", "purchaser",
    "winning_bidder", "project_code", "publish_time", "winning_time",
    "winning_amount", "agency", "location",
}
AGG_FUNCS = {"count", "sum", "avg", "max", "min", "stddev"}
TEXT_FIELDS = ["title", "project_name", "subject_matter", "purchaser", "winning_bidder"]


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class PostgreSQLClient:
    def __init__(self):
        self._engine = None
        self._ready = False
        self._lock = threading.Lock()

    def initialize(self) -> None:
        try:
            url = (f"postgresql+psycopg://{settings.postgres_user}:{settings.postgres_password}"
                   f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}")
            self._engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3})
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            self._init_feedback_table()
            self._ready = True
        except Exception as e:
            logger.warning("PostgreSQL 连接失败(降级): %s", e)
            self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    def _init_feedback_table(self) -> None:
        try:
            with self._engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY,
                        username TEXT UNIQUE NOT NULL,
                        password_hash TEXT NOT NULL,
                        role TEXT DEFAULT 'auditor',  -- admin / auditor / bidder
                        display_name TEXT DEFAULT '',
                        created_at TIMESTAMP DEFAULT NOW())
                """))
                # 默认管理员 (密码 admin123, hash 首次启动写入)
                conn.execute(text("""
                    INSERT INTO users (username, password_hash, role, display_name)
                    SELECT 'admin', '$2b$12$placeholder', 'admin', '系统管理员'
                    WHERE NOT EXISTS (SELECT 1 FROM users WHERE username='admin')
                """))
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS conversations (
                        session_id TEXT PRIMARY KEY,
                        title TEXT DEFAULT '',
                        messages JSONB DEFAULT '[]'::jsonb,
                        created_at TIMESTAMP DEFAULT NOW(),
                        updated_at TIMESTAMP DEFAULT NOW())
                """))
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS feedback (
                        id SERIAL PRIMARY KEY,
                        session_id TEXT, question TEXT, answer TEXT,
                        rating TEXT, created_at TIMESTAMP DEFAULT NOW())
                """))
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS bidding_documents (
                        id SERIAL PRIMARY KEY,
                        source_file TEXT NOT NULL,
                        source_path TEXT,
                        project_name TEXT,
                        project_code TEXT,
                        purchaser TEXT,
                        agency TEXT,
                        subject_matter TEXT,
                        budget TEXT,
                        qualification_requirements JSONB DEFAULT '[]'::jsonb,
                        scoring_criteria TEXT,
                        deadline TEXT,
                        opening_time TEXT,
                        location TEXT,
                        raw_text_preview TEXT,
                        raw_text TEXT,
                        parse_status TEXT,
                        text_length INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT NOW()
                    )
                """))
                # 兼容已有库: 补充全文列
                conn.execute(text(
                    "ALTER TABLE bidding_documents ADD COLUMN IF NOT EXISTS raw_text TEXT"))
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_bd_project_name
                    ON bidding_documents USING gin (to_tsvector('simple', COALESCE(project_name, '')))
                """))
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS document_reviews (
                        id SERIAL PRIMARY KEY,
                        document_id INTEGER REFERENCES bidding_documents(id) ON DELETE CASCADE,
                        review_type TEXT NOT NULL,
                        verdict TEXT NOT NULL,
                        comment TEXT DEFAULT '',
                        reviewer TEXT DEFAULT '',
                        result_snapshot JSONB,
                        created_at TIMESTAMP DEFAULT NOW())
                """))
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_dr_doc
                    ON document_reviews (document_id, review_type, created_at DESC)
                """))
                conn.execute(text(
                    "ALTER TABLE document_reviews ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE SET NULL"))
        except PostgreSQLQueryError:
            pass

    def _run(self, sql: str, params: dict | None = None) -> list[dict]:
        if not self._ready:
            raise PostgreSQLQueryError("PostgreSQL 未连接")
        try:
            with self._engine.begin() as conn:
                result = conn.execute(text(sql), params or {})
                if result.returns_rows:
                    return [dict(r._mapping) for r in result]
                return []
        except Exception as e:
            raise PostgreSQLQueryError(str(e)) from e

    def query(self, query_type: str, **kwargs) -> list[dict]:
        try:
            return self._query_inner(query_type, **kwargs)
        except PostgreSQLQueryError as e:
            return {"success": False, "error": str(e), "results": []}

    def _query_inner(self, query_type: str, **kwargs) -> list[dict]:
        if query_type == "search_by_keyword":
            kw = _escape_like(kwargs.get("keyword", ""))
            conds = " OR ".join(f"{f} ILIKE '%{kw}%' ESCAPE '\\'" for f in TEXT_FIELDS)
            rows = self._run(f"SELECT * FROM bidding_procurement WHERE {conds} LIMIT 20")
            if not rows and len(kwargs.get("keyword", "")) >= 3:
                rev = " OR ".join(
                    f"(char_length({f}) >= 3 AND '{kw}' ILIKE '%' || {f} || '%')"
                    for f in ("title", "project_name"))
                rows = self._run(f"SELECT * FROM bidding_procurement WHERE {rev} LIMIT 20")
            return rows

        if query_type == "filter_by_field":
            field = kwargs.get("field", "")
            if field not in ALLOWED_FIELDS:
                raise PostgreSQLQueryError(f"不允许的字段: {field}")
            value = _escape_like(kwargs.get("value", ""))
            return self._run(
                f"SELECT * FROM bidding_procurement WHERE {field} ILIKE '%{value}%' ESCAPE '\\' LIMIT 20")

        if query_type == "aggregate_stats":
            agg = kwargs.get("agg", "count").lower()
            field = kwargs.get("field", "winning_amount")
            if agg not in AGG_FUNCS or field not in ALLOWED_FIELDS:
                raise PostgreSQLQueryError("聚合函数或字段不合法")
            return self._run(f"SELECT {agg}({field}) AS result FROM bidding_procurement")

        if query_type == "top_by_amount":
            return self._run(
                "SELECT project_name, winning_amount FROM bidding_procurement "
                "WHERE winning_amount IS NOT NULL ORDER BY winning_amount DESC LIMIT 10")

        if query_type == "group_by_field":
            field = kwargs.get("field", "purchaser")
            if field not in ALLOWED_FIELDS:
                raise PostgreSQLQueryError(f"不允许的字段: {field}")
            return self._run(
                f"SELECT {field}, COUNT(*) AS cnt, AVG(winning_amount) AS avg_amount "
                f"FROM bidding_procurement GROUP BY {field} ORDER BY cnt DESC LIMIT 20")

        if query_type == "time_range":
            start = kwargs.get("start", "")
            end = kwargs.get("end", "")
            return self._run(
                "SELECT * FROM bidding_procurement WHERE publish_time >= :s AND publish_time <= :e LIMIT 50",
                {"s": start, "e": end})

        if query_type == "price_distribution":
            """标的物价格分布: count/avg/min/max/stddev + P25/P50/P75/P90."""
            subject = _escape_like(kwargs.get("subject_matter", ""))
            cond = f"subject_matter ILIKE '%{subject}%' ESCAPE '\\'" if subject else "1=1"
            return self._run(f"""
                SELECT COUNT(*) AS cnt, AVG(winning_amount) AS avg_amount,
                       MIN(winning_amount) AS min_amount, MAX(winning_amount) AS max_amount,
                       STDDEV(winning_amount) AS stddev_amount,
                       PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY winning_amount) AS p25,
                       PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY winning_amount) AS p50,
                       PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY winning_amount) AS p75,
                       PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY winning_amount) AS p90
                FROM bidding_procurement
                WHERE winning_amount IS NOT NULL AND {cond}
            """)

        if query_type == "price_trend":
            """按月/年聚合中标金额趋势."""
            subject = _escape_like(kwargs.get("subject_matter", ""))
            granularity = kwargs.get("granularity", "month").lower()
            period_sql = (
                "DATE_TRUNC('month', winning_time)" if granularity == "month"
                else "DATE_TRUNC('year', winning_time)"
            )
            cond = f"subject_matter ILIKE '%{subject}%' ESCAPE '\\'" if subject else "1=1"
            return self._run(f"""
                SELECT {period_sql} AS period,
                       COUNT(*) AS cnt,
                       AVG(winning_amount) AS avg_amount,
                       SUM(winning_amount) AS total_amount
                FROM bidding_procurement
                WHERE winning_amount IS NOT NULL AND {cond}
                  AND winning_time IS NOT NULL
                GROUP BY period
                ORDER BY period DESC
                LIMIT 24
            """)

        if query_type == "top_suppliers_by_subject":
            """某标的物的中标供应商 TOP N."""
            subject = _escape_like(kwargs.get("subject_matter", ""))
            limit = kwargs.get("limit", 10)
            cond = f"subject_matter ILIKE '%{subject}%' ESCAPE '\\'" if subject else "1=1"
            return self._run(f"""
                SELECT winning_bidder AS supplier,
                       COUNT(*) AS win_count,
                       AVG(winning_amount) AS avg_amount,
                       SUM(winning_amount) AS total_amount,
                       MIN(winning_amount) AS min_amount,
                       MAX(winning_amount) AS max_amount
                FROM bidding_procurement
                WHERE winning_amount IS NOT NULL AND {cond} AND winning_bidder IS NOT NULL
                  AND winning_bidder != ''
                GROUP BY winning_bidder
                ORDER BY win_count DESC, total_amount DESC
                LIMIT {int(limit)}
            """)

        raise PostgreSQLQueryError(f"未知查询类型: {query_type}")

    def save_conversation(self, session_id: str, title: str, messages: list) -> None:
        import json
        self._run("""
            INSERT INTO conversations (session_id, title, messages, updated_at)
            VALUES (:sid, :title, CAST(:messages AS jsonb), NOW())
            ON CONFLICT (session_id) DO UPDATE
            SET messages = CAST(:messages AS jsonb),
                title = COALESCE(NULLIF(:title, ''), conversations.title),
                updated_at = NOW()
        """, {"sid": session_id, "title": title,
              "messages": json.dumps(messages, ensure_ascii=False)})

    def list_conversations(self, q: str = "") -> list[dict]:
        if q:
            kw = _escape_like(q)
            return self._run(
                "SELECT session_id, title, updated_at FROM conversations "
                "WHERE messages::text ILIKE '%' || :q || '%' ESCAPE '\\' "
                "OR title ILIKE '%' || :q || '%' ESCAPE '\\' ORDER BY updated_at DESC",
                {"q": kw})
        return self._run(
            "SELECT session_id, title, updated_at FROM conversations ORDER BY updated_at DESC")

    def load_conversation(self, session_id: str) -> list:
        rows = self._run("SELECT messages FROM conversations WHERE session_id = :sid",
                         {"sid": session_id})
        return rows[0]["messages"] if rows else []

    def delete_conversation(self, session_id: str) -> None:
        self._run("DELETE FROM conversations WHERE session_id = :sid", {"sid": session_id})

    def delete_all_conversations(self) -> None:
        self._run("DELETE FROM conversations")

    def save_feedback(self, session_id, question, answer, rating) -> None:
        self._run("INSERT INTO feedback (session_id, question, answer, rating) "
                  "VALUES (:s, :q, :a, :r)",
                  {"s": session_id, "q": question, "a": answer, "r": rating})

    def save_document(self, parsed: dict) -> int:
        """保存解析后的招标文件到 bidding_documents, 返回 id."""
        import json as _json
        qr = parsed.get("qualification_requirements") or []
        if isinstance(qr, str):
            qr = [qr]
        rows = self._run("""
            INSERT INTO bidding_documents
            (source_file, source_path, project_name, project_code, purchaser, agency,
             subject_matter, budget, qualification_requirements, scoring_criteria,
             deadline, opening_time, location, raw_text_preview, raw_text,
             parse_status, text_length)
            VALUES
            (:sf, :sp, :pn, :pc, :pu, :ag, :sm, :bg, CAST(:qr AS jsonb), :sc,
             :dl, :ot, :lo, :rp, :rt, :ps, :tl)
            RETURNING id
        """, {
            "sf": parsed.get("source_file", ""),
            "sp": parsed.get("source_path", ""),
            "pn": parsed.get("project_name"),
            "pc": parsed.get("project_code"),
            "pu": parsed.get("purchaser"),
            "ag": parsed.get("agency"),
            "sm": parsed.get("subject_matter"),
            "bg": parsed.get("budget"),
            "qr": _json.dumps(qr, ensure_ascii=False),
            "sc": parsed.get("scoring_criteria"),
            "dl": parsed.get("deadline"),
            "ot": parsed.get("opening_time"),
            "lo": parsed.get("location"),
            "rp": parsed.get("raw_text_preview"),
            "rt": parsed.get("raw_text"),
            "ps": parsed.get("parse_status", "unknown"),
            "tl": parsed.get("text_length", 0),
        })
        return rows[0]["id"] if rows else -1

    def list_documents(self, q: str = "") -> list[dict]:
        cols = ("id, source_file, project_name, purchaser, budget, deadline, "
                "parse_status, text_length, qualification_requirements, "
                "scoring_criteria, created_at")
        if q:
            kw = _escape_like(q)
            return self._run(
                f"SELECT {cols} FROM bidding_documents "
                "WHERE project_name ILIKE '%' || :q || '%' ESCAPE '\\' "
                "OR source_file ILIKE '%' || :q || '%' ESCAPE '\\' "
                "ORDER BY created_at DESC",
                {"q": kw})
        return self._run(
            f"SELECT {cols} FROM bidding_documents ORDER BY created_at DESC")

    # ---------- 人工复核 (审计留痕) ----------

    def save_review(self, document_id: int, review_type: str, verdict: str,
                    comment: str = "", reviewer: str = "",
                    result_snapshot: dict | None = None,
                    user_id: int | None = None) -> int:
        """保存一条人工复核记录, 返回 id."""
        import json as _json
        rows = self._run("""
            INSERT INTO document_reviews
            (document_id, review_type, verdict, comment, reviewer, result_snapshot, user_id)
            VALUES
            (:did, :rt, :v, :c, :r, CAST(:snap AS jsonb), :uid)
            RETURNING id
        """, {
            "did": document_id,
            "rt": review_type,
            "v": verdict,
            "c": comment or "",
            "r": reviewer or "",
            "snap": _json.dumps(result_snapshot or {}, ensure_ascii=False),
            "uid": user_id,
        })
        return rows[0]["id"] if rows else -1

    def list_reviews(self, document_id: int | None = None,
                     review_type: str | None = None,
                     limit: int = 100) -> list[dict]:
        """查询复核记录 (可按文档/类型过滤), 新记录在前."""
        conds, params = [], {}
        if document_id is not None:
            conds.append("document_id = :did")
            params["did"] = document_id
        if review_type:
            conds.append("review_type = :rt")
            params["rt"] = review_type
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        params["lim"] = limit
        return self._run(
            f"SELECT id, document_id, review_type, verdict, comment, reviewer, "
            f"user_id, created_at FROM document_reviews {where} "
            f"ORDER BY created_at DESC LIMIT :lim", params)


postgresql_client = PostgreSQLClient()
