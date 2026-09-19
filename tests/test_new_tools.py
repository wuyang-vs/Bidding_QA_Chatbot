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


# ========== cert_ocr: 证书 OCR 结构化 (V1.5) ==========

class TestCertOcr:
    def test_fallback_qualification_cert(self):
        from src.tools.cert_ocr import fallback_cert_fields
        r = fallback_cert_fields(
            "建筑业企业资质证书\n等级：一级\n证书编号：BZ-2025-888666\n"
            "有效期至：2028年06月30日")
        assert r["name"] == "建筑业企业资质证书"
        assert r["level"] == "一级"
        assert r["cert_no"] == "BZ-2025-888666"
        assert r["valid_until"] == "2028-06-30"

    def test_fallback_business_license(self):
        from src.tools.cert_ocr import fallback_cert_fields
        r = fallback_cert_fields(
            "营业执照\n统一社会信用代码：91310000MA1FL88X2Q\n营业期限至 长期")
        assert r["name"] == "营业执照"
        assert r["cert_no"] == "91310000MA1FL88X2Q"
        assert r["valid_until"] == "长期"

    def test_fallback_level_stripped_from_name(self):
        from src.tools.cert_ocr import fallback_cert_fields
        r = fallback_cert_fields("建筑工程施工总承包一级资质证书 编号:A123456789")
        assert "一级" not in r["name"]
        assert r["level"] == "一级"
        assert r["cert_no"] == "A123456789"

    def test_fallback_empty(self):
        from src.tools.cert_ocr import fallback_cert_fields
        assert fallback_cert_fields("") == {
            "name": "", "level": "", "cert_no": "", "valid_until": ""}

    def test_extract_llm_success(self):
        from src.tools.cert_ocr import extract_cert_fields
        fake_llm = MagicMock()
        fake_llm.chat.return_value = (
            '```json\n{"name": "CMMI3级证书", "level": "三级", '
            '"cert_no": "CMMI-001", "valid_until": "2027-01-02"}\n```')
        r = extract_cert_fields("某证书 OCR 文本", llm_client=fake_llm)
        assert r["source"] == "llm"
        assert r["cert_no"] == "CMMI-001"
        assert r["valid_until"] == "2027-01-02"

    def test_extract_llm_failure_fallback(self):
        from src.tools.cert_ocr import extract_cert_fields
        fake_llm = MagicMock()
        fake_llm.chat.side_effect = RuntimeError("llm down")
        r = extract_cert_fields("资质证书 编号：Z-9988 有效期至2026-12-01",
                                llm_client=fake_llm)
        assert r["source"] == "fallback"
        assert r["cert_no"] == "Z-9988"
        assert r["valid_until"] == "2026-12-01"
        assert r["warnings"]

    def test_extract_empty_text(self):
        from src.tools.cert_ocr import extract_cert_fields
        r = extract_cert_fields("", llm_client=MagicMock())
        assert r["source"] == "none"
        assert not r["cert_no"]
        assert r["warnings"]

    def test_cert_storage_lifecycle_and_isolation(self, tmp_path, monkeypatch):
        from src.tools import cert_ocr
        monkeypatch.setattr(cert_ocr, "CERT_UPLOAD_DIR", tmp_path / "certs")

        saved = cert_ocr.save_cert_file(7, "我的证书.png", b"\x89PNGfake")
        token = saved["file_token"]
        assert token.endswith(".png")

        # 本人可解析且读回内容一致
        p = cert_ocr.cert_file_path(7, token)
        assert p.read_bytes() == b"\x89PNGfake"

        # 跨用户目录访问 → 404
        with pytest.raises(FileNotFoundError):
            cert_ocr.cert_file_path(8, token)
        # 路径穿越 / 非法 token → 404
        with pytest.raises(FileNotFoundError):
            cert_ocr.cert_file_path(7, "../../etc/passwd")
        with pytest.raises(FileNotFoundError):
            cert_ocr.cert_file_path(7, "x" * 32 + ".exe")

        # 非法扩展名上传被拒
        with pytest.raises(ValueError):
            cert_ocr.save_cert_file(7, "evil.exe", b"xx")

        # 孤儿清理: 保存第二个文件后, 只保留第二个
        saved2 = cert_ocr.save_cert_file(7, "b.jpg", b"jpg")
        removed = cert_ocr.cleanup_orphan_certs(7, {saved2["file_token"]})
        assert removed == 1
        with pytest.raises(FileNotFoundError):
            cert_ocr.cert_file_path(7, token)
        assert cert_ocr.cert_file_path(7, saved2["file_token"]).is_file()

    def test_ocr_image_uses_rapidocr(self, monkeypatch):
        """图片字节 → 预处理 → cv2 解码 → RapidOCR 结果按行拼接 (引擎 mock, 不拉模型)。"""
        from src.tools import cert_ocr

        fake_engine = MagicMock()
        fake_engine.return_value = (
            [[None, "证书编号：X-1"], [None, "有效期至 2029-09-09"]], None)
        monkeypatch.setattr(
            "src.tools.document_parser._get_ocr_engine", lambda: fake_engine)
        fake_cv2 = MagicMock()
        fake_cv2.imdecode.return_value = "IMG"
        monkeypatch.setattr("cv2.imdecode", fake_cv2.imdecode)
        # 预处理涉及真实 cv2, 这里 mock 掉只验证引擎调用链
        monkeypatch.setattr(cert_ocr, "_preprocess_image", lambda x: x)

        text = cert_ocr._ocr_image_bytes(b"fake-bytes")
        assert "X-1" in text and "2029-09-09" in text
        fake_engine.assert_called_once_with("IMG")


