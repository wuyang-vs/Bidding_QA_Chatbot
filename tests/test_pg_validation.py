"""PostgreSQL 客户端: 字段白名单 / LIKE 转义 / 查询类型路由 / 错误包装"""
import os
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from unittest.mock import MagicMock, patch

from src.database.postgresql_client import (
    PostgreSQLClient, PostgreSQLQueryError,
    _escape_like, ALLOWED_FIELDS, AGG_FUNCS, TEXT_FIELDS,
)


# ---- _escape_like ----

def test_escape_like_backslash():
    assert _escape_like("a\\b") == "a\\\\b"

def test_escape_like_percent():
    assert _escape_like("100%") == "100\\%"

def test_escape_like_underscore():
    assert _escape_like("a_b") == "a\\_b"

def test_escape_like_combined():
    assert _escape_like("a%b_c\\d") == "a\\%b\\_c\\\\d"


# ---- 字段白名单 ----

def test_allowed_fields_contains_text_fields():
    for f in TEXT_FIELDS:
        assert f in ALLOWED_FIELDS


def test_agg_funcs_set():
    assert AGG_FUNCS == {"count", "sum", "avg", "max", "min", "stddev"}


# ---- 查询类型路由 (未连接时应抛 PostgreSQLQueryError) ----

def test_query_when_not_ready_returns_error_dict():
    """未连接时 query() 应返回 {"success": False, ...} 而非抛异常"""
    pg = PostgreSQLClient()
    pg._ready = False
    out = pg.query("search_by_keyword", keyword="x")
    assert isinstance(out, dict)
    assert out["success"] is False


def test_query_inner_unknown_type_raises():
    """未知 query_type 应抛 PostgreSQLQueryError"""
    pg = PostgreSQLClient()
    pg._ready = True
    pg._engine = MagicMock()
    try:
        pg._query_inner("nonexistent_type")
        assert False, "应抛 PostgreSQLQueryError"
    except PostgreSQLQueryError as e:
        assert "未知查询类型" in str(e)


def test_filter_by_field_rejects_disallowed():
    """filter_by_field 拒绝白名单外字段"""
    pg = PostgreSQLClient()
    pg._ready = True
    pg._engine = MagicMock()
    try:
        pg._query_inner("filter_by_field", field="malicious", value="x")
        assert False
    except PostgreSQLQueryError as e:
        assert "不允许的字段" in str(e)


def test_filter_by_field_accepts_allowed():
    """白名单内字段应通过, 不抛异常 (但 _run 会因 mock 失败, 捕获)"""
    pg = PostgreSQLClient()
    pg._ready = True
    pg._engine = MagicMock()
    conn = MagicMock()
    conn.execute.return_value = []
    pg._engine.connect.return_value.__enter__ = lambda self: conn
    pg._engine.connect.return_value.__exit__ = lambda *a: None
    out = pg._query_inner("filter_by_field", field="title", value="招标")
    assert out == []


def test_aggregate_rejects_bad_func():
    pg = PostgreSQLClient()
    pg._ready = True
    pg._engine = MagicMock()
    try:
        pg._query_inner("aggregate_stats", agg="drop", field="winning_amount")
        assert False
    except PostgreSQLQueryError:
        pass


def test_aggregate_rejects_bad_field():
    pg = PostgreSQLClient()
    pg._ready = True
    pg._engine = MagicMock()
    try:
        pg._query_inner("aggregate_stats", agg="sum", field="password")
        assert False
    except PostgreSQLQueryError:
        pass


def test_group_by_rejects_disallowed():
    pg = PostgreSQLClient()
    pg._ready = True
    pg._engine = MagicMock()
    try:
        pg._query_inner("group_by_field", field="secret_col")
        assert False
    except PostgreSQLQueryError as e:
        assert "不允许的字段" in str(e)


# ---- 会话/反馈 CRUD (未连接应抛异常) ----

def test_save_conversation_not_ready_raises():
    pg = PostgreSQLClient()
    pg._ready = False
    try:
        pg.save_conversation("s1", "t", [])
        assert False
    except PostgreSQLQueryError:
        pass


def test_list_conversations_not_ready_raises():
    pg = PostgreSQLClient()
    pg._ready = False
    try:
        pg.list_conversations()
        assert False
    except PostgreSQLQueryError:
        pass


# ---- query() 包装层 ----

def test_query_wraps_pg_query_error():
    """_query_inner 抛 PostgreSQLQueryError 应被 query() 包装为 dict"""
    pg = PostgreSQLClient()
    pg._ready = True
    pg._engine = MagicMock()
    out = pg.query("filter_by_field", field="badfield", value="x")
    assert out["success"] is False
    assert "不允许的字段" in out["error"]
