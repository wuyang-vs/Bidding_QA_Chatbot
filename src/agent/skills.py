"""技能加载与匹配 (上下文注入, 非工具调用)"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


def _load_skills() -> dict:
    registry = {}
    if not SKILLS_DIR.exists():
        return registry
    for skill_file in SKILLS_DIR.glob("*/SKILL.md"):
        text = skill_file.read_text(encoding="utf-8")
        meta = {}
        body = text
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                for line in parts[1].strip().splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        meta[k.strip()] = v.strip()
                body = parts[2].strip()
        name = meta.get("name", skill_file.parent.name)
        desc = meta.get("description", "")
        alias = ""
        for sep in ("—", "-", "："):
            if sep in desc:
                alias = desc.split(sep)[0].strip()
                break
        registry[name] = {"description": desc, "body": body, "alias": alias or name}
    return registry


def _match_skills(question: str, history: list[dict], registry: dict) -> list[str]:
    matched = []
    for name, info in registry.items():
        if name in question or (info["alias"] and info["alias"] in question):
            matched.append(name)
            continue
        if any(k in question for k in ("该技能", "这个技能", "上述技能")):
            for msg in reversed(history or []):
                if msg.get("role") == "assistant" and name in msg.get("content", ""):
                    matched.append(name)
                    break
    return matched


AVAILABLE_SKILLS = _load_skills()

SKILLS_PROMPT = "可用技能（当用户问题匹配时自动加载指南并严格按指南执行）：\n" + \
    "\n".join(f"- {n}: {i['description']}" for n, i in AVAILABLE_SKILLS.items())