# ==================== R9: 对照表结构校验 + 缓存 ====================

class TestMatrixValidation:
    def test_validate_row_drops_empty_requirement(self):
        from src.tools.requirement_matrix import _validate_row
        assert _validate_row({"requirement": "  "}, 1) is None

    def test_validate_row_fixes_invalid_status_and_category(self):
        from src.tools.requirement_matrix import _validate_row
        r = _validate_row({"requirement": "具备资质", "status": "FOO",
                           "category": "未知类别"}, 1)
        assert r["status"] == "NO_RESPONSE"
        assert r["category"] == "其他"

    def test_validate_row_material_heuristic(self):
        from src.tools.requirement_matrix import _validate_row
        # 无实质性关键词 → material 强制 false
        r = _validate_row({"requirement": "提供售后服务", "material": True}, 1)
        assert r["material"] is False
        # 含"必须" → material 保留 true
        r2 = _validate_row({"requirement": "必须具有独立法人资格", "material": True}, 1)
        assert r2["material"] is True


class TestMatrixCache:
    def test_cache_hit_same_input(self, monkeypatch):
        from src.tools import requirement_matrix as rm
        rm.clear_matrix_cache()
        calls = {"n": 0}

        class FakeLLM:
            def chat(self, msgs, temperature=0.1):
                calls["n"] += 1
                return '{"rows":[{"no":"1","requirement":"必须满足资质","category":"资格","material":true,"response":"已具备","status":"SATISFIED","evidence":"c1","note":""}]}'

        tender = {"db_id": 99, "qualification_requirements": []}
        m1 = rm.build_requirement_matrix(tender, "招标原文", "投标稿", llm_client=FakeLLM())
        m2 = rm.build_requirement_matrix(tender, "招标原文", "投标稿", llm_client=FakeLLM())
        assert m1["cached"] is False
        assert m2["cached"] is True
        assert calls["n"] == 1  # 第二次命中缓存, 不调 LLM

    def test_cache_miss_different_bid(self, monkeypatch):
        from src.tools import requirement_matrix as rm
        rm.clear_matrix_cache()
        calls = {"n": 0}

        class FakeLLM:
            def chat(self, msgs, temperature=0.1):
                calls["n"] += 1
                return '{"rows":[{"no":"1","requirement":"必须满足资质","category":"资格","material":true,"response":"x","status":"SATISFIED","evidence":"","note":""}]}'

        tender = {"db_id": 99, "qualification_requirements": []}
        rm.build_requirement_matrix(tender, "招标原文", "投标稿A", llm_client=FakeLLM())
        m = rm.build_requirement_matrix(tender, "招标原文", "投标稿B", llm_client=FakeLLM())
        assert m["cached"] is False
        assert calls["n"] == 2


