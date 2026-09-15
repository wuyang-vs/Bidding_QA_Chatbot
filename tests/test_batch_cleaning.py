"""批量导入数据清洗: read_qa_data 列名映射 / 空值过滤 / 去重"""
import os
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

import pandas as pd

from src.rag.ingest import read_qa_data


def _write_xlsx(tmp_path, df, name="t.xlsx"):
    p = tmp_path / name
    df.to_excel(p, index=False)
    return p


def _unwrap(df_meta):
    """read_qa_data 现在返回 (df, meta) tuple, 测试只需要 df."""
    return df_meta[0]


def test_standard_columns_question_answer(tmp_path):
    """标准 question/answer 列名"""
    df = pd.DataFrame({"question": ["Q1"], "answer": ["A1"]})
    p = _write_xlsx(tmp_path, df)
    out = _unwrap(read_qa_data(p))
    assert len(out) == 1
    assert out.iloc[0]["question"] == "Q1"
    assert out.iloc[0]["answer"] == "A1"


def test_chinese_columns_wen_da(tmp_path):
    """中文 问/答 列名"""
    df = pd.DataFrame({"问": ["Q1"], "答": ["A1"]})
    p = _write_xlsx(tmp_path, df)
    out = _unwrap(read_qa_data(p))
    assert len(out) == 1
    assert out.iloc[0]["question"] == "Q1"


def test_chinese_columns_wenti_daan(tmp_path):
    """中文 问题/答案 列名"""
    df = pd.DataFrame({"问题": ["Q1"], "答案": ["A1"]})
    p = _write_xlsx(tmp_path, df)
    out = _unwrap(read_qa_data(p))
    assert len(out) == 1
    assert out.iloc[0]["question"] == "Q1"


def test_case_insensitive(tmp_path):
    """大小写不敏感"""
    df = pd.DataFrame({"Question": ["Q1"], "ANSWER": ["A1"]})
    p = _write_xlsx(tmp_path, df)
    out = _unwrap(read_qa_data(p))
    assert len(out) == 1
    assert out.iloc[0]["answer"] == "A1"


def test_fallback_first_two_columns(tmp_path):
    """列名完全不匹配时取前两列"""
    df = pd.DataFrame({"foo": ["Q1"], "bar": ["A1"], "extra": ["x"]})
    p = _write_xlsx(tmp_path, df)
    out = _unwrap(read_qa_data(p))
    assert len(out) == 1
    assert out.iloc[0]["question"] == "Q1"
    assert out.iloc[0]["answer"] == "A1"


def test_dropna_removes_empty(tmp_path):
    """空值行应被移除"""
    df = pd.DataFrame({
        "question": ["Q1", None, "Q3"],
        "answer": ["A1", "A2", None],
    })
    p = _write_xlsx(tmp_path, df)
    out = _unwrap(read_qa_data(p))
    assert len(out) == 1
    assert out.iloc[0]["question"] == "Q1"


def test_strip_whitespace(tmp_path):
    """字符串应 strip 前后空白"""
    df = pd.DataFrame({"question": ["  Q1  "], "answer": ["  A1  "]})
    p = _write_xlsx(tmp_path, df)
    out = _unwrap(read_qa_data(p))
    assert out.iloc[0]["question"] == "Q1"
    assert out.iloc[0]["answer"] == "A1"


def test_filter_empty_strings(tmp_path):
    """纯空白字符串过滤后为空应被移除"""
    df = pd.DataFrame({"question": ["   ", "Q2"], "answer": ["A1", "A2"]})
    p = _write_xlsx(tmp_path, df)
    out = _unwrap(read_qa_data(p))
    assert len(out) == 1
    assert out.iloc[0]["question"] == "Q2"


def test_dedup_by_question(tmp_path):
    """相同 question 只保留一条"""
    df = pd.DataFrame({
        "question": ["Q1", "Q1", "Q2"],
        "answer": ["A1", "A1-dup", "A2"],
    })
    p = _write_xlsx(tmp_path, df)
    out = _unwrap(read_qa_data(p))
    assert len(out) == 2
    # 第一条 Q1 应保留 (drop_duplicates 默认保留首个)
    assert "Q1" in out["question"].values


def test_reset_index(tmp_path):
    """返回 DataFrame 索引应从 0 重新开始"""
    df = pd.DataFrame({
        "question": ["Q1", None, "Q3"],
        "answer": ["A1", "A2", "A3"],
    })
    p = _write_xlsx(tmp_path, df)
    out = _unwrap(read_qa_data(p))
    assert list(out.index) == [0, 1]
