"""调 DeepSeek API 从原始内容批量生成招投标 Q&A → sharegpt 格式。

用同步 httpx + ThreadPoolExecutor 并发 (避免 anyio 版本冲突)。

用法:
    python scripts/sft/build_domain_qa.py

输入: sources_legal.jsonl + sources_bid.jsonl + sources_qdrant.jsonl
输出: sft_domain.json (LLaMA-Factory sharegpt 格式)
"""
from __future__ import annotations
import json
import os
import re
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
OUT_DIR = Path(__file__).resolve().parent

# ── 配置 ──
CONCURRENCY = 8
MAX_RETRIES = 2
QA_PER_SOURCE = 1
MAX_SOURCE_LEN = 1500

GEN_PROMPT = """你是一位招投标领域专家。请基于以下原始内容，生成 {n} 条高质量的招投标问答对。

要求:
1. 问题须具体、可检索、有实际价值（不要泛泛而问）
2. 答案须严格基于原文内容，引用法规条文编号或具体数据，禁止编造
3. 答案须包含「根据」或「依据」或具体数字/条文号
4. 答案长度 50-500 字
5. 输出严格的 JSON 数组格式，不要其他内容

输出格式:
[{{"question": "问题内容", "answer": "答案内容"}}]

原始内容:
{content}"""


def _load_env():
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip("'\"")
        if k and k not in os.environ:
            os.environ[k] = v


_load_env()

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")


def _validate_qa(q: str, a: str) -> bool:
    if not q or not a:
        return False
    if len(q.strip()) < 8 or len(a.strip()) < 20:
        return False
    if len(a) > 600:
        return False
    if not re.search(r"根据|依据|第.{1,5}条|条规定|万元|\d+%", a):
        return False
    return True


def _gen_one(client: httpx.Client, source: dict, idx: int) -> list[dict]:
    content = source.get("content", "")
    if not content or len(content.strip()) < 20:
        return []
    content = content[:MAX_SOURCE_LEN]
    prompt = GEN_PROMPT.format(n=QA_PER_SOURCE, content=content)

    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = client.post(
                f"{BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {API_KEY}"},
                json={
                    "model": MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                    "max_tokens": 1024,
                },
                timeout=30,
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"]

            m = re.search(r'\[.*\]', text, re.S)
            if not m:
                continue
            pairs = json.loads(m.group())
            results = []
            for p in pairs:
                q = p.get("question", "").strip()
                a = p.get("answer", "").strip()
                if _validate_qa(q, a):
                    results.append({
                        "conversations": [
                            {"from": "human", "value": q},
                            {"from": "gpt", "value": a},
                        ]
                    })
            return results
        except Exception as e:
            if attempt == MAX_RETRIES:
                if idx % 50 == 0:
                    print(f"  [{idx}] 生成失败: {e}")
            continue
    return []


def main():
    all_sources = []
    for fname in ["sources_legal.jsonl", "sources_bid.jsonl", "sources_qdrant.jsonl"]:
        path = OUT_DIR / fname
        if not path.exists():
            print(f"跳过 {fname} (不存在)")
            continue
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                all_sources.append(json.loads(line))
    print(f"加载 {len(all_sources)} 条原始内容")

    if not all_sources:
        print("无数据, 请先运行 extract_sources.py")
        return

    all_qa = []
    seen = set()

    with httpx.Client() as client:
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            futures = {
                pool.submit(_gen_one, client, src, i): i
                for i, src in enumerate(all_sources)
            }
            done = 0
            for fut in as_completed(futures):
                done += 1
                if done % 50 == 0:
                    print(f"  进度: {done}/{len(all_sources)}")
                try:
                    results = fut.result()
                    for item in results:
                        q = item["conversations"][0]["value"]
                        if q not in seen:
                            seen.add(q)
                            all_qa.append(item)
                except Exception:
                    pass

    out_path = OUT_DIR / "sft_domain.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_qa, f, ensure_ascii=False, indent=2)

    print(f"\n生成 {len(all_qa)} 条 Q&A → {out_path}")


if __name__ == "__main__":
    main()