# ==================== R10: 敏感字段加密 + 掩码 ====================

class TestFieldCrypto:
    def test_encrypt_decrypt_roundtrip(self):
        from src.tools.field_crypto import encrypt_field, decrypt_field, is_encrypted
        ct = encrypt_field("6222021234567890123")
        assert ct != "6222021234567890123"
        assert ct.startswith("gAAAAA")
        assert is_encrypted(ct)
        assert decrypt_field(ct) == "6222021234567890123"

    def test_no_double_encrypt(self):
        from src.tools.field_crypto import encrypt_field
        ct1 = encrypt_field("123456")
        ct2 = encrypt_field(ct1)
        assert ct1 == ct2  # 已加密的不再二次加密

    def test_decrypt_plaintext_passthrough(self):
        from src.tools.field_crypto import decrypt_field
        # 历史明文数据原样返回 (向后兼容)
        assert decrypt_field("明文银行账号") == "明文银行账号"

    def test_mask_value(self):
        from src.tools.field_crypto import mask_value
        assert mask_value("bank_account", "6222021234567890") == "************7890"
        assert mask_value("contact_phone", "13812345678") == "138****5678"
        assert mask_value("contact_email", "zhangsan@example.com") == "z***@example.com"
        assert mask_value("legal_person", "张三丰") == "张**"

    def test_encrypt_decrypt_sensitive(self):
        from src.tools.field_crypto import encrypt_sensitive, decrypt_sensitive
        p = {"company_name": "华信", "bank_account": "6222", "contact_phone": "13800000000"}
        enc = encrypt_sensitive(p)
        assert enc["company_name"] == "华信"  # 非敏感字段不变
        assert enc["bank_account"].startswith("gAAAAA")
        dec = decrypt_sensitive(enc)
        assert dec["bank_account"] == "6222"
        assert dec["contact_phone"] == "13800000000"


# ==================== R11: 证书存储抽象 ====================

class TestCertStorage:
    def test_default_storage_is_local(self):
        from src.tools.cert_ocr import (
            get_cert_storage, LocalCertStorage, reset_cert_storage)
        reset_cert_storage()
        try:
            assert isinstance(get_cert_storage(), LocalCertStorage)
        finally:
            reset_cert_storage()

    def test_local_storage_save_path_cleanup(self, tmp_path):
        from src.tools.cert_ocr import LocalCertStorage
        s = LocalCertStorage()
        # 临时改存储根目录
        import src.tools.cert_ocr as co
        old = co.CERT_UPLOAD_DIR
        co.CERT_UPLOAD_DIR = tmp_path / "certs"
        try:
            saved = s.save(1, "a.png", b"hello")
            token = saved["file_token"]
            assert token.endswith(".png")
            assert s.path(1, token).read_bytes() == b"hello"
            assert s.read(1, token) == b"hello"  # 统一 read() 接口
            # 穿越校验
            import pytest
            with pytest.raises(FileNotFoundError):
                s.path(1, "../etc/passwd")
            with pytest.raises(FileNotFoundError):
                s.read(1, "../etc/passwd")
            # cleanup 孤儿
            assert s.cleanup(1, {token}) == 0
            assert s.cleanup(1, set()) == 1
        finally:
            co.CERT_UPLOAD_DIR = old


# ==================== R10: 多版本密钥轮换 ====================

