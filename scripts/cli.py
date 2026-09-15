"""CLI Slash Skill — 开发/运维一键命令.

用法:
  python scripts/cli.py ingest-data --src data/raw/ccgp_qa.xlsx
  python scripts/cli.py eval-rag --bootstrap
  python scripts/cli.py health-check
  python scripts/cli.py bid-analysis --subject "空调"
  python scripts/cli.py add-tool --name my_tool --desc "工具说明"
  python scripts/cli.py add-llm --provider myllm --model my-model

所有命令都委托给现有模块, 不重复实现.
"""
from __future__ import annotations

import sys
from pathlib import Path

# 自动把项目根加进 sys.path, 让用户不用手动 PYTHONPATH
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import json

import typer

app = typer.Typer(name="Bidding QA CLI", help="招投标 RAG 智能问答系统 开发运维命令")


# ============================================================
# /ingest-data
# ============================================================

@app.command("ingest-data", help="导入数据到 Qdrant (支持 Excel/CSV/JSONL)")
def cmd_ingest(
    src: str = typer.Option(None, "--src", "-s", help="源文件路径 (Excel/CSV/JSONL)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只预览, 不写入 Qdrant"),
    no_force: bool = typer.Option(False, "--no-force", help="增量追加, 不删 collection"),
    batch_size: int = typer.Option(32, "--batch-size", help="编码批大小"),
):
    """导入数据 — 委托 batch/ingest_real.py 的 main()."""
    typer.echo(f"📥 导入数据: src={src or '(自动查找)'}  dry_run={dry_run}  force={not no_force}")
    # 委托给现有脚本 (它用 argparse)
    import batch.ingest_real as m
    old_argv = sys.argv[:]
    sys.argv = ["ingest_real"]
    if src:
        sys.argv += ["--src", src]
    if dry_run:
        sys.argv += ["--dry-run"]
    if no_force:
        sys.argv += ["--no-force"]
    sys.argv += ["--batch-size", str(batch_size)]
    try:
        rc = m.main()
        typer.echo(f"完成, 返回码 {rc}")
    finally:
        sys.argv = old_argv


# ============================================================
# /eval-rag
# ============================================================

@app.command("eval-rag", help="RAG 检索评测 (Recall@K / Agent 评测)")
def cmd_eval(
    mode: str = typer.Option("recall", "--mode", "-m", help="recall | agent | ragas"),
    gt: str = typer.Option(None, "--gt", help="ground truth JSON 路径"),
    bootstrap: bool = typer.Option(False, "--bootstrap", help="从 data/test.xlsx 自举 GT"),
    top_k: int = typer.Option(20, "--top-k", help="评测 top_k"),
):
    """RAG 评测 — 委托 eval/ 下的脚本."""
    typer.echo(f"📊 RAG 评测: mode={mode}  top_k={top_k}")

    import sys as _sys

    old_argv = _sys.argv[:]
    _sys.argv = [f"eval_{mode}"]
    if gt:
        _sys.argv += ["--gt", gt]
    if bootstrap:
        _sys.argv += ["--bootstrap"]
    _sys.argv += ["--top-k", str(top_k)]

    try:
        if mode == "recall":
            import eval.recall_eval as m
        elif mode == "agent":
            import eval.agent_eval as m
        elif mode == "ragas":
            import eval.ragas_eval as m
        else:
            typer.echo(f"❌ 未知 mode: {mode} (recall|agent|ragas)")
            raise typer.Exit(1)
        m.main()
    finally:
        _sys.argv = old_argv


# ============================================================
# /health-check
# ============================================================

