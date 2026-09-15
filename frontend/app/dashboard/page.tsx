"use client";
import { useEffect, useState } from "react";
import Link from "next/link";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8001";

interface DashboardData {
  agent: {
    total: number;
    status_breakdown: Record<string, number>;
    avg_elapsed_ms: number;
    tool_call_top: [string, number][];
  };
  knowledge_base: { points: number; ready: boolean };
  graph: { stats: { label: string; cnt: number }[]; ready: boolean };
  database: { rows: number; ready: boolean };
  system: { cpu: number; memory: number; disk: number };
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = () => {
      fetch(`${API_BASE}/api/dashboard`)
        .then(r => r.json())
        .then(d => { setData(d); setLoading(false); })
        .catch(() => setLoading(false));
    };
    load();
    const timer = setInterval(load, 10000);
    return () => clearInterval(timer);
  }, []);

  if (loading) return <div className="p-8 text-center text-gray-400">加载中...</div>;
  if (!data) return <div className="p-8 text-center text-red-500">加载失败</div>;

  // Null-safe defaults
  const agent = data.agent || { total: 0, status_breakdown: {}, avg_elapsed_ms: 0, tool_call_top: [] };
  const kb = data.knowledge_base || { points: 0, ready: false };
  const db = data.database || { rows: 0, ready: false };
  const graph = data.graph || { stats: [], ready: false };
  const sys = data.system || { cpu: 0, memory: 0, disk: 0 };
  const toolTop = agent.tool_call_top || [];
  const statusBreakdown = agent.status_breakdown || {};

  const statusColors: Record<string, string> = {
    ok: "bg-green-500", error: "bg-red-500",
    out_of_scope: "bg-yellow-500", vague: "bg-orange-500",
  };

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950 p-6">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">数据看板</h1>
          <Link href="/" className="text-blue-600 hover:underline text-sm">← 返回问答</Link>
        </div>

        {/* Top cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <StatCard label="知识库条目" value={kb.points} ready={kb.ready} color="blue" />
          <StatCard label="数据库记录" value={db.rows} ready={db.ready} color="purple" />
          <StatCard label="Agent 总请求" value={agent.total} ready={true} color="green" />
          <StatCard label="平均耗时(ms)" value={agent.avg_elapsed_ms} ready={true} color="orange" />
        </div>

        {/* System metrics */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
          <BarCard label="CPU 使用率" value={sys.cpu} color="bg-blue-500" />
          <BarCard label="内存使用率" value={sys.memory} color="bg-purple-500" />
          <BarCard label="磁盘使用率" value={sys.disk} color="bg-orange-500" />
        </div>

        {/* Agent status breakdown */}
        <div className="bg-white dark:bg-gray-900 rounded-xl p-5 mb-6">
          <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">Agent 请求状态分布</h2>
          {agent.total === 0 ? (
            <p className="text-gray-400 text-sm">暂无执行记录</p>
          ) : (
            <div className="space-y-2">
              {Object.entries(statusBreakdown).map(([status, count]) => {
                const pct = Math.round((count / agent.total) * 100);
                return (
                  <div key={status} className="flex items-center gap-3">
                    <span className="text-xs w-20 text-gray-600 dark:text-gray-400">{status}</span>
                    <div className="flex-1 h-6 bg-gray-100 dark:bg-gray-800 rounded overflow-hidden">
                      <div className={`h-full ${statusColors[status] || "bg-gray-400"} flex items-center px-2`}
                           style={{ width: `${Math.max(pct, 5)}%` }}>
                        <span className="text-xs text-white font-medium">{count}</span>
                      </div>
                    </div>
                    <span className="text-xs text-gray-400 w-10 text-right">{pct}%</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Tool call top */}
        <div className="bg-white dark:bg-gray-900 rounded-xl p-5 mb-6">
          <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">工具调用排行</h2>
          {toolTop.length === 0 ? (
            <p className="text-gray-400 text-sm">暂无工具调用</p>
          ) : (
            <div className="space-y-2">
              {toolTop.map(([name, count], i) => {
                const max = toolTop[0][1] || 1;
                const pct = Math.round((count / max) * 100);
                return (
                  <div key={name} className="flex items-center gap-3">
                    <span className="text-xs w-6 text-gray-400">#{i + 1}</span>
                    <span className="text-xs w-48 truncate text-gray-600 dark:text-gray-400">{name}</span>
                    <div className="flex-1 h-5 bg-gray-100 dark:bg-gray-800 rounded overflow-hidden">
                      <div className="h-full bg-blue-500 flex items-center px-2" style={{ width: `${pct}%` }}>
                        <span className="text-xs text-white">{count}</span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Knowledge graph stats */}
        <div className="bg-white dark:bg-gray-900 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">知识图谱节点统计</h2>
          {!graph.ready ? (
            <p className="text-gray-400 text-sm">Neo4j 未连接</p>
          ) : !graph.stats || graph.stats.length === 0 ? (
            <p className="text-gray-400 text-sm">暂无数据</p>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {(graph.stats || []).map((s) => (
                <div key={s.label} className="border border-gray-200 dark:border-gray-800 rounded-lg p-3 text-center">
                  <div className="text-2xl font-bold text-gray-900 dark:text-white">{s.cnt}</div>
                  <div className="text-xs text-gray-500 mt-1">{s.label}</div>
                </div>
              ))}
            </div>
          )}
          <div className="mt-4">
            <Link href="/graph" className="text-blue-600 hover:underline text-sm">查看图谱可视化 →</Link>
          </div>
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, ready, color }: { label: string; value: number; ready: boolean; color: string }) {
  const colors: Record<string, string> = {
    blue: "border-blue-500 text-blue-600 dark:text-blue-400",
    purple: "border-purple-500 text-purple-600 dark:text-purple-400",
    green: "border-green-500 text-green-600 dark:text-green-400",
    orange: "border-orange-500 text-orange-600 dark:text-orange-400",
  };
  return (
    <div className={`bg-white dark:bg-gray-900 rounded-xl p-4 border-l-4 ${colors[color]}`}>
      <div className="text-2xl font-bold">{ready ? value : "—"}</div>
      <div className="text-xs text-gray-500 mt-1">{label}</div>
      {!ready && <div className="text-xs text-red-400 mt-1">未连接</div>}
    </div>
  );
}

function BarCard({ label, value, color }: { label: string; value: number; color: string }) {
  const pct = Math.round(value || 0);
  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl p-4">
      <div className="flex justify-between items-center mb-2">
        <span className="text-sm text-gray-600 dark:text-gray-400">{label}</span>
        <span className="text-sm font-bold text-gray-900 dark:text-white">{pct}%</span>
      </div>
      <div className="h-4 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
        <div className={`h-full ${color} transition-all`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