class TestFieldCryptoRotation:
    """PROFILE_ENC_KEYS=新key,旧key 时: 旧密文可解/可识别/可重加密到新 key。"""

    @pytest.fixture
    def two_keys(self, monkeypatch):
        from cryptography.fernet import Fernet
        from src.config import settings
        from src.tools import field_crypto
        new_key = Fernet.generate_key().decode("utf-8")
        old_key = Fernet.generate_key().decode("utf-8")
        monkeypatch.setattr(settings, "profile_enc_keys", f"{new_key},{old_key}")
        field_crypto.reload_keys()
        try:
            yield Fernet(new_key.encode("utf-8")), Fernet(old_key.encode("utf-8"))
        finally:
            # 恢复默认 (无 PROFILE_ENC_KEYS → auth_secret 派生密钥), 避免污染其他用例
            monkeypatch.setattr(settings, "profile_enc_keys", "")
            field_crypto.reload_keys()

    def test_historical_ciphertext_still_decryptable(self, two_keys):
        _new_f, old_f = two_keys
        from src.tools.field_crypto import decrypt_field, is_encrypted
        ct = old_f.encrypt(b"6222021234567890").decode("utf-8")
        assert is_encrypted(ct)
        assert decrypt_field(ct) == "6222021234567890"

    def test_needs_rotation_and_rotate_value(self, two_keys):
        new_f, old_f = two_keys
        from src.tools import field_crypto
        ct_old = old_f.encrypt(b"13800138000").decode("utf-8")
        assert field_crypto.key_index(ct_old) == 1
        assert field_crypto.needs_rotation(ct_old)
        new_ct, changed = field_crypto.rotate_value(ct_old)
        assert changed is True
        assert field_crypto.key_index(new_ct) == 0
        assert new_f.decrypt(new_ct.encode("utf-8")).decode("utf-8") == "13800138000"
        # 已是当前密钥的密文不再重加密
        again, changed2 = field_crypto.rotate_value(new_ct)
        assert changed2 is False
        assert again == new_ct

    def test_encrypt_uses_current_key(self, two_keys):
        from src.tools.field_crypto import encrypt_field, decrypt_field, key_index
        ct = encrypt_field("secret@example.com")
        assert key_index(ct) == 0
        assert decrypt_field(ct) == "secret@example.com"

    def test_plaintext_passthrough_under_keychain(self, two_keys):
        from src.tools.field_crypto import needs_rotation, rotate_value
        # 明文/空串不参与轮换判定
        assert needs_rotation("普通明文") is False
        val, changed = rotate_value("普通明文")
        assert (val, changed) == ("普通明文", False)

    def test_invalid_key_falls_back_to_derived(self, monkeypatch):
        from src.config import settings
        from src.tools import field_crypto
        monkeypatch.setattr(settings, "profile_enc_keys", "not-a-valid-fernet-key")
        try:
            assert field_crypto.reload_keys() == 1  # 非法 key 被跳过, 回退派生密钥
            ct = field_crypto.encrypt_field("6222")
            assert field_crypto.decrypt_field(ct) == "6222"
        finally:
            monkeypatch.setattr(settings, "profile_enc_keys", "")
            field_crypto.reload_keys()


# ==================== R11: S3 兼容对象存储 (botocore Stubber) ====================