@app.command("health-check", help="一键检查所有组件连接状态")
def cmd_health(
    url: str = typer.Option("http://localhost:8001", "--url", help="后端 API 地址"),
):
    """健康检查 — 优先走 HTTP /api/health, 不可用时走直连探针."""
    typer.echo(f"🏥 健康检查: {url}")

    import json as _json
    import urllib.request

    health_url = url.rstrip("/") + "/api/health"
    try:
        with urllib.request.urlopen(health_url, timeout=5) as resp:
            data = _json.loads(resp.read())
        typer.echo("✅ 后端 API 可达")
        _print_health(data)
        return
    except Exception as e:
        typer.echo(f"⚠️  后端 API 不可达 ({e}), 直连探针...")

    # 直连探针
    results = {}
    try:
        from src.config import settings
        typer.echo(f"  配置文件加载: ✅ (qdrant_url={bool(settings.qdrant_url)}, "
                   f"pg={settings.postgres_host}:{settings.postgres_port})")
        results["config"] = True
    except Exception as e:
        typer.echo(f"  配置文件加载: ❌ {e}")
        results["config"] = False

    try:
        from src.rag.pipeline import rag_pipeline
        rag_pipeline.initialize()
        typer.echo(f"  RAG Pipeline: {'✅ ready' if rag_pipeline.ready else '⚠️  未就绪'}")
        results["rag"] = rag_pipeline.ready
    except Exception as e:
        typer.echo(f"  RAG Pipeline: ❌ {e}")
        results["rag"] = False

    try:
        from src.database.postgresql_client import postgresql_client
        postgresql_client.initialize()
        typer.echo(f"  PostgreSQL: {'✅ connected' if postgresql_client.ready else '⚠️  未连接'}")
        results["pg"] = postgresql_client.ready
    except Exception as e:
        typer.echo(f"  PostgreSQL: ❌ {e}")
        results["pg"] = False

    try:
        from src.database.neo4j_client import neo4j_client
        neo4j_client.initialize()
        typer.echo(f"  Neo4j: {'✅ connected' if neo4j_client.ready else '⚠️  未连接'}")
        results["neo4j"] = neo4j_client.ready
    except Exception as e:
        typer.echo(f"  Neo4j: ❌ {e}")
        results["neo4j"] = False

    ok = sum(1 for v in results.values() if v)
    total = len(results)
    typer.echo(f"\n📊 汇总: {ok}/{total} OK")
    if ok < total:
        raise typer.Exit(1)


def _print_health(data: dict) -> None:
    for k, v in data.items():
        if k == "latencies":
            typer.echo(f"  latencies:")
            for lk, lv in v.items():
                typer.echo(f"    {lk}: {lv}")
            continue
        icon = "✅" if v else "⚠️" if isinstance(v, bool) else "ℹ️"
        typer.echo(f"  {icon} {k}: {v}")


# ============================================================
# /bid-analysis
# ============================================================

@app.command("bid-analysis", help="一键对标分析 (价格 + 竞品)")
def cmd_bid_analysis(
    subject: str = typer.Option(..., "--subject", "-s", help="标的物关键词, 如 '空调'"),
    top_n: int = typer.Option(5, "--top-n", help="竞品 TOP N"),
):
    """价格对标 + 竞争对手分析 — 终端打印 Markdown 报告."""
    typer.echo(f"🔍 投标分析: {subject}\n")

    from src.clients.llm_factory import get_llm_client
    from src.tools.price_analyzer import analyze_price
    from src.tools.competitor_analyzer import analyze_competitors

    llm = get_llm_client()

    typer.echo("━" * 50)
    typer.echo("💰 价格对标分析")
    typer.echo("━" * 50)
    price = analyze_price(subject, llm_client=llm)
    _print_price(price)

    typer.echo("\n" + "━" * 50)
    typer.echo("🏢 竞争对手分析")
    typer.echo("━" * 50)
    comp = analyze_competitors(subject, top_n=top_n, llm_client=llm)
    _print_competitor(comp)

    typer.echo("\n" + "━" * 50)
    typer.echo("📊 数据来源: " + ", ".join(price.get("data_sources", ["none"]) + comp.get("data_sources", [])))
    typer.echo("━" * 50)


def _print_price(price: dict) -> None:
    if price.get("data_source") == "none":
        typer.echo(f"⚠️  {price.get('llm_comment', '无数据')}")
        return
    d = price.get("distribution", {})
    typer.echo(f"  样本数: {d.get('cnt', 0)}")
    typer.echo(f"  均价:   {d.get('avg_amount')}")
    typer.echo(f"  P25/P50/P75: {d.get('p25')} / {d.get('p50')} / {d.get('p75')}")
    typer.echo(f"  建议区间: {price.get('suggested_range', {}).get('description', '')}")
    if price.get("top_suppliers"):
        typer.echo("  中标供应商 TOP:")
        for s in price["top_suppliers"][:5]:
            typer.echo(f"    - {s.get('supplier')}: 中标{s.get('win_count')}次, 均价{s.get('avg_amount')}")
    comment = price.get("llm_comment")
    if comment:
        typer.echo(f"\n  💡 {comment[:300]}")


