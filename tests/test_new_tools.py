"""新工具单元测试: document_parser / bid_generator / compliance_checker / deadline_monitor / report_export.

策略: 全部 mock 外部依赖 (LLM/Qdrant), 只测纯逻辑.
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ========== document_parser ==========

class TestDocumentParser:
    def test_extract_text_txt(self, tmp_path: Path):
        from src.tools.document_parser import extract_text
        f = tmp_path / "公告.txt"
        f.write_text("项目名称: 测试项目\n预算: 500万元", encoding="utf-8")
        text = extract_text(f)
        assert "测试项目" in text
        assert "500万元" in text

    def test_extract_text_unsupported(self, tmp_path: Path):
        from src.tools.document_parser import extract_text
        f = tmp_path / "bad.xyz"
        f.write_text("x")
        with pytest.raises(ValueError, match="不支持的文件格式"):
            extract_text(f)

    def test_extract_structured_llm_mock(self):
        from src.tools.document_parser import extract_structured
        fake_llm = MagicMock()
        fake_llm.chat.return_value = '{"project_name": "测试项目", "budget": "500万元", "qualification_requirements": ["一级资质"]}'
        result = extract_structured("项目名称: 测试项目", llm_client=fake_llm)
        assert result["parse_status"] == "ok"
        assert result["project_name"] == "测试项目"
        assert result["budget"] == "500万元"

    def test_extract_structured_llm_fallback(self):
        """LLM 返回无效 JSON → fallback."""
        from src.tools.document_parser import extract_structured
        fake_llm = MagicMock()
        fake_llm.chat.return_value = "not json at all"
        text = "项目名称: 测试项目\n采购人: ABC公司\n投标截止时间: 2026-10-01"
        result = extract_structured(text, llm_client=fake_llm)
        assert result["parse_status"] == "partial"
        # 正则兜底应命中
        assert result.get("project_name") or result.get("deadline")

    def test_parse_file_combo(self, tmp_path: Path):
        from src.tools.document_parser import parse_file
        fake_llm = MagicMock()
        fake_llm.chat.return_value = '{"project_name": "X", "qualification_requirements": []}'
        f = tmp_path / "a.txt"
        f.write_text("项目名称: X", encoding="utf-8")
        result = parse_file(f, llm_client=fake_llm)
        assert result["source_file"] == "a.txt"
        assert result["text_length"] > 0


# ========== bid_generator ==========

class TestBidGenerator:
    def test_suggest_sections_basic(self):
        from src.tools.bid_generator import suggest_sections
        # 只有采购内容 → 资格 + 技术 + 商务
        tender = {"subject_matter": "服务器采购", "budget": "500万"}
        sections = suggest_sections(tender)
        assert "qualification" in sections
        assert any(k in sections for k in ("technical", "commercial"))

    def test_suggest_sections_empty(self):
        from src.tools.bid_generator import suggest_sections
        # 最小信息 → 至少资格声明
        tender = {"subject_matter": "", "budget": ""}
        sections = suggest_sections(tender)
        assert "qualification" in sections

    def test_generate_section_mock(self):
        from src.tools.bid_generator import generate_section
        fake_llm = MagicMock()
        fake_llm.chat.return_value = "# 技术方案内容..."
        result, fill_info = generate_section(
            {"project_name": "测试项目", "subject_matter": "服务器"},
            "technical",
            similar_cases=[],
            llm_client=fake_llm,
        )
        assert "## 技术方案" in result
        assert isinstance(fill_info, dict)

    def test_invalid_section_key(self):
        from src.tools.bid_generator import generate_section
        with pytest.raises(ValueError, match="未知章节"):
            generate_section({}, "not_a_real_section", llm_client=MagicMock())

    def test_full_bid(self):
        from src.tools.bid_generator import generate_full_bid, SECTIONS
        fake_llm = MagicMock()
        fake_llm.chat.return_value = "内容..."
        tender = {"project_name": "测试项目", "subject_matter": "服务器", "budget": "500万"}
        md, fill_info = generate_full_bid(tender, similar_cases=[], llm_client=fake_llm)
        assert "测试项目" in md
        assert "投 标 文 件" in md
        assert isinstance(fill_info, dict)
        # 所有指定章节标题都在
        for key in SECTIONS:
            assert SECTIONS[key]["title"] in md

    def test_profile_placeholder_fill(self):
        from src.tools.bid_generator import generate_section
        fake_llm = MagicMock()
        fake_llm.chat.return_value = "致 [公司全称]，法人[法定代表人]，参数[具体参数]"
        result, fill_info = generate_section(
            {"project_name": "P", "subject_matter": "软件"},
            "technical", similar_cases=[], llm_client=fake_llm,
            company_profile={"company_name": "华信公司", "legal_person": "张三"},
        )
        assert "华信公司" in result and "张三" in result
        assert "[公司全称]" not in result
        assert "公司全称" not in fill_info["missing_company"]
        assert "具体参数" in fill_info["pending_business"]


# ========== compliance_checker ==========

class TestComplianceChecker:
    def test_fallback_keyword_match(self):
        from src.tools.compliance_checker import _fallback_check
        text = "投标人必须在本地注册, 注册资本不低于1000万元"
        result = _fallback_check(text)
        assert result["summary"]["risks_found"] >= 2  # EXCL_001 + QUAL_001
        high_risks = [r for r in result["risks"] if r["risk_level"] == "高"]
        assert len(high_risks) >= 1

    def test_fallback_clean(self):
        from src.tools.compliance_checker import _fallback_check
        text = "本项目公开招标, 欢迎符合条件的投标人参与."
        result = _fallback_check(text)
        assert result["summary"]["risks_found"] == 0

    def test_llm_result_parsing(self):
        from src.tools.compliance_checker import check_compliance
        fake_llm = MagicMock()
        fake_llm.chat.return_value = (
            '{"results": ['
            '{"rule_id": "EXCL_001", "status": "match", '
            '"evidence": "必须在本地注册", "detail": "发现排他性条款"},'
            '{"rule_id": "QUAL_001", "status": "clean", "evidence": "", "detail": ""}'
            "]}"
        )
        result = check_compliance("招标文件片段...", llm_client=fake_llm)
        assert result["status"] == "warn"
        assert len(result["risks"]) >= 1
        assert result["clean_rules"]

    def test_llm_fail_fallback(self):
        from src.tools.compliance_checker import check_compliance
        fake_llm = MagicMock()
        fake_llm.chat.return_value = "not json"
        text = "必须本地注册"
        result = check_compliance(text, llm_client=fake_llm)
        assert result["summary"]["risks_found"] >= 1
        assert result.get("note")  # 降级提示


# ========== deadline_monitor ==========

class TestDeadlineMonitor:
    def test_parse_date_standard(self):
        from src.tools.deadline_monitor import parse_deadline
        dt = parse_deadline("2026-10-01 09:30")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 10
        assert dt.day == 1
        assert dt.hour == 9

    def test_parse_date_chinese(self):
        from src.tools.deadline_monitor import parse_deadline
        dt = parse_deadline("2026年10月1日 上午9:30")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 10

    def test_parse_date_no_year(self):
        from src.tools.deadline_monitor import parse_deadline
        now = datetime.now()
        dt = parse_deadline("10月1日")
        assert dt is not None
        assert dt.year == now.year

    def test_parse_date_none(self):
        from src.tools.deadline_monitor import parse_deadline
        assert parse_deadline("") is None
        assert parse_deadline(None) is None
        assert parse_deadline("不是日期") is None

    def test_classify_urgency(self):
        from src.tools.deadline_monitor import classify_urgency
        assert classify_urgency(0.5)["level"] == "critical"
        assert classify_urgency(2)["level"] == "warning"
        assert classify_urgency(5)["level"] == "notice"
        assert classify_urgency(10)["level"] == "normal"
        assert classify_urgency(-1)["level"] == "expired"


# ========== report_export ==========

class TestReportExport:
    def test_markdown_to_docx_smoke(self):
        from src.tools.report_export import markdown_to_docx
        md = """# 测试标题

