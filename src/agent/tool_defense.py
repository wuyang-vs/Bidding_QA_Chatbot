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
_JSON_RE = re.compile(r'\{"name":\s*"(search_\w+)",\s*"arguments":\s*(\{.*?\})\}', re.S)


def _parse_text_tool_calls(text: str):
    if not text:
        return None
    calls = []
    cleaned = text.replace("【DSML】", "").replace("<【", "<").replace("】>", ">")
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
    return calls or None


def to_fake_tool_calls(calls: list[dict]):
    """构造 SimpleNamespace 走与原生相同的执行管线"""
    return [SimpleNamespace(
        id=f"text-{i}",
        function=SimpleNamespace(name=c["name"], arguments=json.dumps(c["arguments"])),
    ) for i, c in enumerate(calls)]
