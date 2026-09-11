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
AGG_FUNCS = {"count", "sum", "avg", "max", "min"}
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
        except PostgreSQLQueryError:
            pass

    def _run(self, sql: str, params: dict | None = None) -> list[dict]:
        if not self._ready:
            raise PostgreSQLQueryError("PostgreSQL 未连接")
        try:
            with self._engine.connect() as conn:
                result = conn.execute(text(sql), params or {})
                rows = [dict(r._mapping) for r in result]
                conn.commit()
                return rows
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


postgresql_client = PostgreSQLClient()