这是普通段落, 包含 **粗体** 文字.

## 二级标题

- 列表项 1
- 列表项 2

1. 有序 1
2. 有序 2

| 列A | 列B |
|-----|-----|
| 1   | 2   |
| 3   | 4   |
"""
        data = markdown_to_docx(md, title="测试报告")
        assert len(data) > 1000  # docx 文件至少 1KB
        assert data[:4] == b"PK\x03\x04"  # ZIP magic (docx 本质是 ZIP)

    def test_export_bid(self):
        from src.tools.report_export import export_bid_to_docx
        md = "# 测试项目投标书\n\n## 技术方案\n\n内容..."
        data = export_bid_to_docx(md, project_name="测试项目")
        assert data[:4] == b"PK\x03\x04"


# ========== qualification_checker ==========

class TestQualificationChecker:
    def test_full_match_llm(self):
        from src.tools.qualification_checker import check_qualification
        fake_llm = MagicMock()
        fake_llm.chat.return_value = (
            '{"checks": ['
            '{"requirement": "建筑一级资质", "status": "FULL_MATCH", '
            '"matched_qualification": "建筑工程施工总承包一级", "detail": "等价匹配"},'
            '{"requirement": "ISO9001", "status": "FULL_MATCH", '
            '"matched_qualification": "ISO9001质量管理体系认证", "detail": "一致"}'
            "]}"
        )
        result = check_qualification(
            ["建筑一级资质", "ISO9001"],
            ["建筑工程施工总承包一级", "ISO9001质量管理体系认证"],
            llm_client=fake_llm,
        )
        assert result["summary"]["full"] == 2
        assert result["summary"]["missing"] == 0
        assert result["verdict"] == "pass"

    def test_partial_and_missing_llm(self):
        from src.tools.qualification_checker import check_qualification
        fake_llm = MagicMock()
        fake_llm.chat.return_value = (
            '{"checks": ['
            '{"requirement": "建筑一级", "status": "FULL_MATCH", "matched_qualification": "建筑一级", "detail": ""},'
            '{"requirement": "电子与智能化", "status": "NO_MATCH", "matched_qualification": "", "detail": "未持有"},'
            '{"requirement": "CSDN认证", "status": "PARTIAL_MATCH", "matched_qualification": "软考中级", "detail": "相关但不等价"}'
            "]}"
        )
        result = check_qualification(
            ["建筑一级", "电子与智能化", "CSDN认证"],
            ["建筑一级", "软考中级"],
            llm_client=fake_llm,
        )
        assert result["summary"]["full"] == 1
        assert result["summary"]["missing"] >= 1  # NO_MATCH 或 INFO_MISSING
        assert len(result["checks"]) == 3
        assert result["gap_report"]

    def test_empty_tender_reqs(self):
        from src.tools.qualification_checker import check_qualification
        result = check_qualification([], ["建筑一级"], llm_client=MagicMock())
        assert result["verdict"] == "unknown"
        assert "未检测到" in result["gap_report"]

    def test_empty_company_quals(self):
        from src.tools.qualification_checker import check_qualification
        result = check_qualification(["建筑一级", "ISO9001"], [], llm_client=MagicMock())
        assert result["summary"]["missing"] == 2
        assert result["verdict"] == "fail"

    def test_llm_fail_fallback(self):
        from src.tools.qualification_checker import check_qualification
        fake_llm = MagicMock()
        fake_llm.chat.return_value = "not json at all"
        result = check_qualification(
            ["建筑一级资质", "ISO9001"],
            ["建筑一级资质", "ISO9001质量管理体系"],
            llm_client=fake_llm,
        )
        # fallback 关键词匹配: "建筑一级资质" in "建筑一级资质" → FULL_MATCH
        assert result["summary"]["full"] >= 1  # ISO9001 双向包含也应命中
        assert "coverage" in result["summary"]

    def test_whitespace_cleaned(self):
        from src.tools.qualification_checker import check_qualification
        fake_llm = MagicMock()
        fake_llm.chat.return_value = '{"checks": []}'
        result = check_qualification(
            ["  建筑一级  ", "", None],
            ["建筑一级"],
            llm_client=fake_llm,
        )
        # 空字符串和 None 应被过滤, 只剩 1 条有效
        assert result["summary"]["total_req"] == 1


# ========== price_analyzer ==========

class TestPriceAnalyzer:
    def test_format_amount(self):
        from src.tools.price_analyzer import _format_amount
        assert "万元" in _format_amount(5000000)
        assert "-" == _format_amount(None)

    def test_pg_down_grade(self):
        """PG 未连接时返回降级提示, 不崩."""
        from src.tools.price_analyzer import analyze_price
        fake_pg = MagicMock()
        fake_pg.ready = False
        with patch("src.tools.price_analyzer.postgresql_client", fake_pg):
            result = analyze_price("空调", llm_client=MagicMock())
        assert result["data_source"] == "none"
        assert "PG" in result["llm_comment"] or "PostgreSQL" in result["llm_comment"]

    def test_pg_empty_result(self):
        """PG 连上但无匹配数据时, 返回空分析 + 提示."""
        from src.tools.price_analyzer import analyze_price
        fake_pg = MagicMock()
        fake_pg.ready = True
        fake_pg.query.return_value = []
        with patch("src.tools.price_analyzer.postgresql_client", fake_pg):
            result = analyze_price("不存在的标的", llm_client=MagicMock())
        assert result["distribution"] == {}
        assert "未找到" in result["llm_comment"] or "无法" in result["llm_comment"]


# ========== competitor_analyzer ==========

class TestCompetitorAnalyzer:
    def test_both_down_grade(self):
        """PG 和 Neo4j 都未连接 → 降级提示."""
        from src.tools.competitor_analyzer import analyze_competitors
        fake_pg = MagicMock()
        fake_pg.ready = False
        fake_neo = MagicMock()
        fake_neo.ready = False
        with patch("src.tools.competitor_analyzer.postgresql_client", fake_pg), \
             patch("src.tools.competitor_analyzer.neo4j_client", fake_neo):
            result = analyze_competitors("空调", llm_client=MagicMock())
        assert "降级" in result["llm_comment"] or "无法" in result["llm_comment"]
        assert result["top_suppliers"] == []

    def test_pg_only(self):
        """只有 PG 连上 → 只用 PG 数据, 不崩."""
        from src.tools.competitor_analyzer import analyze_competitors
        fake_pg = MagicMock()
        fake_pg.ready = True
        fake_pg.query.return_value = [
            {"supplier": "A公司", "win_count": 5, "avg_amount": 1000000,
             "total_amount": 5000000, "min_amount": 800000, "max_amount": 1200000}
        ]
        fake_neo = MagicMock()
        fake_neo.ready = False
        fake_llm = MagicMock()
        fake_llm.chat.return_value = "# 竞品分析\n\n主要竞争者..."

        with patch("src.tools.competitor_analyzer.postgresql_client", fake_pg), \
             patch("src.tools.competitor_analyzer.neo4j_client", fake_neo):
            result = analyze_competitors("空调", top_n=3, llm_client=fake_llm)

        assert "postgresql" in result["data_sources"]
        assert "neo4j" not in result["data_sources"]
        assert len(result["top_suppliers"]) == 1
        assert result["top_suppliers"][0]["supplier"] == "A公司"
        assert result["llm_comment"]

    def test_data_conversion(self):
        """Neo4j 返回 list/dict 混合时, _convert_row 正确处理."""
        from src.tools.competitor_analyzer import _convert_row
        row = {
            "supplier": "X",
            "subjects": ["subjectA", "subjectB"],
            "subject_count": 2,
            "competitors": [None, "C1"],
        }
        out = _convert_row(row)
        assert isinstance(out["subjects"], list)
        assert "subjectA" in out["subjects"]
