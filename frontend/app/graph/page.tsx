"use client";
import { useEffect, useRef, useState, useCallback } from "react";
import Link from "next/link";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8001";

interface GraphNode {
  id: string;
  name: string;
  type: string;
  freq?: number;
}
interface GraphEdge {
  source: string;
  target: string;
  relation: string;
}
interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  ready: boolean;
}

// 简易力导向布局 (无 d3 依赖)
function useForceLayout(nodes: GraphNode[], edges: GraphEdge[], width: number, height: number) {
  const [positions, setPositions] = useState<Record<string, {x: number; y: number; vx: number; vy: number}>>({});

  useEffect(() => {
    if (nodes.length === 0) {
      setPositions({});
      return;
    }

    // 初始化: 随机分布
    const pos: Record<string, {x: number; y: number; vx: number; vy: number}> = {};
    const cx = width / 2;
    const cy = height / 2;
    nodes.forEach((n, i) => {
      const angle = (i / nodes.length) * Math.PI * 2;
      const r = Math.min(width, height) * 0.3;
      pos[n.id] = {
        x: cx + Math.cos(angle) * r + (Math.random() - 0.5) * 20,
        y: cy + Math.sin(angle) * r + (Math.random() - 0.5) * 20,
        vx: 0, vy: 0,
      };
    });

    const edgeList = edges.map(e => ({ source: e.source, target: e.target }));
    let frame = 0;
    const maxFrames = 300;

    const tick = () => {
      if (frame >= maxFrames) return;
      frame++;

      // 斥力 (Coulomb)
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = pos[nodes[i].id];
          const b = pos[nodes[j].id];
          if (!a || !b) continue;
          let dx = a.x - b.x;
          let dy = a.y - b.y;
          let dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const force = 800 / (dist * dist);
          a.vx += (dx / dist) * force;
          a.vy += (dy / dist) * force;
          b.vx -= (dx / dist) * force;
          b.vy -= (dy / dist) * force;
        }
      }

      // 引力 (弹簧)
      for (const e of edgeList) {
        const a = pos[e.source];
        const b = pos[e.target];
        if (!a || !b) continue;
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        let dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const targetDist = 120;
        const force = (dist - targetDist) * 0.05;
        a.vx += (dx / dist) * force;
        a.vy += (dy / dist) * force;
        b.vx -= (dx / dist) * force;
        b.vy -= (dy / dist) * force;
      }

      // 向心力 + 阻尼 + 边界
      for (const n of nodes) {
        const p = pos[n.id];
        if (!p) continue;
        p.vx += (cx - p.x) * 0.005;
        p.vy += (cy - p.y) * 0.005;
        p.vx *= 0.85;
        p.vy *= 0.85;
        p.x += p.vx;
        p.y += p.vy;
        p.x = Math.max(30, Math.min(width - 30, p.x));
        p.y = Math.max(30, Math.min(height - 30, p.y));
      }

      setPositions({ ...pos });
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    // eslint-disable-next-line
  }, [nodes, edges]);

  return positions;
}

const TYPE_COLORS: Record<string, string> = {
  SubjectMatter: "#3b82f6",
  Purchaser: "#10b981",
  Supplier: "#f59e0b",
};

const RELATION_COLORS: Record<string, string> = {
  PURCHASED_BY: "#10b981",
  SUPPLIED_BY: "#f59e0b",
};