def _print_competitor(comp: dict) -> None:
    if not comp.get("top_suppliers") and not comp.get("graph_competitors"):
        typer.echo(f"⚠️  {comp.get('llm_comment', '无数据')}")
        return
    if comp.get("top_suppliers"):
        typer.echo("  中标 TOP (PG):")
        for s in comp["top_suppliers"][:5]:
            typer.echo(f"    - {s.get('supplier')}: 中标{s.get('win_count')}次")
    if comp.get("graph_competitors"):
        typer.echo("  竞品覆盖 (Neo4j):")
        for c in comp["graph_competitors"][:5]:
            typer.echo(f"    - {c.get('supplier')}: 覆盖{c.get('subject_count')}个标的物")
    comment = comp.get("llm_comment")
    if comment:
        typer.echo(f"\n  💡 {comment[:300]}")


# ============================================================
# /add-tool
# ============================================================

@app.command("add-tool", help="脚手架: 生成新 Tool 模板")
def cmd_add_tool(
    name: str = typer.Option(..., "--name", "-n", help="工具名, 如 'my_query'"),
    description: str = typer.Option("自定义工具", "--desc", "-d", help="工具描述"),
    output: str = typer.Option(None, "--output", "-o", help="输出文件路径 (默认 src/tools/<name>.py)"),
):
    """生成新 Tool 模板文件."""
    out_path = Path(output) if output else Path("src/tools") / f"{name}.py"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    template = f'''"""Tool: {name} — {description}."""
from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)

TOOL = {{
    "name": "{name}",
    "description": "{description}",
    "parameters": {{
        "type": "object",
        "properties": {{
            "query": {{"type": "string", "description": "查询/输入"}},
        }},
        "required": ["query"],
    }},
}}


def execute(args: dict, question: str = "") -> str:
    """执行工具, 返回字符串结果."""
    query = args.get("query", "")
    logger.info("Tool %s called: %s", "{name}", query)
    # TODO: 实现逻辑
    return f"[{name}] 收到 query={{query}}"


def register() -> dict:
    """返回 tool 定义 (rag_tools.py 用)."""
    return TOOL
'''
    out_path.write_text(template, encoding="utf-8")
    typer.echo(f"✅ Tool 模板已生成: {out_path}")
    typer.echo("  下一步: 在 src/tools/rag_tools.py 注册, 或直接在 Agent prompt 中声明.")


# ============================================================
# /add-llm
# ============================================================

@app.command("add-llm", help="脚手架: 生成新 LLM Provider 模板")
def cmd_add_llm(
    provider: str = typer.Option(..., "--provider", "-p", help="provider 名, 如 'myllm'"),
    base_url: str = typer.Option("https://api.example.com/v1", "--base-url"),
    model: str = typer.Option("gpt-4o-mini", "--model"),
    output: str = typer.Option(None, "--output", "-o", help="输出文件路径"),
):
    """生成新 LLM Provider 客户端模板."""
    out_path = Path(output) if output else Path("src/clients") / f"{provider}_client.py"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    template = f'''"""LLM Provider: {provider}."""
from __future__ import annotations
from src.clients.openai_compatible_client import OpenAICompatibleClient


class {provider.title()}Client(OpenAICompatibleClient):
    """继承 OpenAICompatibleClient, 自动兼容 chat()/chat_stream()/chat_raw()."""

    def __init__(self, model: str | None = None):
        from src.config import settings
        super().__init__(
            provider="{provider}",
            base_url=settings.{provider}_base_url,
            api_key=settings.{provider}_api_key,
            model=model or settings.{provider}_model,
        )
'''
    out_path.write_text(template, encoding="utf-8")
    typer.echo(f"✅ LLM Client 模板已生成: {out_path}")
    typer.echo("  下一步:")
    typer.echo("    1. pyproject.toml / .env 加三个配置:")
    typer.echo(f"       {provider.upper()}_BASE_URL={base_url}")
    typer.echo(f"       {provider.upper()}_API_KEY=your-key")
    typer.echo(f"       {provider.upper()}_MODEL={model}")
    typer.echo("    2. src/config.py 加三个对应字段")
    typer.echo(f"    3. src/clients/llm_factory.py 加 provider='{provider}' 分支")


if __name__ == "__main__":
    app()
