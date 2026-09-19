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
        from src.tools.cert_ocr import get_cert_storage, LocalCertStorage
        assert isinstance(get_cert_storage(), LocalCertStorage)

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
            # 穿越校验
            import pytest
            with pytest.raises(FileNotFoundError):
                s.path(1, "../etc/passwd")
            # cleanup 孤儿
            assert s.cleanup(1, {token}) == 0
            assert s.cleanup(1, set()) == 1
        finally:
            co.CERT_UPLOAD_DIR = old
