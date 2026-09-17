"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  RefreshCw, ChevronDown, ChevronRight, Bot, CheckCircle2, XCircle,
  MinusCircle, HelpCircle, Wrench, Clock, Database, Globe, Brain,
} from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8001";

interface Phase { name: string; ms: number }
interface ToolCall {
  round: number;
  name: string;
  sources_count: number;
  ms: number;
  quality_tag: string;
}
interface Audit {
  faithfulness_score?: number;
  total_sentences?: number;
  hallucinated_count?: number;
  cited_sources?: number;
}
interface Execution {
  trace_id: string;
  timestamp: string;
  question: string;
  provider: string;
  web_search: boolean;
  deep_thinking: boolean;
  phases: Phase[];
  tool_calls: ToolCall[];
  total_rounds: number;
  answer_snippet: string;
  sources_count: number;
  web_sources_count: number;
  audit: Audit | null;
  elapsed_ms: number;
  status: string;
  error: string;
}

const TOOL_LABELS: Record<string, string> = {
  search_bidding_knowledge: "知识库检索",
  search_knowledge_graph: "图谱查询",
  search_postgresql: "结构化查询",
  search_web: "联网搜索",
  search_exa: "Exa 搜索",
};

const STATUS_META: Record<string, { label: string; cls: string; icon: React.ReactNode }> = {
  ok: { label: "成功", cls: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300", icon: <CheckCircle2 size={13} /> },
  error: { label: "异常", cls: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300", icon: <XCircle size={13} /> },
  out_of_scope: { label: "超范围", cls: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300", icon: <MinusCircle size={13} /> },
  vague: { label: "信息不足", cls: "bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300", icon: <HelpCircle size={13} /> },
};

const FILTERS = [
  { key: "", label: "全部" },
  { key: "ok", label: "成功" },
  { key: "error", label: "异常" },
  { key: "out_of_scope", label: "超范围" },
  { key: "vague", label: "信息不足" },
];

function fmtTime(iso: string) {
  try {
    const d = new Date(iso);
    return d.toLocaleString("zh-CN", { hour12: false });
  } catch {
    return iso;
  }
}

function fmtMs(ms: number) {
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)}s`;
  return `${ms}ms`;
}

function toolIcon(name: string) {
  if (name.includes("web") || name.includes("exa")) return <Globe size={13} />;
  if (name.includes("graph")) return <Share2Icon />;
  if (name.includes("postgresql")) return <Database size={13} />;
  return <Brain size={13} />;
}

function Share2Icon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
         strokeLinecap="round" strokeLinejoin="round">
      <circle cx="18" cy="5" r="3" /><circle cx="6" cy="12" r="3" /><circle cx="18" cy="19" r="3" />
      <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
      <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
    </svg>
  );
}

export default function AgentTracePage() {
  const [executions, setExecutions] = useState<Execution[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [autoRefresh, setAutoRefresh] = useState(true);

  useEffect(() => {
    const load = () => {
      const url = `${API_BASE}/api/agent/executions?limit=50${filter ? `&status=${filter}` : ""}`;
      fetch(url)
        .then(r => r.json())
        .then(d => {
          setExecutions(Array.isArray(d.executions) ? d.executions : []);
          setLoading(false);
        })
        .catch(() => setLoading(false));
    };
    load();
    if (!autoRefresh) return;
    const timer = setInterval(load, 8000);
    return () => clearInterval(timer);
  }, [filter, autoRefresh]);

  // 默认展开最新一条
  useEffect(() => {
    if (executions.length > 0) {
      setExpanded(prev => {
        if (prev.__first) return prev;
        return { ...prev, [executions[0].trace_id]: true, __first: true } as Record<string, boolean>;
      });
    }
  }, [executions]);

  const maxPhaseMs = useMemo(
    () => Math.max(1, ...executions.flatMap(e => (e.phases || []).map(p => p.ms))),
    [executions],
  );

  const toggle = (id: string) => setExpanded(prev => ({ ...prev, [id]: !prev[id] }));

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950 p-6">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-2">
            <Bot className="text-blue-600" size={24} />
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Agent 执行过程</h1>
          </div>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer select-none">
              <input type="checkbox" checked={autoRefresh} onChange={e => setAutoRefresh(e.target.checked)} />
              自动刷新
            </label>
            <Link href="/" className="text-blue-600 hover:underline text-sm">← 返回问答</Link>
          </div>
        </div>

        {/* Filters */}
        <div className="flex items-center gap-2 mb-4 flex-wrap">
          {FILTERS.map(f => (
            <button key={f.key} onClick={() => setFilter(f.key)}
                    className={`px-3 py-1 rounded-full text-xs transition ${
                      filter === f.key
                        ? "bg-blue-600 text-white"
                        : "bg-white dark:bg-gray-900 text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"
                    }`}>
              {f.label}
            </button>
          ))}
        </div>

        {loading ? (
          <div className="text-center text-gray-400 py-16">加载中...</div>
        ) : executions.length === 0 ? (
          <div className="text-center py-16">
            <Wrench className="mx-auto text-gray-300 dark:text-gray-700 mb-3" size={40} />
            <p className="text-gray-400 text-sm">暂无 Agent 执行记录</p>
            <p className="text-gray-400 text-xs mt-1">在问答页提一个问题后，这里会展示完整的思考与工具调用过程</p>
            <Link href="/" className="inline-block mt-4 text-blue-600 hover:underline text-sm">去提问 →</Link>
          </div>
        ) : (
          <div className="space-y-3">
            {executions.map(e => {
              const meta = STATUS_META[e.status] || STATUS_META.ok;
              const open = !!expanded[e.trace_id];
              const rounds = Array.from(new Set((e.tool_calls || []).map(t => t.round))).sort((a, b) => a - b);
              const audit = e.audit || {};
              return (
                <div key={e.trace_id}
                     className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden">
                  {/* 卡片头(可点击展开) */}
                  <button onClick={() => toggle(e.trace_id)}
                          className="w-full text-left px-4 py-3 flex items-start gap-3 hover:bg-gray-50 dark:hover:bg-gray-800/50 transition">
                    {open ? <ChevronDown size={16} className="mt-1 text-gray-400 shrink-0" />
                          : <ChevronRight size={16} className="mt-1 text-gray-400 shrink-0" />}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap mb-1">
                        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${meta.cls}`}>
                          {meta.icon}{meta.label}
                        </span>
                        <span className="text-xs text-gray-400">{fmtTime(e.timestamp)}</span>
                        <span className="text-xs text-gray-400 flex items-center gap-1">
                          <Clock size={11} />{fmtMs(e.elapsed_ms || 0)}
                        </span>
                        {e.total_rounds > 0 && (
                          <span className="text-xs text-gray-400">{e.total_rounds} 轮推理</span>
                        )}
                      </div>
                      <p className="text-sm text-gray-800 dark:text-gray-200 line-clamp-2">{e.question}</p>
                    </div>
                  </button>

                  {open && (
                    <div className="px-4 pb-4 pl-11 border-t border-gray-100 dark:border-gray-800">
                      {/* 元信息 */}
                      <div className="flex items-center gap-2 flex-wrap mt-3 mb-4">
                        <span className="px-2 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-xs text-gray-500">
                          模型: {e.provider || "default"}
                        </span>
                        {e.deep_thinking && (
                          <span className="px-2 py-0.5 rounded bg-purple-100 dark:bg-purple-900/40 text-xs text-purple-600 dark:text-purple-300">
                            深度思考
                          </span>
                        )}
                        {e.web_search && (
                          <span className="px-2 py-0.5 rounded bg-cyan-100 dark:bg-cyan-900/40 text-xs text-cyan-600 dark:text-cyan-300">
                            联网搜索{e.web_sources_count > 0 ? ` · ${e.web_sources_count} 条来源` : ""}
                          </span>
                        )}
                        <span className="px-2 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-xs text-gray-500">
                          trace: {e.trace_id}
                        </span>
                      </div>

                      {/* 阶段时间线 */}
                      {(e.phases || []).length > 0 && (
                        <div className="mb-4">
                          <h3 className="text-xs font-semibold text-gray-500 mb-2">阶段耗时</h3>
                          <div className="space-y-1.5">
                            {e.phases.map((p, i) => (
                              <div key={i} className="flex items-center gap-2">
                                <span className="text-xs text-gray-600 dark:text-gray-400 w-20 shrink-0 truncate">{p.name}</span>
                                <div className="flex-1 h-5 bg-gray-100 dark:bg-gray-800 rounded overflow-hidden">
                                  <div className="h-full bg-gradient-to-r from-blue-400 to-blue-600 rounded flex items-center px-2"
                                       style={{ width: `${Math.max(8, Math.round((p.ms / maxPhaseMs) * 100))}%` }}>
                                    <span className="text-[10px] text-white whitespace-nowrap">{fmtMs(p.ms)}</span>
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* 工具调用(按轮分组) */}
                      {(e.tool_calls || []).length > 0 ? (
                        <div className="mb-4">
                          <h3 className="text-xs font-semibold text-gray-500 mb-2">
                            工具调用 ({e.tool_calls.length} 次)
                          </h3>
                          <div className="space-y-3">
                            {rounds.map(r => {
                              const roundTools = e.tool_calls.filter(t => t.round === r);
                              // 同一轮工具为并行批次, 日志里 ms 是整批墙钟耗时(各工具相同), 只在轮级别展示一次
                              const batchMs = Math.max(0, ...roundTools.map(t => t.ms || 0));
                              return (
                              <div key={r} className="border-l-2 border-blue-200 dark:border-blue-900 pl-3">
                                <div className="flex items-center justify-between mb-1.5">
                                  <span className="text-[11px] text-blue-500">
                                    第 {r} 轮 · {roundTools.length} 个工具并行
                                  </span>
                                  {batchMs > 0 && (
                                    <span className="text-[11px] text-gray-400">批次耗时 {fmtMs(batchMs)}</span>
                                  )}
                                </div>
                                <div className="space-y-1.5">
                                  {roundTools.map((t, i) => {
                                    const empty = t.sources_count === 0;
                                    return (
                                      <div key={i}
                                           className={`rounded-lg border px-3 py-2 ${
                                             empty
                                               ? "border-orange-200 dark:border-orange-900/50 bg-orange-50/50 dark:bg-orange-950/20"
                                               : "border-green-200 dark:border-green-900/50 bg-green-50/50 dark:bg-green-950/20"
                                           }`}>
                                        <div className="flex items-center gap-2 flex-wrap">
                                          <span className="text-gray-500">{toolIcon(t.name)}</span>
                                          <span className="text-xs font-medium text-gray-700 dark:text-gray-300">
                                            {TOOL_LABELS[t.name] || t.name}
                                          </span>
                                          <span className={`text-[11px] ${empty ? "text-orange-500" : "text-green-600 dark:text-green-400"}`}>
                                            {empty ? "0 条结果" : `${t.sources_count} 条来源`}
                                          </span>
                                        </div>
                                        {t.quality_tag && (
                                          <p className="text-[11px] text-gray-500 dark:text-gray-400 mt-1 line-clamp-2 whitespace-pre-line">
                                            {t.quality_tag.split("\n")[0]}
                                          </p>
                                        )}
                                      </div>
                                    );
                                  })}
                                </div>
                              </div>
                              );
                            })}
                          </div>
                        </div>
                      ) : (
                        <p className="text-xs text-gray-400 mb-4">本次未调用工具（前置拦截或直接作答）</p>
                      )}

                      {/* 审计 */}
                      {audit && audit.total_sentences ? (
                        <div className="mb-4 grid grid-cols-3 gap-2">
                          <div className="rounded-lg bg-gray-50 dark:bg-gray-800/60 p-2.5 text-center">
                            <div className={`text-lg font-bold ${
                              (audit.faithfulness_score ?? 0) >= 0.8 ? "text-green-600"
                              : (audit.faithfulness_score ?? 0) >= 0.5 ? "text-orange-500" : "text-red-500"}`}>
                              {Math.round((audit.faithfulness_score ?? 0) * 100)}%
                            </div>
                            <div className="text-[11px] text-gray-500">忠实度</div>
                          </div>
                          <div className="rounded-lg bg-gray-50 dark:bg-gray-800/60 p-2.5 text-center">
                            <div className="text-lg font-bold text-gray-800 dark:text-gray-200">{audit.total_sentences}</div>
                            <div className="text-[11px] text-gray-500">答案句数</div>
                          </div>
                          <div className="rounded-lg bg-gray-50 dark:bg-gray-800/60 p-2.5 text-center">
                            <div className={`text-lg font-bold ${(audit.hallucinated_count ?? 0) > 0 ? "text-red-500" : "text-green-600"}`}>
                              {audit.hallucinated_count ?? 0}
                            </div>
                            <div className="text-[11px] text-gray-500">疑似幻觉句</div>
                          </div>
                        </div>
                      ) : null}

                      {/* 错误信息 */}
                      {e.status === "error" && e.error && (
                        <div className="mb-4 rounded-lg bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900/50 px-3 py-2">
                          <p className="text-xs text-red-600 dark:text-red-400 whitespace-pre-line break-all">{e.error}</p>
                        </div>
                      )}

                      {/* 回答摘要 */}
                      {e.answer_snippet && (
                        <div>
                          <h3 className="text-xs font-semibold text-gray-500 mb-1.5">回答摘要</h3>
                          <p className="text-xs text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-gray-800/60 rounded-lg p-3 whitespace-pre-line">
                            {e.answer_snippet}
                          </p>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