export default function GraphPage() {
  const [data, setData] = useState<GraphData>({ nodes: [], edges: [], ready: false });
  const [keyword, setKeyword] = useState("");
  const [loading, setLoading] = useState(true);
  const [hovered, setHovered] = useState<string | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const load = useCallback((kw = "") => {
    setLoading(true);
    fetch(`${API_BASE}/api/graph/subgraph?keyword=${encodeURIComponent(kw)}&limit=40`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const width = 900;
  const height = 600;
  const positions = useForceLayout(data.nodes, data.edges, width, height);

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950 p-6">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">知识图谱可视化</h1>
          <div className="flex items-center gap-4">
            <input
              value={keyword}
              onChange={e => setKeyword(e.target.value)}
              onKeyDown={e => e.key === "Enter" && load(keyword)}
              placeholder="搜索标的物..."
              className="px-3 py-1.5 border border-gray-300 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-900 text-sm text-gray-900 dark:text-white outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button onClick={() => load(keyword)}
                    className="px-3 py-1.5 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700">
              搜索
            </button>
            <Link href="/" className="text-blue-600 hover:underline text-sm">← 返回问答</Link>
          </div>
        </div>

        {/* Legend */}
        <div className="flex items-center gap-4 mb-4 text-xs">
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full bg-blue-500" />标的物</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full bg-green-500" />采购人</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full bg-orange-500" />供应商</span>
          <span className="text-gray-400">{data.nodes.length} 节点 / {data.edges.length} 关系</span>
        </div>

        {/* Graph */}
        <div className="bg-white dark:bg-gray-900 rounded-xl overflow-hidden border border-gray-200 dark:border-gray-800">
          {!data.ready ? (
            <div className="p-12 text-center text-gray-400">Neo4j 未连接，无法显示图谱</div>
          ) : loading ? (
            <div className="p-12 text-center text-gray-400">加载中...</div>
          ) : data.nodes.length === 0 ? (
            <div className="p-12 text-center text-gray-400">暂无图谱数据</div>
          ) : (
            <svg ref={svgRef} width={width} height={height} className="w-full" style={{ maxHeight: 600 }}>
              {/* Edges */}
              {data.edges.map((e, i) => {
                const s = positions[e.source];
                const t = positions[e.target];
                if (!s || !t) return null;
                return (
                  <line key={i} x1={s.x} y1={s.y} x2={t.x} y2={t.y}
                        stroke={RELATION_COLORS[e.relation] || "#999"} strokeOpacity={0.4} strokeWidth={1.5} />
                );
              })}
              {/* Nodes */}
              {data.nodes.map(n => {
                const p = positions[n.id];
                if (!p) return null;
                const color = TYPE_COLORS[n.type] || "#666";
                const radius = n.freq ? Math.max(8, Math.min(24, 8 + n.freq / 2)) : 12;
                const isHovered = hovered === n.id;
                return (
                  <g key={n.id} transform={`translate(${p.x}, ${p.y})`}
                     onMouseEnter={() => setHovered(n.id)}
                     onMouseLeave={() => setHovered(null)}
                     style={{ cursor: "pointer" }}>
                    <circle r={isHovered ? radius + 3 : radius} fill={color} fillOpacity={0.7} stroke={color} strokeWidth={2} />
                    <text textAnchor="middle" y={radius + 14}
                          fontSize={isHovered ? 12 : 10}
                          fill="currentColor"
                          className="text-gray-700 dark:text-gray-300">
                      {n.name.length > 12 ? n.name.slice(0, 12) + "..." : n.name}
                    </text>
                    {isHovered && (
                      <g transform={`translate(0, ${-radius - 10})`}>
                        <rect x={-50} y={-20} width={100} height={28} rx={4} fill="white" stroke="#ccc" />
                        <text textAnchor="middle" y={-2} fontSize={11} fill="#333">
                          {n.type} {n.freq ? `(${n.freq})` : ""}
                        </text>
                      </g>
                    )}
                  </g>
                );
              })}
            </svg>
          )}
        </div>

        {/* Node list */}
        {data.nodes.length > 0 && (
          <div className="mt-4 bg-white dark:bg-gray-900 rounded-xl p-4">
            <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">节点列表</h2>
            <div className="flex flex-wrap gap-2">
              {data.nodes.map(n => (
                <span key={n.id}
                      className="px-2 py-1 rounded text-xs border"
                      style={{ borderColor: TYPE_COLORS[n.type] || "#666", color: TYPE_COLORS[n.type] || "#666" }}>
                  {n.name}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
