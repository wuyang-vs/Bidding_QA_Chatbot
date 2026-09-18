"""投标文件智能解析: PDF/Word → 结构化 JSON.

流程:
  1. extract_text(path)  — 根据扩展名路由 PyMuPDF / python-docx
  2. extract_structured(text) — LLM 按固定 schema 抽取
  3. parse_file(path)    — 组合以上两步

设计:
  - 大文件: 截断前 8000 字符 (含表头), 再补后 2000 字符 (截止时间/附件常在末尾)
  - 容错: LLM JSON 解析失败 → 返回纯 text + 原始片段, 不崩
  - 依赖: pymupdf (PDF), python-docx (Word)

Agent 调用:
  from src.tools.document_parser import parse_file
  result = parse_file("招标公告.pdf")
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# LLM 抽取字段 schema — 必须输出这些 key, 缺失填 null
EXTRACT_SCHEMA = """{
  "project_name": "string|null      // 项目名称",
  "project_code": "string|null      // 项目编号/招标编号",
  "purchaser": "string|null         // 采购人/招标单位",
  "agency": "string|null            // 招标代理机构",
  "subject_matter": "string|null    // 采购内容/标的物 (简要描述)",
  "budget": "string|null            // 预算金额/最高限价 (含币种/单位)",
  "qualification_requirements": [   // 资质要求列表 (每条一条)
    "string"
  ],
  "scoring_criteria": "string|null  // 评分方法/标准 (简要描述)",
  "deadline": "string|null          // 投标截止时间 (原文保留)",
  "opening_time": "string|null      // 开标时间",
  "location": "string|null          // 投标/开标地点"
}"""


# ---------- 文本提取 ----------

# OCR 单例 (懒加载, 避免启动时拉起 onnxruntime)
_ocr_engine = None
# 页面文本少于该字符数视为扫描页 (无文本层)
_OCR_MIN_CHARS = 15
_OCR_DPI = 180
# OCR 页数安全上限 (超出后保留空页并在结果中标记 ocr_truncated, 防止超长扫描件卡死)
_OCR_MAX_PAGES = 100


def _get_ocr_engine():
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR
        logger.info("🖼  首次扫描件, 加载 RapidOCR 模型 ...")
        _ocr_engine = RapidOCR()
    return _ocr_engine


def _ocr_page(page) -> str:
    """对单个 PyMuPDF 页渲染后 OCR, 返回拼接文本."""
    import numpy as np
    import cv2
    png = page.get_pixmap(dpi=_OCR_DPI).tobytes("png")
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    result, _ = _get_ocr_engine()(img)
    if not result:
        return ""
    # result: [[box, text, score], ...] 按行上到下已大致有序
    return "\n".join(item[1] for item in result if item and len(item) > 1 and item[1])


def extract_pages_pdf(path: str | Path) -> tuple[list[dict[str, Any]], list[int], dict[str, Any]]:
    """PDF 按页提取, 返回 (pages, ocr_pages).

    pages: [{"page_no": 1 起, "text": str}]
    文本层为空的扫描页自动走 OCR; ocr_pages 记录实际 OCR 的页号.
    """
    import pymupdf
    doc = pymupdf.open(path)
    pages: list[dict[str, Any]] = []
    ocr_pages: list[int] = []
    truncated = False
    try:
        for idx, page in enumerate(doc, start=1):
            text = page.get_text() or ""
            if len(text.strip()) < _OCR_MIN_CHARS:
                if len(ocr_pages) >= _OCR_MAX_PAGES:
                    truncated = True
                    logger.warning("OCR 页数超过上限 %d, 第 %d 页起跳过", _OCR_MAX_PAGES, idx)
                else:
                    logger.info("🖼  第 %d 页无文本层, 执行 OCR ...", idx)
                    try:
                        ocr_text = _ocr_page(page)
                        if ocr_text.strip():
                            text = ocr_text
                            ocr_pages.append(idx)
                    except Exception as e:  # OCR 失败不应拖垮整个解析
                        logger.warning("第 %d 页 OCR 失败: %s", idx, e)
            pages.append({"page_no": idx, "text": text})
    finally:
        doc.close()
    if truncated:
        # 标记挂到调用方可读位置 (通过模块属性返回不方便, 用日志 + 末页标记)
        pages_meta = {"ocr_truncated": True}
    else:
        pages_meta = {"ocr_truncated": False}
    return pages, ocr_pages, pages_meta


def extract_text_pdf(path: str | Path) -> str:
    """PDF 全文提取 (PyMuPDF, 扫描页自动 OCR)."""
    pages, _ocr, _meta = extract_pages_pdf(path)
    return "\n".join(p["text"] for p in pages)


def extract_text_docx(path: str | Path) -> str:
    """Word 文档提取 (python-docx), 含表格."""
    from docx import Document
    doc = Document(str(path))
    parts: list[str] = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def extract_text_xlsx(path: str | Path) -> str:
    """Excel 招标文件提取 (openpyxl), 逐 sheet 逐行, 单元格以 | 连接."""
    import openpyxl
    wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    parts: list[str] = []
    try:
        for ws in wb.worksheets:
            parts.append(f"## Sheet: {ws.title}")
            for row in ws.iter_rows(values_only=True):
                cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
                if cells:
                    parts.append(" | ".join(cells))
    finally:
        wb.close()
    return "\n".join(parts)


def extract_text_txt(path: str | Path) -> str:
    """纯文本 (含 GBK 兼容)."""
    for enc in ("utf-8", "utf-8-sig", "gbk", "gb18030"):
        try:
            return Path(path).read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return Path(path).read_text(encoding="utf-8", errors="replace")


def extract_pages(path: str | Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """统一按页提取: 返回 (pages, meta).

    PDF 有真实页码 (扫描页 OCR); 其他格式无分页概念, page_no=None,
    引用溯源时仅显示文件名不伪造页码.
    meta: {"ocr_pages": [...], "ocr_truncated": bool}
    """
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".pdf":
        pages, ocr_pages, pages_meta = extract_pages_pdf(p)
        return pages, {"ocr_pages": ocr_pages, **pages_meta}
    text = extract_text(p)
    return [{"page_no": None, "text": text}], {"ocr_pages": [], "ocr_truncated": False}


def extract_text(path: str | Path) -> str:
    """根据扩展名路由."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".pdf":
        return extract_text_pdf(p)
    if ext in (".docx", ".doc"):
        if ext == ".doc":
            logger.warning(".doc 旧格式, 可能无法完整解析, 建议转 .docx")
        return extract_text_docx(p)
    if ext in (".xlsx", ".xls"):
        if ext == ".xls":
            logger.warning(".xls 旧格式建议另存为 .xlsx")
        return extract_text_xlsx(p)
    if ext in (".txt", ".md"):
        return extract_text_txt(p)
    raise ValueError(f"不支持的文件格式: {ext} (支持 .pdf/.docx/.xlsx/.txt/.md)")