class TestS3CertStorage:
    BUCKET = "bid-certs-test"

    def _make(self):
        import boto3
        from botocore.config import Config
        from botocore.stub import Stubber
        from src.tools.cert_ocr import S3CertStorage
        # 与生产 _s3() 一致: path-style + s3v4 签名 (预签名 URL 才带 X-Amz-Signature)
        client = boto3.client(
            "s3", region_name="us-east-1",
            aws_access_key_id="test-key", aws_secret_access_key="test-secret",
            config=Config(s3={"addressing_style": "path"},
                          signature_version="s3v4"))
        stubber = Stubber(client)
        storage = S3CertStorage(bucket=self.BUCKET, prefix="certs/",
                                client=client, auto_bucket=False)
        return storage, stubber

    def test_save_key_format_and_put_object(self):
        from urllib.parse import quote
        from botocore.stub import ANY
        storage, stubber = self._make()
        payload = b"\x89PNG fake cert bytes"
        stubber.add_response(
            "put_object", {},
            expected_params={"Bucket": self.BUCKET, "Key": ANY,
                             "Body": payload, "ContentType": "image/png",
                             "Metadata": {"original_name":
                                          quote("营业执照.png", safe="")}})
        stubber.activate()
        saved = storage.save(7, "营业执照.png", payload)
        token = saved["file_token"]
        import re
        assert re.fullmatch(r"[0-9a-f]{32}\.png", token)
        assert saved["size"] == len(payload)
        # key 含用户目录隔离前缀
        assert storage._key(7, token) == f"certs/7/{token}"
        stubber.assert_no_pending_responses()

    def test_read_roundtrip_and_404(self):
        import io
        storage, stubber = self._make()
        token = "a" * 32 + ".pdf"
        key = f"certs/9/{token}"
        payload = b"%PDF-1.4 fake"
        stubber.add_response(
            "get_object",
            {"Body": io.BytesIO(payload), "ContentType": "application/pdf"},
            expected_params={"Bucket": self.BUCKET, "Key": key})
        stubber.add_client_error("get_object", service_error_code="NoSuchKey",
                                 expected_params={"Bucket": self.BUCKET, "Key": key})
        stubber.activate()
        assert storage.read(9, token) == payload
        with pytest.raises(FileNotFoundError):
            storage.read(9, token)
        stubber.assert_no_pending_responses()

    def test_delete_object(self):
        storage, stubber = self._make()
        token = "b" * 32 + ".jpg"
        stubber.add_response(
            "delete_object", {},
            expected_params={"Bucket": self.BUCKET, "Key": f"certs/3/{token}"})
        stubber.activate()
        storage.delete(3, token)  # 不抛异常即可
        stubber.assert_no_pending_responses()

    def test_cleanup_lists_and_batch_deletes(self):
        storage, stubber = self._make()
        keep = "c" * 32 + ".png"
        orphan = "d" * 32 + ".jpg"
        stubber.add_response(
            "list_objects_v2",
            {"Contents": [
                {"Key": f"certs/5/{keep}"},
                {"Key": f"certs/5/{orphan}"},
            ]},
            expected_params={"Bucket": self.BUCKET, "Prefix": "certs/5/"})
        stubber.add_response(
            "delete_objects",
            {"Deleted": [{"Key": f"certs/5/{orphan}"}]},
            expected_params={
                "Bucket": self.BUCKET,
                "Delete": {"Objects": [{"Key": f"certs/5/{orphan}"}],
                           "Quiet": True}})
        stubber.activate()
        assert storage.cleanup(5, {keep}) == 1
        stubber.assert_no_pending_responses()

    def test_invalid_token_rejected_without_api_call(self):
        # 不注册任何桩响应: 一旦真的发起 API 调用 Stubber 会抛错
        storage, _stubber = self._make()
        with pytest.raises(FileNotFoundError):
            storage.read(7, "../../etc/passwd")
        with pytest.raises(FileNotFoundError):
            storage.read(7, "x" * 32 + ".exe")  # 扩展名白名单
        with pytest.raises(FileNotFoundError):
            storage.presigned_url(7, "../evil.png")
        with pytest.raises(ValueError):
            storage.save(7, "evil.exe", b"xx")

    def test_presigned_url_contains_bucket_and_key(self):
        storage, _stubber = self._make()
        token = "e" * 32 + ".png"
        url = storage.presigned_url(9, token, expires_min=5)
        assert isinstance(url, str) and url.startswith("http")
        assert self.BUCKET in url
        assert token in url
        assert "X-Amz-Signature=" in url  # s3v4 预签名

    def test_build_s3_storage_from_settings(self, monkeypatch):
        from src.config import settings
        from src.tools import cert_ocr
        monkeypatch.setattr(settings, "cert_storage_type", "s3")
        monkeypatch.setattr(settings, "cert_s3_bucket", "from-settings-bucket")
        cert_ocr.reset_cert_storage()
        try:
            s = cert_ocr.get_cert_storage()
            assert isinstance(s, cert_ocr.S3CertStorage)
            assert s.bucket == "from-settings-bucket"
        finally:
            cert_ocr.reset_cert_storage()


# ==================== R12: 审计日志落库 ====================

