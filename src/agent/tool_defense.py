from __future__ import annotations
"""工具文本检测/归一化/解析"""
import json
import re
from types import SimpleNamespace


def _looks_like_tool_call(text: str) -> bool:
    if not text:
        return False
    low = text.lower()
    if "<【" in low and "dsml" in low:
        return True
    # 全角竖线变体: <｜｜DSML｜｜ invoke ...> / <｜｜DSML｜｜/calls>
    if "｜｜dsml" in low or "dsml｜｜" in low:
        return True
    if low.startswith("<") or low.startswith("{"):
        head = low[:200]
        if any(k in head for k in ("tool_call", "invoke", "function_call", '"name"')):
            return True
    for marker in ("<tool", "<invoke", "<function_call",
                   '"name": "search_', '"function": {"name"',
                   "search_bidding_knowledge(", "search_knowledge_graph(",
                   "search_postgresql(", "search_web(", "search_exa("):
        if marker in low:
            return True
    if _GLM_TEXT_RE.search(text) or _GLM_BARE_RE.search(text):
        return True
    return False


def _normalize_tool_content(content: str) -> str:
    if content and _looks_like_tool_call(content):
        return ""
    return content or ""


_INVOKE_RE = re.compile(
    r'<invoke\s+name="([^"]+)"[^>]*>(.*?)(?=<invoke|</tool_calls>|$)', re.S)
_PARAM_RE = re.compile(r'<parameter\s+name="([^"]+)"[^>]*>(.*?)</parameter>', re.S)
_TOOLCALL_RE = re.compile(r'<tool_call>(.*?)</tool_call>', re.S)
_NAME_RE = re.compile(r'<name>(.*?)</name>', re.S)
# GLM-4 原生工具调用为 {"name": ..., "parameters": ...}, OpenAI 风格为 "arguments", 两者都接受
_JSON_RE = re.compile(
    r'\{"name":\s*"(search_\w+)",\s*"(?:arguments|parameters)":\s*(\{.*?\})\}', re.S)

# GLM-4 原生文本形态: <|assistant|> tool_name 换行 {args json} (vLLM 无 glm4 parser 时的文本输出)
_GLM_TEXT_RE = re.compile(
    r'<\|assistant\|>\s*(search_\w+)[ \t]*\r?\n[ \t]*(\{.*?\})', re.S)
# 同形态的裸变体: 工具名在行首 (后续轮次模型可能不再输出 <|assistant|> 标记)
_GLM_BARE_RE = re.compile(
    r'^[ \t]*(search_\w+)[ \t]*\r?\n[ \t]*(\{[^\n\r]*\})', re.M)


# 全角竖线 DSML 控制令牌: <｜｜DSML｜｜ invoke ...> / </｜｜DSML｜｜ invoke>
_FW_DSML_OPEN_RE = re.compile(r"<｜\s*｜\s*DSML\s*｜\s*｜\s*", re.I)
_FW_DSML_CLOSE_RE = re.compile(r"</\s*｜\s*｜\s*DSML\s*｜\s*｜\s*", re.I)


def _parse_text_tool_calls(text: str):
    if not text:
        return None
    calls = []
    cleaned = text.replace("【DSML】", "").replace("<【", "<").replace("】>", ">")
    # 归一化全角 DSML 变体为半角 XML 形态后再走既有解析
    cleaned = _FW_DSML_OPEN_RE.sub("<", cleaned)
    cleaned = _FW_DSML_CLOSE_RE.sub("</", cleaned)
    cleaned = (cleaned.replace("< invoke", "<invoke")
                      .replace("< parameter", "<parameter")
                      .replace("</ parameter", "</parameter"))
    for m in _INVOKE_RE.finditer(cleaned):
        name, body = m.group(1), m.group(2)
        args = {pm.group(1): pm.group(2).strip() for pm in _PARAM_RE.finditer(body)}
        calls.append({"name": name, "arguments": args})
    for m in _TOOLCALL_RE.finditer(cleaned):
        body = m.group(1)
        nm = _NAME_RE.search(body)
        if not nm:
            continue
        args = {pm.group(1): pm.group(2).strip()
                for pm in re.finditer(r'<(\w+)>(.*?)</\1>', body, re.S)
                if pm.group(1) != "name"}
        calls.append({"name": nm.group(1).strip(), "arguments": args})
    for m in _JSON_RE.finditer(text):
        try:
            args = json.loads(m.group(2))
            if isinstance(args, dict):
                calls.append({"name": m.group(1), "arguments": args})
        except json.JSONDecodeError:
            continue
    for m in _GLM_TEXT_RE.finditer(cleaned):
        try:
            args = json.loads(m.group(2))
            if isinstance(args, dict):
                calls.append({"name": m.group(1), "arguments": args})
        except json.JSONDecodeError:
            continue
    for m in _GLM_BARE_RE.finditer(cleaned):
        try:
            args = json.loads(m.group(2))
            if isinstance(args, dict):
                calls.append({"name": m.group(1), "arguments": args})
        except json.JSONDecodeError:
            continue
    return calls or None


def to_fake_tool_calls(calls: list[dict]):
    """构造 SimpleNamespace 走与原生相同的执行管线"""
    return [SimpleNamespace(
        id=f"text-{i}",
        function=SimpleNamespace(name=c["name"], arguments=json.dumps(c["arguments"])),
    ) for i, c in enumerate(calls)]