# ---------- LLM 结构化抽取 ----------

_EXTRACT_SYSTEM = (
    "你是招投标文件解析专家. 根据用户提供的招标/投标文件内容, "
    "严格按指定 JSON schema 提取关键信息.\n"
    "规则:\n"
    "1. 只输出 JSON, 不要任何额外文字或代码块标记\n"
    "2. 找不到的字段填 null, 不要编造\n"
    "3. qualification_requirements 是数组, 每条一项资质要求\n"
    "4. 预算保留原文 (如 '人民币500万元' / '1000000元')\n"
    "5. 截止时间/开标时间保留原文, 不要格式化"
)


def _chunk_for_llm(text: str, head: int = 6000, tail: int = 2000) -> str:
    """大文件截断: 保留开头 (通常有项目名/编号/预算) + 结尾 (通常有截止时间/地点)."""
    if len(text) <= head + tail + 500:
        return text
    mid = "\n...[中间省略]...\n"
    return text[:head] + mid + text[-tail:]


def extract_structured(text: str, llm_client=None) -> dict[str, Any]:
    """LLM 结构化抽取. 失败时返回 fallback dict (含 raw_text)."""
    if llm_client is None:
        from src.clients.llm_factory import get_llm_client
        llm_client = get_llm_client()

    truncated = _chunk_for_llm(text)
    user_msg = (
        f"以下是招投标文件内容, 请按给定 schema 提取:\n\n"
        f"【Schema】\n{EXTRACT_SCHEMA}\n\n"
        f"【文件内容】\n{truncated}"
    )
    try:
        raw = llm_client.chat([
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user", "content": user_msg},
        ], temperature=0.1)
        # 清除可能的 ```json ... ``` 包装
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)
        result = json.loads(cleaned)
        # 补齐缺失 key
        for k in EXTRACT_SCHEMA.split('"')[1::2]:  # 取所有 key
            if k not in result:
                result[k] = None
        result["raw_text_preview"] = text[:2000]
        result["raw_text"] = text
        result["parse_status"] = "ok"
        return result
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("LLM JSON 解析失败: %s, 返回 fallback", e)
        return {
            "project_name": _guess_field(text, "项目名称"),
            "project_code": _guess_field(text, "项目编号|招标编号"),
            "purchaser": _guess_field(text, "采购人|招标人|建设单位"),
            "deadline": _guess_field(text, "投标截止时间|递交投标文件截止时间"),
            "parse_status": "partial",
            "error": str(e),
            "raw_text_preview": text[:2000],
            "raw_text": text,
        }


def _guess_field(text: str, patterns: str) -> str | None:
    """正则兜底: 简单 key:value 提取 (LLM 失败时)."""
    for pat in patterns.split("|"):
        m = re.search(rf"{pat}[::]\s*(.+?)(?:\n|$)", text)
        if m:
            return m.group(1).strip()[:100]
    return None


# ---------- 组合入口 ----------

def parse_file(path: str | Path, llm_client=None) -> dict[str, Any]:
    """完整解析: 文本提取 → LLM 结构化. 单函数便捷入口."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    logger.info("📄 解析文件: %s", p.name)
    pages, page_meta = extract_pages(p)
    text = "\n".join(pg["text"] for pg in pages)
    logger.info("  提取文本长度: %d 字符, %d 页 (其中 OCR 页: %s%s)",
                len(text), len(pages), page_meta.get("ocr_pages") or "无",
                ", 已截断" if page_meta.get("ocr_truncated") else "")
    structured = extract_structured(text, llm_client)
    structured["source_file"] = p.name
    structured["source_path"] = str(p.resolve())
    structured["text_length"] = len(text)
    structured["pages"] = pages
    structured["page_count"] = len(pages)
    structured["ocr_pages"] = page_meta.get("ocr_pages", [])
    structured["ocr_truncated"] = page_meta.get("ocr_truncated", False)
    return structured