class _FakePg:
    """记录 _run 调用的假 PG; 行为由属性/钩子配置。"""
    def __init__(self, ready=True, rows=None, raise_on=None):
        self.ready = ready
        self._rows = rows or []
        self.raise_on = raise_on
        self.calls: list[tuple[str, dict]] = []

    def _run(self, sql, params=None):
        self.calls.append((sql, params or {}))
        if self.raise_on and self.raise_on in sql:
            raise RuntimeError("pg boom")
        if "COUNT(*)" in sql:
            return [{"cnt": len(self._rows)}]
        if sql.lstrip().upper().startswith("SELECT"):
            return list(self._rows)
        return []


class TestAuditLog:
    def test_record_insert_params_and_never_values(self, monkeypatch):
        import json
        from src.tools import audit_log
        fake = _FakePg()
        monkeypatch.setattr("src.database.postgresql_client.postgresql_client", fake)
        ok = audit_log.record_audit(
            user_id=7, username="acpt_u_1", action=audit_log.ACTION_PROFILE_UPDATE,
            target_type="company_profile", target_id="7",
            changed_fields=["contact_phone", "bank_account"],
            ip="127.0.0.1", user_agent="pytest-agent", detail="profile saved")
        assert ok is True
        sql, params = fake.calls[0]
        assert "INSERT INTO audit_logs" in sql
        assert params["action"] == "profile.update"
        assert params["uid"] == 7 and params["uname"] == "acpt_u_1"
        fields = json.loads(params["fields"])
        assert fields == ["contact_phone", "bank_account"]
        # 审计只存字段名: 绑定参数里不得出现任何"值"
        blob = json.dumps(params, ensure_ascii=False)
        assert "13812345678" not in blob and "6222" not in blob

    def test_record_pg_not_ready_degrades(self, monkeypatch):
        from src.tools import audit_log
        fake = _FakePg(ready=False)
        monkeypatch.setattr("src.database.postgresql_client.postgresql_client", fake)
        assert audit_log.record_audit(
            user_id=1, username="u", action="profile.update",
            changed_fields=["x"]) is False
        assert fake.calls == []  # 未就绪不触达 DB

    def test_record_db_error_degrades(self, monkeypatch):
        from src.tools import audit_log
        fake = _FakePg(raise_on="INSERT INTO audit_logs")
        monkeypatch.setattr("src.database.postgresql_client.postgresql_client", fake)
        # 写库异常不得抛出 (审计不能阻断主业务)
        assert audit_log.record_audit(
            user_id=1, username="u", action="profile.update") is False

    def test_clean_fields_and_clipping(self, monkeypatch):
        import json
        from src.tools import audit_log
        fake = _FakePg()
        monkeypatch.setattr("src.database.postgresql_client.postgresql_client", fake)
        dirty = ["a", "a", "", " b ", 123, None, "x" * 100] + [f"f{i}" for i in range(99)]
        assert audit_log.record_audit(
            user_id=None, username="u" * 999, action="  ",
            changed_fields=dirty, detail="d" * 5000, user_agent="ua" * 999) is False
        assert fake.calls == []  # 空白 action 直接拒绝
        ok = audit_log.record_audit(
            user_id=None, username="u" * 999, action="cert.ocr",
            changed_fields=dirty, detail="d" * 5000, user_agent="ua" * 999)
        assert ok is True
        _, p = fake.calls[0]
        fields = json.loads(p["fields"])
        assert fields[0] == "a" and fields[1] == "b"   # 去重/去空/非字符串剔除
        assert all(len(f) <= audit_log._MAX_FIELD_LEN for f in fields)
        assert len(fields) == audit_log._MAX_FIELDS    # 限量
        assert len(p["detail"]) == audit_log._MAX_DETAIL_LEN
        assert len(p["ua"]) == audit_log._MAX_TEXT_LEN
        assert len(p["uname"]) == audit_log._MAX_TEXT_LEN

    def test_list_filters_pagination_and_serialize(self, monkeypatch):
        from datetime import datetime
        from src.tools import audit_log
        fake = _FakePg(rows=[{
            "id": 3, "user_id": 7, "username": "acpt_u_1", "action": "profile.update",
            "target_type": "company_profile", "target_id": "7",
            "changed_fields": '["contact_phone"]', "ip": "127.0.0.1",
            "user_agent": "pytest", "detail": "",
            "created_at": datetime(2026, 9, 19, 10, 11, 12)}])
        monkeypatch.setattr("src.database.postgresql_client.postgresql_client", fake)
        out = audit_log.list_audit_logs(
            user_id=7, action="profile.update", limit=99999, offset=5, order="desc")
        sql_items, p_items = fake.calls[0]
        assert "WHERE user_id = :uid AND action = :action" in sql_items
        assert "ORDER BY id DESC LIMIT :limit OFFSET :offset" in sql_items
        assert p_items["limit"] == audit_log._MAX_LIMIT  # 上限钳制
        assert p_items["offset"] == 5
        assert out["total"] == 1 and out["limit"] == audit_log._MAX_LIMIT
        item = out["items"][0]
        assert item["changed_fields"] == ["contact_phone"]   # JSONB 字符串已解析
        assert item["created_at"] == "2026-09-19 10:11:12"   # datetime 已序列化
        # 非法排序方向回落 DESC; 非法 limit/offset 回落默认
        fake.calls.clear()
        out2 = audit_log.list_audit_logs(order="; DROP TABLE", limit="x", offset="y")
        assert "ORDER BY id DESC" in fake.calls[0][0]
        assert out2["limit"] == audit_log._DEFAULT_LIMIT and out2["offset"] == 0

    def test_list_pg_not_ready_empty(self, monkeypatch):
        from src.tools import audit_log
        fake = _FakePg(ready=False)
        monkeypatch.setattr("src.database.postgresql_client.postgresql_client", fake)
        out = audit_log.list_audit_logs(action="profile.update")
        assert out == {"items": [], "total": 0, "limit": 50, "offset": 0}

    def test_upsert_profile_emits_audit(self, monkeypatch):
        import json
        from src.tools import company_profile
        fake = _FakePg()  # SELECT 均返回空行 → 空档案, INSERT 返回 []
        monkeypatch.setattr("src.database.postgresql_client.postgresql_client", fake)
        company_profile.upsert_profile(
            99, {"company_name": "审计接入有限公司", "contact_phone": "13812345678"},
            audit_meta={"username": "acpt_audit_1", "ip": "10.0.0.9",
                        "user_agent": "pytest-ua"})
        audit_calls = [(s, p) for s, p in fake.calls if "INSERT INTO audit_logs" in s]
        assert len(audit_calls) == 1, "资料变更应落一条审计"
        sql, p = audit_calls[0]
        assert p["action"] == "profile.update" and p["uname"] == "acpt_audit_1"
        assert p["ip"] == "10.0.0.9" and p["ua"] == "pytest-ua"
        fields = json.loads(p["fields"])
        assert "company_name" in fields and "contact_phone" in fields

    def test_upsert_profile_skips_audit_when_no_change(self, monkeypatch):
        """旧档与新档完全一致 → 不写审计。"""
        from src.tools import company_profile
        from src.tools.field_crypto import encrypt_sensitive

        existing = encrypt_sensitive(company_profile._norm(
            {"company_name": "不变有限公司", "contact_phone": "13812345678"}))

        class _PgSame(_FakePg):
            def _run(self, sql, params=None):
                self.calls.append((sql, params or {}))
                if sql.lstrip().upper().startswith("SELECT * FROM COMPANY_PROFILES"):
                    return [dict(existing)]
                return []

        fake = _PgSame()
        monkeypatch.setattr("src.database.postgresql_client.postgresql_client", fake)
        company_profile.upsert_profile(
            100, {"company_name": "不变有限公司", "contact_phone": "13812345678"},
            audit_meta={"username": "u"})
        assert not any("INSERT INTO audit_logs" in s for s, _ in fake.calls), \
            "无字段变化不应写审计"
