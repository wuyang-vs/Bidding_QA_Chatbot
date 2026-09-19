"use client";

import { useEffect, useRef, useState, type ReactNode, type ComponentType } from "react";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import { FileText, Upload, Loader2, CheckCircle, AlertCircle, Eye, X, Shield, ClipboardCheck, AlertTriangle, CheckSquare, FileWarning, UserCheck, History, FileCheck, User, LogOut, Calculator, FileSearch, Radar, PenLine, Download, Copy, Building2, BookOpen } from "lucide-react";
import AlertModal, { type AlertPayload } from "@/components/AlertModal";

interface ParsedDoc {
  db_id?: number;
  source_file?: string;
  parse_status?: string;
  project_name?: string | null;
  project_code?: string | null;
  purchaser?: string | null;
  agency?: string | null;
  subject_matter?: string | null;
  budget?: string | null;
  qualification_requirements?: string[] | null;
  scoring_criteria?: string | null;
  deadline?: string | null;
  opening_time?: string | null;
  location?: string | null;
  text_length?: number;
  raw_text_preview?: string;
  error?: string;
}

interface ListDoc {
  id: number;
  source_file: string;
  project_name?: string | null;
  purchaser?: string | null;
  budget?: string | null;
  parse_status?: string;
  created_at?: string;
}

interface ComplianceRisk {
  rule_id: string;
  category: string;
  risk_level: string;
  matched_text: string;
  law_basis: string;
  detail: string;
}

interface ComplianceResult {
  summary: { high: number; medium: number; low: number; total_checked: number; risks_found: number };
  risks: ComplianceRisk[];
  clean_rules: string[];
  status: "ok" | "attention" | "warn";
  note?: string;
  docId?: number;
}

interface QualCheckItem {
  requirement: string;
  status: "FULL_MATCH" | "PARTIAL_MATCH" | "NO_MATCH" | "INFO_MISSING" | string;
  matched_qualification?: string;
  detail?: string;
}

interface QualificationResult {
  summary: { total_req: number; full: number; partial: number; missing: number; coverage?: string };
  checks: QualCheckItem[];
  gap_report?: string;
  verdict?: string;
  docId?: number;
}

interface RejectionClause {
  id: string;
  category: string;
  clause_text: string;
  requirement?: string;
  risk_level: "高" | "中" | "低" | string;
  tip?: string;
}

interface RejectionSelfCheck {
  clause_id: string;
  status: "safe" | "risk" | "uncertain" | string;
  reason?: string;
}

interface RejectionResult {
  summary: { total_clauses: number; by_category: Record<string, number>; risk_count: number };
  clauses: RejectionClause[];
  self_check: RejectionSelfCheck[] | null;
  verdict: "unknown" | "safe" | "attention" | "danger" | string;
  note?: string;
  docId?: number;
}

interface ResponseClause {
  id: string;
  clause_no?: string;
  category: string;
  tender_clause: string;
  requirement?: string;
  status: "response" | "positive" | "negative" | "none" | string;
  evidence?: string;
  detail?: string;
}

interface ResponseResult {
  summary: { total: number; response: number; positive: number; negative: number; none: number };
  clauses: ResponseClause[];
  verdict: "pass" | "attention" | "danger" | "unknown" | string;
  note?: string;
  docId?: number;
}

interface ScoringItem {
  id: string;
  dimension: string;
  weight: number;
  max_score: number;
  scoring_rule?: string;
}

interface ScoringResult {
  total_score: number;
  items: ScoringItem[];
  note?: string;
  docId?: number;
}

interface CompareResult {
  fields: string[];
  bidders: { name: string; values: Record<string, string> }[];
  note?: string;
}

interface ReviewRecord {
  id: number;
  document_id: number;
  review_type: "compliance" | "qualification" | "rejection" | string;
  verdict: "approved" | "rejected" | string;
  comment?: string;
  reviewer?: string;
  created_at?: string;
}

const API = "http://localhost:8001";

// 正文中的 [占位符] 黄色高亮 (ReactMarkdown 自定义渲染)
function splitPlaceholders(text: string): ReactNode {
  const parts = text.split(/(\[[^\[\]\n]{1,40}\])/g);
  return parts.map((p, i) =>
    p.startsWith("[") && p.endsWith("]") ? (
      <mark key={i} className="bg-amber-200 dark:bg-amber-500/40 text-amber-900 dark:text-amber-100 rounded px-0.5">{p}</mark>
    ) : (
      <span key={i}>{p}</span>
    )
  );
}
function hlChildren(children: ReactNode): ReactNode {
  return Array.isArray(children)
    ? children.map((c: ReactNode) => (typeof c === "string" ? splitPlaceholders(c) : c))
    : (typeof children === "string" ? splitPlaceholders(children) : children);
}
const MD_HL: Record<string, ComponentType<any>> = {
  p: ({ children }) => <p>{hlChildren(children)}</p>,
  li: ({ children }) => <li>{hlChildren(children)}</li>,
  td: ({ children }) => <td>{hlChildren(children)}</td>,
  th: ({ children }) => <th>{hlChildren(children)}</th>,
  h1: ({ children }) => <h1>{hlChildren(children)}</h1>,
  h2: ({ children }) => <h2>{hlChildren(children)}</h2>,
  h3: ({ children }) => <h3>{hlChildren(children)}</h3>,
  h4: ({ children }) => <h4>{hlChildren(children)}</h4>,
};
function remainingPlaceholders(md: string): string[] {
  const set = new Set<string>();
  const re = /\[([^\[\]\n]{1,40})\]/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(md))) set.add(m[1]);
  return Array.from(set);
}

function Field({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="grid grid-cols-[110px_1fr] gap-2 py-2 border-b border-gray-100 dark:border-gray-800">
      <div className="text-xs text-gray-500 dark:text-gray-400">{label}</div>
      <div className="text-sm text-gray-900 dark:text-gray-100 break-words">
        {value ? value : <span className="text-gray-300 dark:text-gray-600 text-xs">—</span>}
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: "ok" | "attention" | "warn" | "loading" }) {
  const map = {
    ok: { text: "合规", cls: "bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200" },
    attention: { text: "注意", cls: "bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200" },
    warn: { text: "风险", cls: "bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-200" },
    loading: { text: "检查中", cls: "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300" },
  };
  const m = map[status];
  return <span className={`text-xs px-2 py-0.5 rounded font-medium ${m.cls}`}>{m.text}</span>;
}

// ================== 人工复核 (通用, 三类检查共用) ==================

function ReviewBox({ docId, type, accent, snapshot }: {
  docId: number;
  type: "compliance" | "qualification" | "rejection" | "response" | "scoring";
  accent: "purple" | "blue" | "orange";
  snapshot: unknown;
}) {
  const [records, setRecords] = useState<ReviewRecord[]>([]);
  const [reviewer, setReviewer] = useState("");
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setReviewer(localStorage.getItem("bid_reviewer") || "");
    fetch(`${API}/api/reviews?document_id=${docId}&review_type=${type}`)
      .then((r) => r.json())
      .then((j) => setRecords(j.items || []))
      .catch(() => {});
  }, [docId, type]);

  const accentText = {
    purple: "text-purple-600",
    blue: "text-blue-600",
    orange: "text-orange-600",
  }[accent];

  const submit = async (verdict: "approved" | "rejected") => {
    setSubmitting(true);
    setError(null);
    try {
      if (reviewer.trim()) localStorage.setItem("bid_reviewer", reviewer.trim());
      const r = await fetch(`${API}/api/reviews`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document_id: docId, review_type: type, verdict,
          comment: comment.trim(), reviewer: reviewer.trim(),
          result_snapshot: snapshot,
        }),
      });
      if (!r.ok) throw new Error(await r.text());
      setComment("");
      const j = await fetch(`${API}/api/reviews?document_id=${docId}&review_type=${type}`);
      const data = await j.json();
      setRecords(data.items || []);
    } catch (e: any) {
      setError(e?.message || "保存失败");
    } finally {
      setSubmitting(false);
    }
  };

  const latest = records[0];

  return (
    <div className="mt-4 border-t border-gray-200 dark:border-gray-800 pt-4">
      <div className="flex items-center gap-2 mb-2">
        <UserCheck size={15} className={accentText} />
        <span className="text-xs font-medium text-gray-700 dark:text-gray-300">人工确认 / 审计留痕</span>
        {latest && (
          <span className={`text-xs px-2 py-0.5 rounded font-medium ${
            latest.verdict === "approved"
              ? "bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200"
              : "bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-200"}`}>
            最新结论: {latest.verdict === "approved" ? "✅ 已确认" : "❌ 已驳回"}
            {latest.reviewer ? ` · ${latest.reviewer}` : ""}
          </span>
        )}
      </div>

      <div className="flex gap-2 mb-2">
        <input
          value={reviewer}
          onChange={(e) => setReviewer(e.target.value)}
          placeholder="复核人姓名"
          className="w-32 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 px-2 py-1.5 text-xs text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-gray-400"
        />
        <input
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="复核备注 (可选) — 如: 已人工核对原文, 风险属实"
          className="flex-1 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 px-2 py-1.5 text-xs text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-gray-400"
        />
        <button
          onClick={() => submit("approved")}
          disabled={submitting}
          className="px-3 py-1.5 text-xs bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white rounded-lg transition whitespace-nowrap">
          {submitting ? <Loader2 className="animate-spin" size={12} /> : <CheckCircle size={12} className="inline mr-1" />}
          确认通过
        </button>
        <button
          onClick={() => submit("rejected")}
          disabled={submitting}
          className="px-3 py-1.5 text-xs bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white rounded-lg transition whitespace-nowrap">
          <X size={12} className="inline mr-1" />驳回
        </button>
      </div>
      {error && <div className="text-xs text-red-600 mb-1">{error}</div>}

      {records.length > 0 && (
        <details className="text-xs">
          <summary className="text-gray-400 cursor-pointer hover:text-gray-600 flex items-center gap-1">
            <History size={12} /> 复核历史 ({records.length})
          </summary>
          <div className="mt-2 space-y-1 max-h-40 overflow-auto">
            {records.map((r) => (
              <div key={r.id} className="flex items-start gap-2 text-gray-600 dark:text-gray-400">
                <span className={`flex-shrink-0 px-1.5 py-0.5 rounded text-[11px] ${
                  r.verdict === "approved"
                    ? "bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-300"
                    : "bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-300"}`}>
                  {r.verdict === "approved" ? "确认" : "驳回"}
                </span>
                <span className="flex-1 break-words">
                  {r.reviewer && <span className="font-medium">{r.reviewer}: </span>}
                  {r.comment || "(无备注)"}
                </span>
                <span className="text-gray-400 flex-shrink-0">
                  {r.created_at ? new Date(r.created_at).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : ""}
                </span>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

// ================== 合规结果展示 ==================

function CompliancePanel({ result, onClose }: { result: ComplianceResult; onClose?: () => void }) {
  const { summary, risks, status, note } = result;
  const totalRisk = summary.high + summary.medium + summary.low;

  return (
    <div className="mt-4 border border-gray-200 dark:border-gray-800 rounded-xl overflow-hidden">
      <div className="bg-purple-50 dark:bg-purple-950/30 border-b border-purple-200 dark:border-purple-800 p-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Shield className="text-purple-600" size={18} />
          <span className="text-sm font-medium text-purple-900 dark:text-purple-100">合规性检查</span>
          <StatusBadge status={status} />
        </div>
        {onClose && (
          <button onClick={onClose} className="text-purple-500 hover:text-purple-700 text-xs">关闭</button>
        )}
      </div>

      <div className="p-5">
        {/* 摘要统计 */}
        <div className="flex flex-wrap gap-4 mb-4">
          <div className="text-center">
            <div className="text-2xl font-bold text-gray-900 dark:text-gray-100">{summary.total_checked}</div>
            <div className="text-xs text-gray-500">总规则</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-red-600">{summary.high}</div>
            <div className="text-xs text-gray-500">高风险</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-yellow-600">{summary.medium}</div>
            <div className="text-xs text-gray-500">中风险</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-gray-600">{risks.length}</div>
            <div className="text-xs text-gray-500">风险条款</div>
          </div>
        </div>

        {note && (
          <div className="mb-3 text-xs text-yellow-700 dark:text-yellow-300 bg-yellow-50 dark:bg-yellow-950/40 rounded p-2">
            {note}
          </div>
        )}

        {/* 风险列表 */}
        {risks.length > 0 ? (
          <div className="space-y-2">
            {risks.map((r, i) => (
              <div key={i} className={`border rounded-lg p-3 ${
                r.risk_level === "高" ? "border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950/20" :
                r.risk_level === "中" ? "border-yellow-200 dark:border-yellow-800 bg-yellow-50 dark:bg-yellow-950/20" :
                "border-gray-200 dark:border-gray-800"
              }`}>
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <AlertTriangle size={14} className={r.risk_level === "高" ? "text-red-600" : "text-yellow-600"} />
                    <span className="text-sm font-medium text-gray-900 dark:text-gray-100">{r.category}</span>
                    <span className="text-xs px-1.5 py-0.5 bg-gray-200 dark:bg-gray-700 rounded">{r.rule_id}</span>
                    <span className={`text-xs px-1.5 py-0.5 rounded ${
                      r.risk_level === "高" ? "bg-red-200 text-red-800" : "bg-yellow-200 text-yellow-800"
                    }`}>{r.risk_level}风险</span>
                  </div>
                </div>
                <div className="mt-2 text-sm text-gray-700 dark:text-gray-300">{r.detail}</div>
                {r.matched_text && (
                  <blockquote className="mt-2 pl-3 border-l-2 border-purple-400 text-xs text-gray-600 dark:text-gray-400 italic">
                    "{r.matched_text}"
                  </blockquote>
                )}
                <div className="mt-2 text-xs text-gray-500">📖 {r.law_basis}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-sm text-green-700 dark:text-green-300 bg-green-50 dark:bg-green-950/30 rounded p-3 flex items-center gap-2">
            <CheckCircle size={16} /> 未发现明显风险条款
          </div>
        )}

        {result.docId != null && (
          <ReviewBox docId={result.docId} type="compliance" accent="purple" snapshot={{ summary, status }} />
        )}
      </div>
    </div>
  );
}

// ================== 资格检查结果 ==================

function QualificationPanel({ result, onClose }: { result: QualificationResult; onClose?: () => void }) {
  const { summary, checks, gap_report, verdict } = result;

  const badge = (s: string) => {
    const map: Record<string, string> = {
      FULL_MATCH: "bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200",
      NO_MATCH: "bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-200",
      PARTIAL_MATCH: "bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200",
      INFO_MISSING: "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300",
    };
    const label: Record<string, string> = {
      FULL_MATCH: "✅ 满足",
      NO_MATCH: "❌ 缺失",
      PARTIAL_MATCH: "⚠️ 部分",
      INFO_MISSING: "❓ 不明",
    };
    return <span className={`text-xs px-2 py-0.5 rounded font-medium ${map[s] || "bg-gray-200 text-gray-700"}`}>{label[s] || s}</span>;
  };

  const verdictMap: Record<string, { text: string; cls: string }> = {
    pass: { text: "✅ 通过", cls: "bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200" },
    attention: { text: "⚠️ 注意", cls: "bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200" },
    fail: { text: "❌ 不通过", cls: "bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-200" },
    unknown: { text: "❓ 未知", cls: "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300" },
  };

  return (
    <div className="mt-4 border border-gray-200 dark:border-gray-800 rounded-xl overflow-hidden">
      <div className="bg-blue-50 dark:bg-blue-950/30 border-b border-blue-200 dark:border-blue-800 p-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ClipboardCheck className="text-blue-600" size={18} />
          <span className="text-sm font-medium text-blue-900 dark:text-blue-100">资格条件审查</span>
          {verdict && (
            <span className={`text-xs px-2 py-0.5 rounded font-medium ${verdictMap[verdict]?.cls || ""}`}>
              {verdictMap[verdict]?.text || verdict}
            </span>
          )}
        </div>
        {onClose && (
          <button onClick={onClose} className="text-blue-500 hover:text-blue-700 text-xs">关闭</button>
        )}
      </div>

      <div className="p-5">
        <div className="flex flex-wrap gap-4 mb-4">
          <div className="text-center">
            <div className="text-2xl font-bold text-gray-900 dark:text-gray-100">{summary.total_req}</div>
            <div className="text-xs text-gray-500">总要求</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-green-600">{summary.full}</div>
            <div className="text-xs text-gray-500">满足</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-yellow-600">{summary.partial}</div>
            <div className="text-xs text-gray-500">部分</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-red-600">{summary.missing}</div>
            <div className="text-xs text-gray-500">缺失</div>
          </div>
          {summary.coverage && (
            <div className="text-center">
              <div className="text-2xl font-bold text-blue-600">{summary.coverage}</div>
              <div className="text-xs text-gray-500">覆盖率</div>
            </div>
          )}
        </div>

        {gap_report && (
          <details className="mb-3">
            <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-700">
              查看缺口报告
            </summary>
            <pre className="mt-2 p-3 bg-gray-50 dark:bg-gray-900 text-xs text-gray-700 dark:text-gray-300 rounded-lg overflow-auto max-h-64 whitespace-pre-wrap font-sans">
              {gap_report}
            </pre>
          </details>
        )}

        {checks.length > 0 ? (
          <div className="space-y-2">
            {checks.map((r, i) => (
              <div key={i} className="border border-gray-200 dark:border-gray-800 rounded-lg p-3 flex items-start gap-3">
                <CheckSquare size={14} className="mt-1 text-gray-400 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-gray-900 dark:text-gray-100 break-words">{r.requirement}</div>
                  {r.matched_qualification && (
                    <div className="text-xs text-gray-500 dark:text-gray-400 mt-1 italic break-words">
                      匹配资质: {r.matched_qualification}
                    </div>
                  )}
                  {r.detail && (
                    <div className="text-xs text-gray-600 dark:text-gray-400 mt-1">{r.detail}</div>
                  )}
                </div>
                <div className="flex-shrink-0">{badge(r.status)}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-sm text-gray-500 bg-gray-50 dark:bg-gray-900 rounded p-3">
            暂无资质要求可比对
          </div>
        )}

        {result.docId != null && (
          <ReviewBox docId={result.docId} type="qualification" accent="blue" snapshot={{ summary, verdict }} />
        )}
      </div>
    </div>
  );
}

// ================== 废标条款检查结果 ==================

function RejectionPanel({ result, onClose }: { result: RejectionResult; onClose?: () => void }) {
  const { summary, clauses, self_check, verdict, note } = result;

  const verdictMap: Record<string, { text: string; cls: string }> = {
    safe: { text: "✅ 自查通过", cls: "bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200" },
    attention: { text: "⚠️ 部分待确认", cls: "bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200" },
    danger: { text: "❌ 存在废标风险", cls: "bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-200" },
    unknown: { text: "条款清单", cls: "bg-orange-100 dark:bg-orange-900 text-orange-800 dark:text-orange-200" },
  };

  const riskCls = (lv: string) =>
    lv === "高" ? "bg-red-100 dark:bg-red-900/60 text-red-700 dark:text-red-300"
    : lv === "中" ? "bg-yellow-100 dark:bg-yellow-900/60 text-yellow-700 dark:text-yellow-300"
    : "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400";

  const selfBadge = (s: string) => {
    const map: Record<string, { t: string; c: string }> = {
      safe: { t: "✅ 安全", c: "bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200" },
      risk: { t: "❌ 风险", c: "bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-200" },
      uncertain: { t: "❓ 待确认", c: "bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200" },
    };
    const m = map[s] || { t: s, c: "bg-gray-200 text-gray-700" };
    return <span className={`text-xs px-2 py-0.5 rounded font-medium ${m.c}`}>{m.t}</span>;
  };

  const checkMap: Record<string, RejectionSelfCheck> = {};
  (self_check || []).forEach((c) => { checkMap[c.clause_id] = c; });

  const cats = Object.entries(summary.by_category || {});

  return (
    <div className="mt-4 border border-gray-200 dark:border-gray-800 rounded-xl overflow-hidden">
      <div className="bg-orange-50 dark:bg-orange-950/30 border-b border-orange-200 dark:border-orange-800 p-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <FileWarning className="text-orange-600" size={18} />
          <span className="text-sm font-medium text-orange-900 dark:text-orange-100">废标条款检查</span>
          <span className={`text-xs px-2 py-0.5 rounded font-medium ${verdictMap[verdict]?.cls || verdictMap.unknown.cls}`}>
            {verdictMap[verdict]?.text || "条款清单"}
          </span>
        </div>
        {onClose && (
          <button onClick={onClose} className="text-orange-500 hover:text-orange-700 text-xs">关闭</button>
        )}
      </div>

      <div className="p-5">
        {/* 统计 */}
        <div className="flex flex-wrap gap-4 mb-4">
          <div className="text-center">
            <div className="text-2xl font-bold text-gray-900 dark:text-gray-100">{summary.total_clauses}</div>
            <div className="text-xs text-gray-500">废标条款</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-red-600">{summary.risk_count}</div>
            <div className="text-xs text-gray-500">高风险项</div>
          </div>
          {cats.map(([cat, n]) => (
            <div key={cat} className="text-center">
              <div className="text-lg font-bold text-orange-600">{n}</div>
              <div className="text-xs text-gray-500">{cat}</div>
            </div>
          ))}
        </div>

        {note && (
          <div className="mb-3 text-xs text-yellow-700 dark:text-yellow-300 bg-yellow-50 dark:bg-yellow-950/40 rounded p-2">
            {note}
          </div>
        )}

        {clauses.length === 0 ? (
          <div className="text-sm text-gray-500 bg-gray-50 dark:bg-gray-900 rounded p-3">
            未识别到废标条款
          </div>
        ) : (
          <div className="space-y-2">
            {clauses.map((c) => {
              const chk = checkMap[c.id];
              return (
                <div key={c.id} className={`border rounded-lg p-3 ${
                  chk?.status === "risk"
                    ? "border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-950/20"
                    : "border-gray-200 dark:border-gray-800"
                }`}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap mb-1">
                        <span className="text-xs font-mono text-gray-400">{c.id}</span>
                        <span className="text-xs px-1.5 py-0.5 bg-orange-100 dark:bg-orange-900/50 text-orange-700 dark:text-orange-300 rounded">
                          {c.category}
                        </span>
                        <span className={`text-xs px-1.5 py-0.5 rounded ${riskCls(c.risk_level)}`}>
                          {c.risk_level}风险
                        </span>
                        {chk && selfBadge(chk.status)}
                      </div>
                      <div className="text-sm text-gray-900 dark:text-gray-100 break-words">{c.clause_text}</div>
                      {c.tip && (
                        <div className="text-xs text-orange-700 dark:text-orange-300 mt-1">
                          💡 {c.tip}
                        </div>
                      )}
                      {chk?.reason && (
                        <div className="text-xs text-gray-600 dark:text-gray-400 mt-1">
                          自查判定: {chk.reason}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {result.docId != null && (
          <ReviewBox docId={result.docId} type="rejection" accent="orange" snapshot={{ summary, verdict }} />
        )}
      </div>
    </div>
  );
}

// ================== 投标响应性检查结果 ==================

function ResponsePanel({ result, onClose }: { result: ResponseResult; onClose?: () => void }) {
  const { summary, clauses, verdict, note } = result;

  const verdictMap: Record<string, { text: string; cls: string }> = {
    pass: { text: "✅ 全部响应", cls: "bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200" },
    attention: { text: "⚠️ 部分未响应", cls: "bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200" },
    danger: { text: "❌ 存在负偏离", cls: "bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-200" },
    unknown: { text: "响应性检查", cls: "bg-teal-100 dark:bg-teal-900 text-teal-800 dark:text-teal-200" },
  };

  const statusBadge = (s: string) => {
    const map: Record<string, { t: string; c: string }> = {
      response: { t: "响应", c: "bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200" },
      positive: { t: "正偏离", c: "bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-200" },
      negative: { t: "负偏离", c: "bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-200" },
      none: { t: "未响应", c: "bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-300" },
    };
    const m = map[s] || { t: s, c: "bg-gray-200 text-gray-700" };
    return <span className={`text-xs px-2 py-0.5 rounded font-medium ${m.c}`}>{m.t}</span>;
  };

  const cardCls = (s: string) =>
    s === "negative" ? "border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-950/20" :
    s === "none" ? "border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/40" :
    s === "positive" ? "border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-950/20" :
    "border-gray-200 dark:border-gray-800";

  return (
    <div className="mt-4 border border-gray-200 dark:border-gray-800 rounded-xl overflow-hidden">
      <div className="bg-teal-50 dark:bg-teal-950/30 border-b border-teal-200 dark:border-teal-800 p-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <FileCheck className="text-teal-600" size={18} />
          <span className="text-sm font-medium text-teal-900 dark:text-teal-100">投标响应性检查</span>
          <span className={`text-xs px-2 py-0.5 rounded font-medium ${verdictMap[verdict]?.cls || verdictMap.unknown.cls}`}>
            {verdictMap[verdict]?.text || "响应性检查"}
          </span>
        </div>
        {onClose && (
          <button onClick={onClose} className="text-teal-500 hover:text-teal-700 text-xs">关闭</button>
        )}
      </div>

      <div className="p-5">
        <div className="flex flex-wrap gap-4 mb-4">
          <div className="text-center">
            <div className="text-2xl font-bold text-gray-900 dark:text-gray-100">{summary.total}</div>
            <div className="text-xs text-gray-500">实质性条款</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-green-600">{summary.response}</div>
            <div className="text-xs text-gray-500">响应</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-blue-600">{summary.positive}</div>
            <div className="text-xs text-gray-500">正偏离</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-red-600">{summary.negative}</div>
            <div className="text-xs text-gray-500">负偏离</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-gray-500">{summary.none}</div>
            <div className="text-xs text-gray-500">未响应</div>
          </div>
        </div>

        {note && (
          <div className="mb-3 text-xs text-yellow-700 dark:text-yellow-300 bg-yellow-50 dark:bg-yellow-950/40 rounded p-2">{note}</div>
        )}

        {clauses.length === 0 ? (
          <div className="text-sm text-gray-500 bg-gray-50 dark:bg-gray-900 rounded p-3">未提取到实质性条款</div>
        ) : (
          <div className="space-y-2">
            {clauses.map((c) => (
              <div key={c.id} className={`border rounded-lg p-3 ${cardCls(c.status)}`}>
                <div className="flex items-center gap-2 flex-wrap mb-1">
                  <span className="text-xs font-mono text-gray-400">{c.id}</span>
                  {c.clause_no && <span className="text-xs px-1.5 py-0.5 bg-teal-100 dark:bg-teal-900/50 text-teal-700 dark:text-teal-300 rounded">{c.clause_no}</span>}
                  <span className="text-xs px-1.5 py-0.5 bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 rounded">{c.category}</span>
                  {statusBadge(c.status)}
                </div>
                <div className="text-sm text-gray-900 dark:text-gray-100 break-words">{c.tender_clause}</div>
                {c.requirement && c.requirement !== c.tender_clause && (
                  <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">要求: {c.requirement}</div>
                )}
                {c.evidence && (
                  <div className="mt-1 pl-3 border-l-2 border-teal-400 text-xs text-gray-700 dark:text-gray-300 italic">
                    投标原文: "{c.evidence}"
                  </div>
                )}
                {c.detail && (
                  <div className="text-xs text-teal-700 dark:text-teal-300 mt-1">📝 {c.detail}</div>
                )}
              </div>
            ))}
          </div>
        )}

        {result.docId != null && (
          <ReviewBox docId={result.docId} type="response" accent="purple" snapshot={{ summary, verdict }} />
        )}
      </div>
    </div>
  );
}

// ================== 评分辅助表 ==================

function ScoringPanel({ result, onClose }: { result: ScoringResult; onClose?: () => void }) {
  const { items, total_score, note } = result;
  const [bidderCount, setBidderCount] = useState(2);
  const [scores, setScores] = useState<Record<string, number[]>>({});

  // 初始化每行的得分数组
  useEffect(() => {
    const init: Record<string, number[]> = {};
    items.forEach((it) => { init[it.id] = new Array(bidderCount).fill(0); });
    setScores(init);
  }, [items, bidderCount]);

  const setScore = (itemId: string, idx: number, val: number) => {
    setScores((prev) => {
      const arr = [...(prev[itemId] || new Array(bidderCount).fill(0))];
      arr[idx] = val;
      return { ...prev, [itemId]: arr };
    });
  };

  const totals = Array.from({ length: bidderCount }, (_, idx) =>
    items.reduce((sum, it) => sum + (scores[it.id]?.[idx] || 0), 0)
  );

  return (
    <div className="mt-4 border border-gray-200 dark:border-gray-800 rounded-xl overflow-hidden">
      <div className="bg-amber-50 dark:bg-amber-950/30 border-b border-amber-200 dark:border-amber-800 p-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ClipboardCheck className="text-amber-600" size={18} />
          <span className="text-sm font-medium text-amber-900 dark:text-amber-100">评分辅助表</span>
          <span className="text-xs px-2 py-0.5 rounded font-medium bg-amber-100 dark:bg-amber-900 text-amber-800 dark:text-amber-200">
            满分 {total_score} 分
          </span>
        </div>
        {onClose && (
          <button onClick={onClose} className="text-amber-500 hover:text-amber-700 text-xs">关闭</button>
        )}
      </div>

      <div className="p-5">
        {note && (
          <div className="mb-3 text-xs text-yellow-700 dark:text-yellow-300 bg-yellow-50 dark:bg-yellow-950/40 rounded p-2">{note}</div>
        )}

        <div className="flex items-center gap-3 mb-3">
          <label className="text-xs text-gray-500">投标人家数:</label>
          <select value={bidderCount} onChange={(e) => setBidderCount(Number(e.target.value))}
                  className="text-xs border border-gray-300 dark:border-gray-700 rounded px-2 py-1 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100">
            {[1,2,3,4,5,6].map((n) => <option key={n} value={n}>{n} 家</option>)}
          </select>
          <span className="text-xs text-gray-400">在下方表格中填入各投标人每项得分</span>
        </div>

        {items.length === 0 ? (
          <div className="text-sm text-gray-500 bg-gray-50 dark:bg-gray-900 rounded p-3">未解析到评分项</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="bg-amber-50 dark:bg-amber-950/30">
                  <th className="border border-gray-200 dark:border-gray-700 p-2 text-left text-amber-900 dark:text-amber-100">评分项</th>
                  <th className="border border-gray-200 dark:border-gray-700 p-2 text-center text-amber-900 dark:text-amber-100">权重</th>
                  <th className="border border-gray-200 dark:border-gray-700 p-2 text-left text-amber-900 dark:text-amber-100">评分标准</th>
                  {Array.from({ length: bidderCount }, (_, i) => (
                    <th key={i} className="border border-gray-200 dark:border-gray-700 p-2 text-center text-amber-900 dark:text-amber-100">投标人{i + 1}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {items.map((it) => (
                  <tr key={it.id}>
                    <td className="border border-gray-200 dark:border-gray-700 p-2 text-gray-900 dark:text-gray-100">{it.dimension}</td>
                    <td className="border border-gray-200 dark:border-gray-700 p-2 text-center text-gray-700 dark:text-gray-300">{it.weight}</td>
                    <td className="border border-gray-200 dark:border-gray-700 p-2 text-xs text-gray-600 dark:text-gray-400">{it.scoring_rule || "—"}</td>
                    {Array.from({ length: bidderCount }, (_, idx) => (
                      <td key={idx} className="border border-gray-200 dark:border-gray-700 p-1">
                        <input
                          type="number"
                          min={0}
                          max={it.max_score}
                          value={scores[it.id]?.[idx] ?? 0}
                          onChange={(e) => setScore(it.id, idx, Number(e.target.value))}
                          className="w-full text-center text-sm bg-transparent focus:outline-none focus:bg-amber-50 dark:focus:bg-amber-950/40 rounded p-1 text-gray-900 dark:text-gray-100"
                        />
                      </td>
                    ))}
                  </tr>
                ))}
                <tr className="bg-amber-100 dark:bg-amber-950/40 font-bold">
                  <td colSpan={3} className="border border-gray-200 dark:border-gray-700 p-2 text-right text-amber-900 dark:text-amber-100">加权总分</td>
                  {totals.map((t, i) => (
                    <td key={i} className="border border-gray-200 dark:border-gray-700 p-2 text-center text-amber-900 dark:text-amber-100">{t.toFixed(2)}</td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        )}

        {result.docId != null && (
          <ReviewBox docId={result.docId} type="scoring" accent="purple" snapshot={{ total_score, item_count: items.length }} />
        )}
      </div>
    </div>
  );
}

// ================== 多家投标对比 ==================

function ComparePanel({ result, onClose }: { result: CompareResult; onClose?: () => void }) {
  const { fields, bidders, note } = result;

  return (
    <div className="mt-4 border border-gray-200 dark:border-gray-800 rounded-xl overflow-hidden">
      <div className="bg-indigo-50 dark:bg-indigo-950/30 border-b border-indigo-200 dark:border-indigo-800 p-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ClipboardCheck className="text-indigo-600" size={18} />
          <span className="text-sm font-medium text-indigo-900 dark:text-indigo-100">多家投标对比</span>
          <span className="text-xs px-2 py-0.5 rounded font-medium bg-indigo-100 dark:bg-indigo-900 text-indigo-800 dark:text-indigo-200">
            {bidders.length} 家
          </span>
        </div>
        {onClose && (
          <button onClick={onClose} className="text-indigo-500 hover:text-indigo-700 text-xs">关闭</button>
        )}
      </div>

      <div className="p-5">
        {note && (
          <div className="mb-3 text-xs text-yellow-700 dark:text-yellow-300 bg-yellow-50 dark:bg-yellow-950/40 rounded p-2">{note}</div>
        )}

        {fields.length === 0 ? (
          <div className="text-sm text-gray-500 bg-gray-50 dark:bg-gray-900 rounded p-3">无可对比字段</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="bg-indigo-50 dark:bg-indigo-950/30">
                  <th className="border border-gray-200 dark:border-gray-700 p-2 text-left text-indigo-900 dark:text-indigo-100">对比项</th>
                  {bidders.map((b, i) => (
                    <th key={i} className="border border-gray-200 dark:border-gray-700 p-2 text-center text-indigo-900 dark:text-indigo-100">{b.name}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {fields.map((f) => (
                  <tr key={f}>
                    <td className="border border-gray-200 dark:border-gray-700 p-2 text-gray-900 dark:text-gray-100 font-medium">{f}</td>
                    {bidders.map((b, i) => (
                      <td key={i} className="border border-gray-200 dark:border-gray-700 p-2 text-center text-gray-700 dark:text-gray-300 break-words max-w-[200px]">
                        {b.values[f] || "—"}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

// ================== 主页面 ==================

export default function DocumentsPage() {
  const [docs, setDocs] = useState<ListDoc[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [parsed, setParsed] = useState<ParsedDoc | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [detail, setDetail] = useState<ListDoc | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // 解析结果对应的检查状态
  const [compLoading, setCompLoading] = useState(false);
  const [compResult, setCompResult] = useState<ComplianceResult | null>(null);
  const [qualLoading, setQualLoading] = useState(false);
  const [qualResult, setQualResult] = useState<QualificationResult | null>(null);

  // 检测结果主动预警弹窗 (R17)
  const [alert, setAlert] = useState<AlertPayload | null>(null);
  const clip = (s: string | undefined, n = 90) =>
    s ? (s.length > n ? s.slice(0, n) + "…" : s) : "";

  // 弹窗（企业资质输入）
  const [qualInputOpen, setQualInputOpen] = useState(false);
  const [qualInput, setQualInput] = useState("");
  const qualTargetId = useRef<number | null>(null);

  // 废标条款检查
  const [rejLoading, setRejLoading] = useState(false);
  const [rejResult, setRejResult] = useState<RejectionResult | null>(null);
  const [rejInputOpen, setRejInputOpen] = useState(false);
  const [rejInput, setRejInput] = useState("");
  const rejTargetId = useRef<number | null>(null);

  // 投标响应性检查
  const [respLoading, setRespLoading] = useState(false);
  const [respResult, setRespResult] = useState<ResponseResult | null>(null);
  const [respInputOpen, setRespInputOpen] = useState(false);
  const [respBidText, setRespBidText] = useState("");
  const [respClause, setRespClause] = useState("");
  const respTargetId = useRef<number | null>(null);

  // 评分辅助表
  const [scoringLoading, setScoringLoading] = useState(false);
  const [scoringResult, setScoringResult] = useState<ScoringResult | null>(null);

  // 多家投标对比
  const [cmpLoading, setCmpLoading] = useState(false);
  const [cmpResult, setCmpResult] = useState<CompareResult | null>(null);
  const [cmpOpen, setCmpOpen] = useState(false);
  const [cmpBids, setCmpBids] = useState<{ name: string; text: string }[]>([
    { name: "投标人A", text: "" }, { name: "投标人B", text: "" }, { name: "投标人C", text: "" },
  ]);

  // 鉴权
  const [authOpen, setAuthOpen] = useState(false);
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [authUser, setAuthUser] = useState<{ id: number; username: string; role: string; display_name: string } | null>(null);
  const [authToken, setAuthToken] = useState<string>(() => {
    if (typeof window === "undefined") return "";
    return localStorage.getItem("qa_auth_token") || "";
  });

  // 上传元数据 (包件号/投标人/可见性)
  const [upPackage, setUpPackage] = useState("");
  const [upBidder, setUpBidder] = useState("");
  const [upInternal, setUpInternal] = useState(false);

  // ⑥ 评审阶段状态机
  const [stageInfo, setStageInfo] = useState<any>(null);
  const [stageLoading, setStageLoading] = useState(false);
  const [stageComment, setStageComment] = useState("");

  // 工作流
  const [wfOpen, setWfOpen] = useState(false);
  const [wfPresets, setWfPresets] = useState<{ id: string; name: string; description: string }[]>([]);
  const [wfConfig, setWfConfig] = useState("compliance_review");
  const [wfDbId, setWfDbId] = useState<number | null>(null);
  const [wfBidText, setWfBidText] = useState("");
  const [wfLoading, setWfLoading] = useState(false);
  const [wfResult, setWfResult] = useState<any>(null);

  // 报价计算
  const [priceOpen, setPriceOpen] = useState(false);
  const [priceLoading, setPriceLoading] = useState(false);
  const [priceResult, setPriceResult] = useState<any>(null);
  const [priceItemsText, setPriceItemsText] = useState(
    "服务器,10,50000,500000\n交换机,5,8000,40000\n实施服务,1,200000,200000");
  const [priceTotal, setPriceTotal] = useState("740000");
  const [priceCn, setPriceCn] = useState("柒拾肆万元整");
  const [priceControl, setPriceControl] = useState("1000000");
  const [priceOthers, setPriceOthers] = useState("740000,800000");

  // 投标文件解析
  const [bpOpen, setBpOpen] = useState(false);
  const [bpLoading, setBpLoading] = useState(false);
  const [bpResult, setBpResult] = useState<any>(null);
  const [bpName, setBpName] = useState("");
  const [bpText, setBpText] = useState("");

  // 围串标线索
  const [colOpen, setColOpen] = useState(false);
  const [colLoading, setColLoading] = useState(false);
  const [colResult, setColResult] = useState<any>(null);
  const colInputRef = useRef<HTMLInputElement>(null);

  // 标书一键生成 (单章流式)
  const BID_SECTIONS: { key: string; label: string }[] = [
    { key: "technical", label: "技术方案" },
    { key: "commercial", label: "商务方案" },
    { key: "qualification", label: "资格响应" },
    { key: "project_management", label: "项目管理" },
    { key: "after_sales", label: "售后服务" },
  ];
  const [bidOpen, setBidOpen] = useState(false);
  const [bidDbId, setBidDbId] = useState<number | null>(null);
  const [bidFileName, setBidFileName] = useState("");
  const [bidSection, setBidSection] = useState("technical");
  const [bidStreaming, setBidStreaming] = useState(false);
  const [bidTitle, setBidTitle] = useState("");
  const [bidMarkdown, setBidMarkdown] = useState("");
  const [bidCases, setBidCases] = useState(0);
  const [bidErr, setBidErr] = useState("");
  const [bidCopied, setBidCopied] = useState(false);
  const [bidExporting, setBidExporting] = useState(false);
  // 整本合稿 + 响应对照
  const [bidTab, setBidTab] = useState<"section" | "full">("section");
  const [fullBusy, setFullBusy] = useState(false);
  const [fullProgress, setFullProgress] = useState<{ key: string; title: string; status: "run" | "done" }[]>([]);
  const [fullMd, setFullMd] = useState("");
  const [fullMatrix, setFullMatrix] = useState<any[]>([]);
  const [fullHard, setFullHard] = useState<any[]>([]);
  const [fullVerdict, setFullVerdict] = useState("");
  const [fullFill, setFullFill] = useState<{ filled: string[]; missing_company: string[]; pending_business: string[] } | null>(null);
  const [fullExporting, setFullExporting] = useState(false);
  const [fullCopied, setFullCopied] = useState(false);

  useEffect(() => {
    if (authToken) localStorage.setItem("qa_auth_token", authToken);
    else localStorage.removeItem("qa_auth_token");
  }, [authToken]);
  useEffect(() => {
    if (authUser) localStorage.setItem("qa_auth_user", JSON.stringify(authUser));
    else localStorage.removeItem("qa_auth_user");
  }, [authUser]);
  useEffect(() => {
    if (!authUser && typeof window !== "undefined") {
      const raw = localStorage.getItem("qa_auth_user");
      if (raw) { try { setAuthUser(JSON.parse(raw)); } catch {} }
    }
  }, []);

  const loadDocs = async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/api/documents`);
      const j = await r.json();
      setDocs(j.items || []);
    } catch (e: any) {
      setError(e?.message || "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadDocs(); }, []);

  const isInternalRole = ["admin", "auditor", "purchaser"].includes(authUser?.role || "");

  const loadStage = async (docId: number) => {
    setStageInfo(null);
    setStageComment("");
    if (!isInternalRole || !authToken) return;
    try {
      const r = await fetch(`${API}/api/review-stage/${docId}`, {
        headers: { Authorization: `Bearer ${authToken}` },
      });
      if (r.ok) setStageInfo(await r.json());
    } catch { /* 静默: 无权限或服务不可用 */ }
  };

  const transitionStage = async (docId: number, action: string) => {
    setStageLoading(true);
    try {
      const r = await fetch(`${API}/api/review-stage/transition`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${authToken}` },
        body: JSON.stringify({ document_id: docId, action, comment: stageComment }),
      });
      if (!r.ok) {
        const e = await r.json().catch(() => ({}));
        setError(e.detail || `流转失败 HTTP ${r.status}`);
      } else {
        setStageComment("");
        await loadStage(docId);
      }
    } catch (e: any) {
      setError(e?.message || "流转失败");
    } finally {
      setStageLoading(false);
    }
  };

  // 各阶段可用动作
  const STAGE_ACTIONS: Record<string, [string, string][]> = {
    none: [["start", "提交评审"]],
    initial: [["challenge", "提出质疑"], ["close_initial", "初评结案"]],
    challenge: [["start_recheck", "受理质疑→复审"], ["reject_challenge", "驳回质疑结案"]],
    recheck: [["close", "复审结案"]],
    closed: [],
  };

  const handleFile = async (file: File) => {
    setError(null);
    setParsed(null);
    setCompResult(null);
    setQualResult(null);
    setRejResult(null);
    setRespResult(null);
    setScoringResult(null);
    setCmpResult(null);
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("save_to_db", "true");
      if (upPackage.trim()) fd.append("package", upPackage.trim());
      if (upBidder.trim()) fd.append("bidder_name", upBidder.trim());
      // 投标人的文件按规则强制 internal; 招标人/专家可勾选 internal
      fd.append("visibility",
        authUser?.role === "bidder" || upInternal ? "internal" : "auto");
      const r = await fetch(`${API}/api/document/upload`, {
        method: "POST",
        body: fd,
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : undefined,
      });
      if (!r.ok) {
        const msg = await r.text();
        throw new Error(msg || `HTTP ${r.status}`);
      }
      const j: ParsedDoc = await r.json();
      setParsed(j);
      await loadDocs();
    } catch (e: any) {
      setError(e?.message || "解析失败");
    } finally {
      setUploading(false);
    }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files[0];
    if (f) handleFile(f);
  };

  const runComplianceCheck = async (dbId: number) => {
    setCompLoading(true);
    setCompResult(null);
    try {
      const r = await fetch(`${API}/api/compliance/check`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ db_id: dbId }),
      });
      if (!r.ok) throw new Error(await r.text());
      const j: ComplianceResult = await r.json();
      setCompResult({ ...j, docId: dbId });
      // 主动预警 (R17): 高风险弹红, 中风险弹黄
      const hi = (j.risks || []).filter((x) => x.risk_level === "高");
      const mid = (j.risks || []).filter((x) => x.risk_level === "中");
      if (hi.length > 0) {
        setAlert({
          level: "high", title: "合规检测发现高风险排他性条款", docId: dbId,
          items: hi.map((x) => `【${x.rule_id}·${x.category}】${clip(x.detail || x.matched_text)}`),
        });
      } else if (mid.length > 0) {
        setAlert({
          level: "medium", title: "合规检测发现中风险条款", docId: dbId,
          items: mid.map((x) => `【${x.rule_id}·${x.category}】${clip(x.detail || x.matched_text)}`),
        });
      }
    } catch (e: any) {
      setCompResult({
        summary: { high: 0, medium: 0, low: 0, total_checked: 0, risks_found: 0 },
        risks: [], clean_rules: [], status: "warn",
        note: `检查失败: ${e?.message || "未知错误"}`,
        docId: dbId,
      });
    } finally {
      setCompLoading(false);
    }
  };

  const runQualificationCheck = async (dbId: number, certs: string[]) => {
    setQualLoading(true);
    setQualResult(null);
    try {
      const r = await fetch(`${API}/api/qualification/check`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ db_id: dbId, company_qualifications: certs }),
      });
      if (!r.ok) throw new Error(await r.text());
      const j: QualificationResult = await r.json();
      setQualResult({ ...j, docId: dbId });
      // 主动预警 (R17): 有资格项不满足弹红, 部分满足弹黄
      const miss = (j.checks || []).filter((c) => c.status === "NO_MATCH" || c.status === "INFO_MISSING");
      const part = (j.checks || []).filter((c) => c.status === "PARTIAL_MATCH");
      if (miss.length > 0) {
        setAlert({
          level: "high", title: "资格检查存在不满足项，可能被否决", docId: dbId,
          items: miss.map((c) => `${clip(c.requirement)}${c.detail ? ` — ${clip(c.detail, 40)}` : ""}`),
        });
      } else if (part.length > 0) {
        setAlert({
          level: "medium", title: "资格检查存在部分满足项", docId: dbId,
          items: part.map((c) => `${clip(c.requirement)}${c.detail ? ` — ${clip(c.detail, 40)}` : ""}`),
        });
      }
    } catch (e: any) {
      setQualResult({
        summary: { total_req: 0, full: 0, partial: 0, missing: 0 },
        checks: [],
        gap_report: "",
        verdict: "unknown",
        docId: dbId,
      });
      setError(`资格检查失败: ${e?.message}`);
    } finally {
      setQualLoading(false);
    }
  };

  const openQualInput = (dbId: number) => {
    qualTargetId.current = dbId;
    setQualInput("");
    setQualInputOpen(true);
  };

  const runRejectionCheck = async (dbId: number, bidderStatus?: string) => {
    setRejLoading(true);
    setRejResult(null);
    try {
      const r = await fetch(`${API}/api/rejection/check`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ db_id: dbId, bidder_status: bidderStatus || "" }),
      });
      if (!r.ok) throw new Error(await r.text());
      const j: RejectionResult = await r.json();
      setRejResult({ ...j, docId: dbId });
      // 主动预警 (R17): 废标风险弹红, 待确认弹黄
      const self = j.self_check || [];
      const risks = self.filter((s) => s.status === "risk");
      const uncertains = self.filter((s) => s.status === "uncertain");
      const clauseText = (id: string) => clip((j.clauses || []).find((c) => c.id === id)?.clause_text);
      if (j.verdict === "danger" || risks.length > 0) {
        setAlert({
          level: "high", title: "废标自查存在风险条款", docId: dbId,
          items: risks.map((s) => `【${s.clause_id}】${clauseText(s.clause_id)}${s.reason ? ` — ${clip(s.reason, 50)}` : ""}`),
        });
      } else if (j.verdict === "attention" || uncertains.length > 0) {
        setAlert({
          level: "medium", title: "废标自查存在待确认条款", docId: dbId,
          items: uncertains.map((s) => `【${s.clause_id}】${clauseText(s.clause_id)}${s.reason ? ` — ${clip(s.reason, 50)}` : ""}`),
        });
      }
    } catch (e: any) {
      setRejResult({
        summary: { total_clauses: 0, by_category: {}, risk_count: 0 },
        clauses: [], self_check: null, verdict: "unknown",
        note: `检查失败: ${e?.message || "未知错误"}`,
        docId: dbId,
      });
      setError(`废标检查失败: ${e?.message}`);
    } finally {
      setRejLoading(false);
    }
  };

  const openRejInput = (dbId: number) => {
    rejTargetId.current = dbId;
    setRejInput("");
    setRejInputOpen(true);
  };

  const runResponseCheck = async (dbId: number, bidText: string, clause: string) => {
    setRespLoading(true);
    setRespResult(null);
    try {
      const r = await fetch(`${API}/api/response/check`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tender_db_id: dbId, bid_text: bidText, clause }),
      });
      if (!r.ok) throw new Error(await r.text());
      const j: ResponseResult = await r.json();
      setRespResult({ ...j, docId: dbId });
      // 主动预警 (R17): 负偏离弹红, 未响应弹黄
      const neg = (j.clauses || []).filter((c) => c.status === "negative");
      const none = (j.clauses || []).filter((c) => c.status === "none");
      if (j.verdict === "danger" || neg.length > 0) {
        setAlert({
          level: "high", title: "响应性检查存在负偏离项", docId: dbId,
          items: neg.map((c) => `【${c.clause_no || c.id}】${clip(c.tender_clause)}${c.detail ? ` — ${clip(c.detail, 40)}` : ""}`),
        });
      } else if (j.verdict === "attention" || none.length > 0) {
        setAlert({
          level: "medium", title: "响应性检查存在未响应项", docId: dbId,
          items: none.map((c) => `【${c.clause_no || c.id}】${clip(c.tender_clause)}`),
        });
      }
    } catch (e: any) {
      setRespResult({
        summary: { total: 0, response: 0, positive: 0, negative: 0, none: 0 },
        clauses: [], verdict: "unknown",
        note: `检查失败: ${e?.message || "未知错误"}`,
        docId: dbId,
      });
      setError(`响应性检查失败: ${e?.message}`);
    } finally {
      setRespLoading(false);
    }
  };

  const openRespInput = (dbId: number) => {
    respTargetId.current = dbId;
    setRespBidText("");
    setRespClause("");
    setRespInputOpen(true);
  };

  const runScoring = async (dbId: number) => {
    setScoringLoading(true);
    setScoringResult(null);
    try {
      const r = await fetch(`${API}/api/scoring/table`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ db_id: dbId }),
      });
      if (!r.ok) throw new Error(await r.text());
      setScoringResult({ ...(await r.json()), docId: dbId });
    } catch (e: any) {
      setError(`评分辅助表生成失败: ${e?.message}`);
    } finally {
      setScoringLoading(false);
    }
  };

  const runCompare = async () => {
    const valid = cmpBids.filter((b) => b.text.trim() && b.name.trim());
    if (valid.length < 2) {
      setError("请至少填写 2 家投标人的名称和内容");
      return;
    }
    setCmpLoading(true);
    setCmpResult(null);
    try {
      const r = await fetch(`${API}/api/bids/compare`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bids: valid.map((b) => ({ bidder_name: b.name, text: b.text })) }),
      });
      if (!r.ok) throw new Error(await r.text());
      setCmpResult(await r.json());
      setCmpOpen(false);
    } catch (e: any) {
      setError(`投标对比失败: ${e?.message}`);
    } finally {
      setCmpLoading(false);
    }
  };

  const runPriceCalc = async () => {
    const items = priceItemsText.split("\n").map((l) => l.trim()).filter(Boolean).map((line) => {
      const [name, qty, unit_price, amount] = line.split(",").map((x) => x.trim());
      return { name, qty: qty || "", unit_price: unit_price || "", amount: amount || "" };
    });
    if (!items.length) { setError("请填写分项报价"); return; }
    setPriceLoading(true);
    setPriceResult(null);
    try {
      const r = await fetch(`${API}/api/price/calculate`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          items,
          declared_total: priceTotal || null,
          declared_total_cn: priceCn || null,
          control_price: priceControl || null,
          all_bid_prices: priceOthers ? priceOthers.split(",").map((x) => Number(x.trim())).filter((x) => !isNaN(x)) : null,
        }),
      });
      if (!r.ok) throw new Error(await r.text());
      const j = await r.json();
      setPriceResult(j);
      setPriceOpen(false);
      // 主动预警 (R17): 报价校验错误弹红, 警告弹黄
      const errs = (j.anomalies || []).filter((a: any) => a.level === "error");
      const warns = (j.anomalies || []).filter((a: any) => a.level !== "error");
      if (errs.length > 0) {
        setAlert({
          level: "high", title: "报价校验存在错误，可能导致废标", targetId: "price-result",
          items: errs.map((a: any) => `【${a.code}】${clip(a.message)}`),
        });
      } else if (warns.length > 0) {
        setAlert({
          level: "medium", title: "报价校验存在警告", targetId: "price-result",
          items: warns.map((a: any) => `【${a.code}】${clip(a.message)}`),
        });
      }
    } catch (e: any) {
      setError(`报价计算失败: ${e?.message}`);
    } finally {
      setPriceLoading(false);
    }
  };

  const runBidParse = async () => {
    if (!bpText.trim()) { setError("请粘贴投标文件内容"); return; }
    setBpLoading(true);
    setBpResult(null);
    try {
      const r = await fetch(`${API}/api/bid/parse`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bidder_name: bpName, text: bpText }),
      });
      if (!r.ok) throw new Error(await r.text());
      setBpResult(await r.json());
      setBpOpen(false);
    } catch (e: any) {
      setError(`投标解析失败: ${e?.message}`);
    } finally {
      setBpLoading(false);
    }
  };

  const runCollusion = async () => {
    const files = colInputRef.current?.files;
    if (!files || files.length < 2) { setError("请至少选择 2 份投标文件"); return; }
    setColLoading(true);
    setColResult(null);
    try {
      const fd = new FormData();
      Array.from(files).forEach((f) => fd.append("files", f));
      const r = await fetch(`${API}/api/collusion/upload`, { method: "POST", body: fd });
      if (!r.ok) throw new Error(await r.text());
      setColResult(await r.json());
      setColOpen(false);
    } catch (e: any) {
      setError(`围串标检测失败: ${e?.message}`);
    } finally {
      setColLoading(false);
    }
  };

  // ── 标书一键生成 (单章流式) ─────────────────────────────
  const openBidWriter = (id: number, fileName: string) => {
    setBidDbId(id);
    setBidFileName(fileName);
    setBidSection("technical");
    setBidTitle("");
    setBidMarkdown("");
    setBidCases(0);
    setBidErr("");
    setBidCopied(false);
    setBidTab("section");
    setFullBusy(false);
    setFullProgress([]);
    setFullMd("");
    setFullMatrix([]);
    setFullHard([]);
    setFullVerdict("");
    setFullFill(null);
    setBidOpen(true);
  };

  const runBidSection = async () => {
    if (bidDbId == null || bidStreaming) return;
    setBidStreaming(true);
    setBidErr("");
    setBidMarkdown("");
    setBidTitle("");
    setBidCases(0);
    setBidCopied(false);
    try {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (authToken) headers.Authorization = `Bearer ${authToken}`;
      const resp = await fetch(`${API}/api/bid/section/stream`, {
        method: "POST",
        headers,
        body: JSON.stringify({ db_id: bidDbId, section: bidSection }),
      });
      if (!resp.ok || !resp.body) {
        const detail = await resp.json().catch(() => ({}));
        throw new Error(detail.detail || `生成失败 (${resp.status})`);
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          const t = line.trim();
          if (!t.startsWith("data: ")) continue;
          const ev = JSON.parse(t.slice(6));
          if (ev.type === "meta") { setBidTitle(ev.title || ""); setBidCases(ev.similar_cases_found || 0); }
          else if (ev.type === "token") setBidMarkdown((m) => m + (ev.content || ""));
          else if (ev.type === "error") throw new Error(ev.content || "章节生成失败");
        }
      }
    } catch (e: any) {
      setBidErr(e?.message || "章节生成失败");
    } finally {
      setBidStreaming(false);
    }
  };

  const exportBidDocx = async () => {
    if (!bidMarkdown.trim() || bidExporting) return;
    setBidExporting(true);
    try {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (authToken) headers.Authorization = `Bearer ${authToken}`;
      const r = await fetch(`${API}/api/export/docx`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          db_id: bidDbId,
          markdown: bidMarkdown,
          export_title: `${bidFileName || "投标书"}_${bidTitle || bidSection}`,
        }),
      });
      if (!r.ok) {
        const detail = await r.json().catch(() => ({}));
        throw new Error(detail.detail || `导出失败 (${r.status})`);
      }
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `投标书_${bidTitle || bidSection}.docx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      setBidErr(e?.message || "导出 Word 失败");
    } finally {
      setBidExporting(false);
    }
  };

  const copyBidMd = async () => {
    if (!bidMarkdown.trim()) return;
    try {
      await navigator.clipboard.writeText(bidMarkdown);
      setBidCopied(true);
      setTimeout(() => setBidCopied(false), 1500);
    } catch { /* 剪贴板不可用时静默 */ }
  };

  // ── 整本一键合稿 (5 章 SSE + 响应对照表) ─────────────────
  const runBidFull = async () => {
    if (bidDbId == null || fullBusy) return;
    if (!authToken) { setBidErr("整本合稿需要先登录（企业资料占位符自动回填）"); return; }
    setFullBusy(true);
    setBidErr("");
    setFullMd("");
    setFullMatrix([]);
    setFullHard([]);
    setFullVerdict("");
    setFullFill(null);
    setFullProgress([]);
    try {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      headers.Authorization = `Bearer ${authToken}`;
      const resp = await fetch(`${API}/api/bid/full/stream`, {
        method: "POST",
        headers,
        body: JSON.stringify({ db_id: bidDbId }),
      });
      if (!resp.ok || !resp.body) {
        const detail = await resp.json().catch(() => ({}));
        throw new Error(detail.detail || `生成失败 (${resp.status})`);
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          const t = line.trim();
          if (!t.startsWith("data: ")) continue;
          const ev = JSON.parse(t.slice(6));
          if (ev.type === "meta" && Array.isArray(ev.sections)) {
            setFullProgress(ev.sections.map((s: any) => ({ key: s.key, title: s.title, status: "run" })));
          } else if (ev.type === "section_start") {
            setFullProgress((ps) => ps.map((p) => p.key === ev.key ? { ...p, status: "run" } : p));
          } else if (ev.type === "section_done") {
            setFullProgress((ps) => ps.map((p) => p.key === ev.key ? { ...p, status: "done" } : p));
          } else if (ev.type === "matrix_done") {
            setFullMatrix(Array.isArray(ev.rows) ? ev.rows : []);
            setFullHard(Array.isArray(ev.hard_failures) ? ev.hard_failures : []);
            setFullVerdict(ev.verdict || "");
          } else if (ev.type === "done") {
            setFullMd(ev.markdown || "");
            setFullFill(ev.fill_info || null);
          } else if (ev.type === "error") {
            throw new Error(ev.content || "整本生成失败");
          }
        }
      }
    } catch (e: any) {
      setBidErr(e?.message || "整本生成失败");
    } finally {
      setFullBusy(false);
    }
  };

  const exportFullBid = async () => {
    if (!fullMd.trim() || fullExporting) return;
    setFullExporting(true);
    try {
      const r = await fetch(`${API}/api/export/docx`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${authToken}` },
        body: JSON.stringify({
          db_id: bidDbId,
          markdown: fullMd,
          export_title: `${bidFileName || "投标书"}_整本`,
        }),
      });
      if (!r.ok) {
        const detail = await r.json().catch(() => ({}));
        throw new Error(detail.detail || `导出失败 (${r.status})`);
      }
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `投标书_整本.docx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      setBidErr(e?.message || "导出 Word 失败");
    } finally {
      setFullExporting(false);
    }
  };

  const copyFullMd = async () => {
    if (!fullMd.trim()) return;
    try {
      await navigator.clipboard.writeText(fullMd);
      setFullCopied(true);
      setTimeout(() => setFullCopied(false), 1500);
    } catch { /* ignore */ }
  };

  const matrixRowClass = (status: string, material: boolean) => {
    if (status === "NOT_SATISFIED" || status === "NO_RESPONSE")
      return material ? "bg-red-50 dark:bg-red-950/40 font-medium" : "bg-red-50/60 dark:bg-red-950/20";
    if (status === "NEGATIVE_DEVIATION") return "bg-amber-50 dark:bg-amber-950/30";
    return "";
  };
  const statusBadge = (status: string) => {
    const map: Record<string, { t: string; c: string }> = {
      SATISFIED: { t: "🟢 满足", c: "text-green-700 dark:text-green-400" },
      POSITIVE_DEVIATION: { t: "🔵 正偏离", c: "text-blue-700 dark:text-blue-400" },
      NEGATIVE_DEVIATION: { t: "🟡 负偏离", c: "text-amber-700 dark:text-amber-400" },
      NOT_SATISFIED: { t: "🔴 不满足", c: "text-red-700 dark:text-red-400 font-semibold" },
      NO_RESPONSE: { t: "🔴 未响应", c: "text-red-700 dark:text-red-400 font-semibold" },
    };
    const s = map[status] || { t: status, c: "" };
    return <span className={s.c}>{s.t}</span>;
  };

  return (
    <div className="max-w-5xl mx-auto p-6 space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <FileText className="text-blue-600" /> 招标文件解析 & 审查
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            上传 PDF / Word / TXT / Markdown，自动抽取项目信息；支持合规性检查和资格条件审查。
          </p>
        </div>
        <div className="flex items-center gap-3 whitespace-nowrap mt-2">
          <Link href="/profile" className="text-blue-600 hover:underline text-sm inline-flex items-center gap-1">
            <Building2 size={13} /> 企业资料库
          </Link>
          <Link href="/" className="text-blue-600 hover:underline text-sm">← 返回问答</Link>
        </div>
      </div>

      <div className="flex justify-between items-center">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setCmpOpen(true)}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg transition"
          >
            <ClipboardCheck size={14} /> 多家投标对比
          </button>
          {authUser?.role !== "bidder" && (
          <button
            onClick={async () => {
              setWfResult(null);
              try {
                const r = await fetch(`${API}/api/workflow/presets`);
                const j = await r.json();
                setWfPresets(j.presets || []);
              } catch {}
              setWfOpen(true);
            }}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg transition"
          >
            <Shield size={14} /> 智能工作流
          </button>
          )}
          <button
            onClick={() => { setPriceResult(null); setPriceOpen(true); }}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-amber-600 hover:bg-amber-700 text-white rounded-lg transition"
          >
            <Calculator size={14} /> 报价计算
          </button>
          <button
            onClick={() => { setBpResult(null); setBpOpen(true); }}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-sky-600 hover:bg-sky-700 text-white rounded-lg transition"
          >
            <FileSearch size={14} /> 投标解析
          </button>
          {authUser?.role !== "bidder" && (
          <button
            onClick={() => { setColResult(null); setColOpen(true); }}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-rose-600 hover:bg-rose-700 text-white rounded-lg transition"
          >
            <Radar size={14} /> 围串标线索
          </button>
          )}
        </div>
        {authUser ? (
          <div className="flex items-center gap-2 text-sm">
            <span className="inline-flex items-center gap-1 text-gray-600 dark:text-gray-300">
              <User size={14} />
              {authUser.display_name || authUser.username}
              <span className="px-1.5 py-0.5 text-xs rounded bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 ml-1">
                {authUser.role === "admin" ? "管理员" : authUser.role === "auditor" ? "审计员" : authUser.role === "purchaser" ? "招标人" : "投标人"}
              </span>
            </span>
            <button
              onClick={() => { setAuthToken(""); setAuthUser(null); }}
              className="inline-flex items-center gap-1 px-3 py-1.5 text-xs text-red-600 hover:bg-red-50 dark:hover:bg-red-950/30 rounded-lg transition">
              <LogOut size={12} /> 退出
            </button>
          </div>
        ) : (
          <button
            onClick={() => { setAuthMode("login"); setAuthOpen(true); }}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-gray-700 hover:bg-gray-800 text-white rounded-lg transition">
            <User size={14} /> 登录
          </button>
        )}
      </div>

      {/* 上传元数据 (包件/投标人/可见性) */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2" onClick={(e) => e.stopPropagation()}>
        <input value={upPackage} onChange={(e) => setUpPackage(e.target.value)} placeholder="包件号/包件名 (可选)"
          className="rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-1.5 text-xs text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500" />
        <input value={upBidder} onChange={(e) => setUpBidder(e.target.value)} placeholder="投标人名称 (投标文件可选)"
          className="rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-1.5 text-xs text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500" />
        <label className={`flex items-center gap-2 text-xs px-3 py-1.5 rounded-lg border cursor-pointer ${upInternal || authUser?.role === "bidder"
          ? "border-amber-400 bg-amber-50 dark:bg-amber-950/30 text-amber-700 dark:text-amber-300"
          : "border-gray-300 dark:border-gray-700 text-gray-600 dark:text-gray-300"}`}>
          <input type="checkbox" checked={upInternal || authUser?.role === "bidder"}
            disabled={authUser?.role === "bidder"}
            onChange={(e) => setUpInternal(e.target.checked)} className="accent-amber-600" />
          评标内部文件 (投标人不可见)
        </label>
      </div>

      {/* 上传区 */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        onClick={() => fileRef.current?.click()}
        className={`cursor-pointer border-2 border-dashed rounded-xl p-8 text-center transition
          ${dragOver ? "border-blue-500 bg-blue-50 dark:bg-blue-950/40" : "border-gray-300 dark:border-gray-700 hover:border-gray-400"}`}
      >
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,.docx,.doc,.txt,.md,.xlsx,.xls"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) handleFile(f);
          }}
        />
        <Upload size={32} className="mx-auto text-gray-400 mb-2" />
        <p className="text-sm text-gray-600 dark:text-gray-300">
          {uploading ? "解析中..." : "点击或拖拽文件到此处上传"}
        </p>
        <p className="text-xs text-gray-400 mt-1">支持 .pdf / .docx / .doc / .txt / .md / .xlsx (扫描件 PDF 自动 OCR)</p>
      </div>

      {/* 上传中 */}
      {uploading && (
        <div className="bg-blue-50 dark:bg-blue-950/40 border border-blue-200 dark:border-blue-800 rounded-lg p-4 flex items-center gap-3">
          <Loader2 className="animate-spin text-blue-600" size={20} />
          <div>
            <div className="text-sm font-medium text-blue-900 dark:text-blue-100">正在解析文件...</div>
            <div className="text-xs text-blue-700 dark:text-blue-300">提取文本 → LLM 结构化抽取 → 存入数据库</div>
          </div>
        </div>
      )}

      {/* 错误 */}
      {error && !uploading && (
        <div className="bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 rounded-lg p-4 flex items-start gap-3">
          <AlertCircle className="text-red-600 flex-shrink-0 mt-0.5" size={20} />
          <div className="text-sm text-red-900 dark:text-red-100">{error}</div>
        </div>
      )}

      {/* 解析结果 */}
      {parsed && !uploading && (
        <div className="border border-gray-200 dark:border-gray-800 rounded-xl overflow-hidden">
          <div className="bg-green-50 dark:bg-green-950/30 border-b border-green-200 dark:border-green-800 p-3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <CheckCircle className="text-green-600" size={18} />
              <span className="text-sm font-medium text-green-900 dark:text-green-100">
                解析完成 · {parsed.source_file}
              </span>
              {parsed.parse_status !== "ok" && (
                <span className="text-xs px-2 py-0.5 bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200 rounded">
                  {parsed.parse_status}
                </span>
              )}
            </div>
            {parsed.db_id && <span className="text-xs text-gray-500">已入库 #{parsed.db_id}</span>}
          </div>
          <div className="p-5">
            <Field label="项目名称" value={parsed.project_name} />
            <Field label="项目编号" value={parsed.project_code} />
            <Field label="采购人" value={parsed.purchaser} />
            <Field label="代理机构" value={parsed.agency} />
            <Field label="采购内容" value={parsed.subject_matter} />
            <Field label="预算金额" value={parsed.budget} />
            <Field label="投标截止" value={parsed.deadline} />
            <Field label="开标时间" value={parsed.opening_time} />
            <Field label="开标地点" value={parsed.location} />
            <Field label="评分办法" value={parsed.scoring_criteria} />
            <Field label="文本长度" value={parsed.text_length ? `${parsed.text_length.toLocaleString()} 字符` : null} />

            {parsed.qualification_requirements && parsed.qualification_requirements.length > 0 && (
              <div className="mt-4">
                <div className="text-xs text-gray-500 dark:text-gray-400 mb-2">
                  资质要求 ({parsed.qualification_requirements.length})
                </div>
                <ul className="space-y-1">
                  {parsed.qualification_requirements.map((q, i) => (
                    <li key={i} className="text-sm text-gray-800 dark:text-gray-200 pl-4 relative before:content-['•'] before:absolute before:left-0 before:text-blue-500">
                      {q}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {parsed.raw_text_preview && (
              <details className="mt-4">
                <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-700">
                  查看原文预览 (前 2000 字)
                </summary>
                <pre className="mt-2 p-3 bg-gray-50 dark:bg-gray-900 text-xs text-gray-700 dark:text-gray-300 rounded-lg overflow-auto max-h-48 whitespace-pre-wrap font-mono">
                  {parsed.raw_text_preview}
                </pre>
              </details>
            )}

            {/* 审查按钮区 */}
            {parsed.db_id && (
              <div className="mt-5 pt-4 border-t border-gray-200 dark:border-gray-800 flex flex-wrap gap-3">
                <button
                  onClick={() => runComplianceCheck(parsed.db_id!)}
                  disabled={compLoading}
                  className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-purple-600 hover:bg-purple-700 disabled:opacity-50 text-white rounded-lg transition"
                >
                  {compLoading ? <Loader2 className="animate-spin" size={14} /> : <Shield size={14} />}
                  合规性检查
                </button>
                <button
                  onClick={() => openQualInput(parsed.db_id!)}
                  disabled={qualLoading}
                  className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-lg transition"
                >
                  {qualLoading ? <Loader2 className="animate-spin" size={14} /> : <ClipboardCheck size={14} />}
                  资格条件审查
                </button>
                <button
                  onClick={() => openRejInput(parsed.db_id!)}
                  disabled={rejLoading}
                  className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-orange-600 hover:bg-orange-700 disabled:opacity-50 text-white rounded-lg transition"
                >
                  {rejLoading ? <Loader2 className="animate-spin" size={14} /> : <FileWarning size={14} />}
                  废标条款检查
                </button>
                <button
                  onClick={() => openRespInput(parsed.db_id!)}
                  disabled={respLoading}
                  className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-teal-600 hover:bg-teal-700 disabled:opacity-50 text-white rounded-lg transition"
                >
                  {respLoading ? <Loader2 className="animate-spin" size={14} /> : <FileCheck size={14} />}
                  响应性检查
                </button>
                <button
                  onClick={() => runScoring(parsed.db_id!)}
                  disabled={scoringLoading}
                  className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-amber-600 hover:bg-amber-700 disabled:opacity-50 text-white rounded-lg transition"
                >
                  {scoringLoading ? <Loader2 className="animate-spin" size={14} /> : <ClipboardCheck size={14} />}
                  评分辅助表
                </button>
                <button
                  onClick={() => openBidWriter(parsed.db_id!, parsed.source_file || "")}
                  className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg transition"
                >
                  <PenLine size={14} />
                  一键生成标书
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* 检查结果区 (从列表触发时 parsed 可能为空, 故独立放置) */}
      {(compResult || qualResult || rejResult || respResult || scoringResult) && (
        <div className="space-y-0">
          {compResult && (
            <CompliancePanel result={compResult} onClose={() => setCompResult(null)} />
          )}
          {qualResult && (
            <QualificationPanel result={qualResult} onClose={() => setQualResult(null)} />
          )}
          {rejResult && (
            <RejectionPanel result={rejResult} onClose={() => setRejResult(null)} />
          )}
          {respResult && (
            <ResponsePanel result={respResult} onClose={() => setRespResult(null)} />
          )}
          {scoringResult && (
            <ScoringPanel result={scoringResult} onClose={() => setScoringResult(null)} />
          )}
        </div>
      )}

      {/* 多家投标对比结果 (独立) */}
      {cmpResult && (
        <ComparePanel result={cmpResult} onClose={() => setCmpResult(null)} />
      )}

      {/* 工作流结果 (独立) */}
      {wfResult && <WorkflowPanel result={wfResult} onClose={() => setWfResult(null)} />}

      {/* 报价计算结果 (独立) */}
      {priceResult && (
        <div id="price-result" className="scroll-mt-4">
          <PricePanel result={priceResult} onClose={() => setPriceResult(null)} />
        </div>
      )}

      {/* 投标解析结果 (独立) */}
      {bpResult && <BidParsePanel result={bpResult} onClose={() => setBpResult(null)} />}

      {/* 围串标线索结果 (独立) */}
      {colResult && <CollusionPanel result={colResult} onClose={() => setColResult(null)} />}

      {/* 已解析列表 */}
      <div>
        <h2 className="text-lg font-semibold mb-3">已解析文档 ({docs.length})</h2>
        {loading ? (
          <div className="text-sm text-gray-500">加载中...</div>
        ) : docs.length === 0 ? (
          <div className="text-sm text-gray-400 bg-gray-50 dark:bg-gray-900 rounded-lg p-8 text-center">
            暂无文档，上传一个试试
          </div>
        ) : (
          <div className="grid gap-3">
            {docs.map((d) => (
              <div key={d.id}
                   className="border border-gray-200 dark:border-gray-800 rounded-lg p-4 hover:border-gray-300 dark:hover:border-gray-700 transition">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-sm truncate">{d.source_file}</div>
                    {d.project_name && (
                      <div className="text-xs text-gray-600 dark:text-gray-400 mt-1 truncate">
                        {d.project_name}
                      </div>
                    )}
                    <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-xs text-gray-500">
                      {d.purchaser && <span>采购人: {d.purchaser}</span>}
                      {d.budget && <span>预算: {d.budget}</span>}
                    </div>
                  </div>
                  <div className="flex items-center gap-1 flex-shrink-0">
                    <button
                      onClick={() => runComplianceCheck(d.id)}
                      className="p-2 text-gray-400 hover:text-purple-600 hover:bg-purple-50 dark:hover:bg-purple-950 rounded-lg transition"
                      title="合规检查">
                      <Shield size={16} />
                    </button>
                    <button
                      onClick={() => openQualInput(d.id)}
                      className="p-2 text-gray-400 hover:text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-950 rounded-lg transition"
                      title="资格检查">
                      <ClipboardCheck size={16} />
                    </button>
                    <button
                      onClick={() => openRejInput(d.id)}
                      className="p-2 text-gray-400 hover:text-orange-600 hover:bg-orange-50 dark:hover:bg-orange-950 rounded-lg transition"
                      title="废标条款检查">
                      <FileWarning size={16} />
                    </button>
                    <button
                      onClick={() => openRespInput(d.id)}
                      className="p-2 text-gray-400 hover:text-teal-600 hover:bg-teal-50 dark:hover:bg-teal-950 rounded-lg transition"
                      title="响应性检查">
                      <FileCheck size={16} />
                    </button>
                    <button
                      onClick={() => runScoring(d.id)}
                      disabled={scoringLoading}
                      className="p-2 text-gray-400 hover:text-amber-600 hover:bg-amber-50 dark:hover:bg-amber-950 disabled:opacity-50 rounded-lg transition"
                      title="评分辅助表">
                      <ClipboardCheck size={16} />
                    </button>
                    <button
                      onClick={() => openBidWriter(d.id, d.source_file)}
                      className="p-2 text-gray-400 hover:text-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-950 rounded-lg transition"
                      title="一键生成标书章节">
                      <PenLine size={16} />
                    </button>
                    <button onClick={() => { setDetail(d); loadStage(d.id); }}
                            className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition"
                            title="查看详情">
                      <Eye size={16} />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 详情弹窗 */}
      {detail && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={() => setDetail(null)}>
          <div className="bg-white dark:bg-gray-900 rounded-xl max-w-2xl w-full max-h-[80vh] overflow-auto"
               onClick={(e) => e.stopPropagation()}>
            <div className="sticky top-0 bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 px-5 py-3 flex items-center justify-between">
              <div>
                <div className="font-medium text-sm truncate">{detail.source_file}</div>
                <div className="text-xs text-gray-500">#{detail.id}</div>
              </div>
              <button onClick={() => setDetail(null)} className="p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded">
                <X size={18} />
              </button>
            </div>
            <div className="p-5">
              {detail.project_name && <Field label="项目名称" value={detail.project_name} />}
              {detail.purchaser && <Field label="采购人" value={detail.purchaser} />}
              {detail.budget && <Field label="预算" value={detail.budget} />}
              <div className="mt-4 flex gap-3">
                <button
                  onClick={() => runComplianceCheck(detail.id)}
                  className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-purple-600 hover:bg-purple-700 text-white rounded-lg transition">
                  <Shield size={14} /> 合规检查
                </button>
                <button
                  onClick={() => openQualInput(detail.id)}
                  className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition">
                  <ClipboardCheck size={14} /> 资格检查
                </button>
                <button
                  onClick={() => openRejInput(detail.id)}
                  className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-orange-600 hover:bg-orange-700 text-white rounded-lg transition">
                  <FileWarning size={14} /> 废标检查
                </button>
                <button
                  onClick={() => openRespInput(detail.id)}
                  className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-teal-600 hover:bg-teal-700 text-white rounded-lg transition">
                  <FileCheck size={14} /> 响应检查
                </button>
                <button
                  onClick={() => runScoring(detail.id)}
                  disabled={scoringLoading}
                  className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-amber-600 hover:bg-amber-700 disabled:opacity-50 text-white rounded-lg transition">
                  {scoringLoading ? <Loader2 className="animate-spin" size={14} /> : <ClipboardCheck size={14} />} 评分辅助表
                </button>
                <button
                  onClick={() => { setDetail(null); openBidWriter(detail.id, detail.source_file); }}
                  className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg transition">
                  <PenLine size={14} /> 一键生成标书
                </button>
              </div>

              {/* ⑥ 评审阶段状态机 (仅内部角色) */}
              {isInternalRole && (
                <div className="mt-5 border-t border-gray-200 dark:border-gray-800 pt-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-medium text-gray-900 dark:text-gray-100">评审阶段</span>
                    {stageInfo && (
                      <span className={`text-xs px-2 py-0.5 rounded font-medium ${
                        stageInfo.stage === "closed"
                          ? "bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-200"
                          : "bg-blue-100 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300"}`}>
                        {stageInfo.stage_label}
                      </span>
                    )}
                  </div>
                  {!stageInfo ? (
                    <p className="text-xs text-gray-400">加载中…</p>
                  ) : (
                    <>
                      {stageInfo.stage !== "closed" && (
                        <div className="space-y-2 mb-3">
                          <input
                            value={stageComment}
                            onChange={(e) => setStageComment(e.target.value)}
                            placeholder="流转备注 (可选, 如质疑事项/复审结论)"
                            className="w-full rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-1.5 text-xs text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500" />
                          <div className="flex flex-wrap gap-2">
                            {(STAGE_ACTIONS[stageInfo.stage] || []).map(([act, label]) => (
                              <button key={act} onClick={() => transitionStage(detail.id, act)}
                                disabled={stageLoading}
                                className="px-3 py-1.5 text-xs bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white rounded-lg transition">
                                {stageLoading ? <Loader2 className="animate-spin inline" size={12} /> : label}
                              </button>
                            ))}
                          </div>
                        </div>
                      )}
                      {stageInfo.history.length > 0 && (
                        <div className="space-y-1.5">
                          {stageInfo.history.map((h: any) => (
                            <div key={h.id} className="text-xs text-gray-600 dark:text-gray-300 flex items-start gap-2">
                              <span className="shrink-0 px-1.5 py-0.5 bg-gray-100 dark:bg-gray-800 rounded text-[10px]">
                                {h.from_stage_label || "未开始"} → {h.to_stage_label}
                              </span>
                              <span className="flex-1">
                                <span className="text-gray-500">{h.action_label}</span>
                                {h.comment && <span className="text-gray-500"> · {h.comment}</span>}
                                <span className="text-gray-400 ml-1">— {h.operator}</span>
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 一键生成标书弹窗 (单章流式) */}
      {bidOpen && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={() => !(bidStreaming || fullBusy) && setBidOpen(false)}>
          <div className="bg-white dark:bg-gray-900 rounded-xl max-w-5xl w-full max-h-[88vh] flex flex-col"
               onClick={(e) => e.stopPropagation()}>
            <div className="border-b border-gray-200 dark:border-gray-800 px-5 py-3 flex items-center justify-between">
              <div className="min-w-0">
                <div className="font-medium text-sm flex items-center gap-2">
                  <PenLine size={15} className="text-emerald-600" /> 一键生成标书
                </div>
                <div className="text-xs text-gray-500 truncate">招标文件 #{bidDbId} · {bidFileName}</div>
              </div>
              <button onClick={() => !(bidStreaming || fullBusy) && setBidOpen(false)}
                      disabled={bidStreaming || fullBusy}
                      className="p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded disabled:opacity-40">
                <X size={18} />
              </button>
            </div>

            <div className="px-5 pt-3 flex items-center justify-between gap-3">
              <div className="inline-flex rounded-lg border border-gray-200 dark:border-gray-700 p-0.5">
                <button onClick={() => setBidTab("section")}
                        className={`px-3 py-1.5 text-xs rounded-md transition ${bidTab === "section" ? "bg-emerald-600 text-white" : "text-gray-600 dark:text-gray-300"}`}>
                  单章流式生成
                </button>
                <button onClick={() => setBidTab("full")}
                        className={`px-3 py-1.5 text-xs rounded-md transition inline-flex items-center gap-1 ${bidTab === "full" ? "bg-emerald-600 text-white" : "text-gray-600 dark:text-gray-300"}`}>
                  <BookOpen size={12} /> 整本合稿＋响应对照
                </button>
              </div>
              <Link href="/profile" target="_blank"
                    className="text-xs text-blue-600 hover:underline inline-flex items-center gap-1 whitespace-nowrap">
                <Building2 size={12} /> 企业资料库（自动回填）
              </Link>
            </div>

            {bidTab === "section" ? (
            <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-800">
              <div className="flex flex-wrap gap-2">
                {BID_SECTIONS.map((s) => (
                  <button key={s.key}
                    onClick={() => !bidStreaming && setBidSection(s.key)}
                    disabled={bidStreaming}
                    className={`px-3 py-1.5 text-xs rounded-lg border transition disabled:opacity-50 ${
                      bidSection === s.key
                        ? "bg-emerald-600 text-white border-emerald-600"
                        : "border-gray-300 dark:border-gray-700 text-gray-700 dark:text-gray-300 hover:border-emerald-500"}`}>
                    {s.label}
                  </button>
                ))}
              </div>
              <div className="mt-3 flex items-center gap-3">
                <button onClick={runBidSection} disabled={bidStreaming}
                  className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white rounded-lg transition">
                  {bidStreaming ? <Loader2 className="animate-spin" size={14} /> : <PenLine size={14} />}
                  {bidStreaming ? "正在生成…" : (bidMarkdown ? "重新生成本章" : "生成本章草稿")}
                </button>
                <button onClick={copyBidMd} disabled={!bidMarkdown || bidStreaming}
                  className="inline-flex items-center gap-1.5 px-3 py-2 text-sm border border-gray-300 dark:border-gray-700 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-40 transition">
                  {bidCopied ? <CheckCircle size={14} className="text-green-600" /> : <Copy size={14} />}
                  {bidCopied ? "已复制" : "复制"}
                </button>
                <button onClick={exportBidDocx} disabled={!bidMarkdown || bidExporting}
                  className="inline-flex items-center gap-1.5 px-3 py-2 text-sm border border-gray-300 dark:border-gray-700 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-40 transition">
                  {bidExporting ? <Loader2 className="animate-spin" size={14} /> : <Download size={14} />}
                  导出 Word
                </button>
                {bidCases > 0 && (
                  <span className="text-xs text-gray-400">已参考 {bidCases} 条同类案例</span>
                )}
              </div>
              <p className="text-[11px] text-gray-400 mt-2">
                登录后企业资料库中的公司全称/法人/资质编号等会自动回填；未配置或业务测算类占位符（黄色高亮）需人工补。
              </p>
            </div>
            ) : (
            <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-800">
              <div className="flex flex-wrap items-center gap-3">
                <button onClick={runBidFull} disabled={fullBusy}
                  className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-lg transition">
                  {fullBusy ? <Loader2 className="animate-spin" size={14} /> : <BookOpen size={14} />}
                  {fullBusy ? "正在整本生成…" : (fullMd ? "重新生成整本" : "一键生成整本标书（5章+对照表）")}
                </button>
                <button onClick={copyFullMd} disabled={!fullMd || fullBusy}
                  className="inline-flex items-center gap-1.5 px-3 py-2 text-sm border border-gray-300 dark:border-gray-700 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-40 transition">
                  {fullCopied ? <CheckCircle size={14} className="text-green-600" /> : <Copy size={14} />}
                  {fullCopied ? "已复制" : "复制"}
                </button>
                <button onClick={exportFullBid} disabled={!fullMd || fullExporting}
                  className="inline-flex items-center gap-1.5 px-3 py-2 text-sm border border-gray-300 dark:border-gray-700 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-40 transition">
                  {fullExporting ? <Loader2 className="animate-spin" size={14} /> : <Download size={14} />}
                  导出整本 Word
                </button>
                {fullVerdict === "fail" && <span className="text-xs text-red-600 font-medium">存在实质性不合格项，导出前须整改</span>}
                {fullVerdict === "warn" && <span className="text-xs text-amber-600">存在负偏离项，请人工复核</span>}
                {fullVerdict === "pass" && fullMd && <span className="text-xs text-green-600">全部要求响应通过</span>}
              </div>
              <p className="text-[11px] text-gray-400 mt-2">
                依次流式生成封面/目录/5 个章节，并自动产出招标要求逐条响应对照表（不满足项标红），全程约 3-6 分钟。
              </p>
            </div>
            )}

            <div className="flex-1 overflow-auto px-5 py-4">
              {bidErr && (
                <div className="text-sm text-red-600 bg-red-50 dark:bg-red-950/40 rounded-lg p-3 mb-3">
                  {bidErr}
                </div>
              )}

              {bidTab === "section" ? (<>
              {!bidMarkdown && !bidErr && !bidStreaming && (
                <div className="text-sm text-gray-400 text-center py-12">
                  选择章节后点击「生成本章草稿」，将基于本招标文件与同类案例流式产出
                </div>
              )}
              {bidStreaming && !bidMarkdown && (
                <div className="text-sm text-gray-400 text-center py-12">
                  <Loader2 className="animate-spin inline mr-2" size={14} />正在组织内容…
                </div>
              )}
              {bidMarkdown && (() => {
                const pending = remainingPlaceholders(bidMarkdown);
                return (<>
                  {pending.length > 0 && (
                    <div className="text-xs bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-900 rounded-lg px-3 py-2 mb-3 text-amber-800 dark:text-amber-200">
                      待人工处理占位符 {pending.length} 项（正文黄色高亮）：{pending.slice(0, 8).map((p) => `[${p}]`).join(" ")}
                      {pending.length > 8 ? " …" : ""}
                    </div>
                  )}
                  <div className="bid-md text-sm text-gray-800 dark:text-gray-200">
                    <ReactMarkdown components={MD_HL}>{`## ${bidTitle || "章节草稿"}\n\n${bidMarkdown.replace(/^\s*#{1,3}\s*[^\n]*\n+/, (m) => (bidTitle && m.includes(bidTitle) ? "" : m))}`}</ReactMarkdown>
                  </div>
                </>);
              })()}
              </>) : (<>
              {fullBusy && fullProgress.length > 0 && (
                <div className="mb-4 space-y-1.5">
                  {fullProgress.map((p) => (
                    <div key={p.key} className="flex items-center gap-2 text-sm">
                      {p.status === "done"
                        ? <CheckCircle size={14} className="text-green-600" />
                        : <Loader2 size={14} className="animate-spin text-blue-600" />}
                      <span className={p.status === "done" ? "text-gray-500" : "text-gray-800 dark:text-gray-200"}>{p.title}</span>
                      <span className="text-xs text-gray-400">{p.status === "done" ? "完成" : "生成中…"}</span>
                    </div>
                  ))}
                  {fullProgress.every((p) => p.status === "done") && !fullMd && (
                    <div className="text-xs text-gray-500 flex items-center gap-2"><Loader2 size={13} className="animate-spin" />正在生成逐条响应对照表…</div>
                  )}
                </div>
              )}
              {!fullBusy && !fullMd && (
                <div className="text-sm text-gray-400 text-center py-12">
                  点击「一键生成整本标书」，自动合稿并对招标要求逐条体检（不合格项标红）
                </div>
              )}
              {fullHard.length > 0 && (
                <div className="mb-3 rounded-lg border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-950/40 p-3">
                  <div className="text-sm font-semibold text-red-700 dark:text-red-400 flex items-center gap-2 mb-1">
                    <AlertTriangle size={14} /> {fullHard.length} 项实质性条款不合格（投标前必须整改）
                  </div>
                  <ul className="text-xs text-red-800 dark:text-red-300 list-disc pl-5 space-y-0.5">
                    {fullHard.slice(0, 10).map((r, i) => (
                      <li key={i}>第 {r.no} 条（{r.category}）：{r.requirement}</li>
                    ))}
                  </ul>
                </div>
              )}
              {fullFill && (fullFill.filled.length > 0 || fullFill.missing_company.length > 0 || fullFill.pending_business.length > 0) && (
                <div className="mb-3 rounded-lg bg-gray-50 dark:bg-gray-800/60 p-3 text-xs space-y-0.5">
                  {fullFill.filled.length > 0 && (
                    <div className="text-green-700 dark:text-green-400">企业资料已自动回填 {fullFill.filled.length} 项：{fullFill.filled.slice(0, 8).join("、")}</div>
                  )}
                  {fullFill.missing_company.length > 0 && (
                    <div className="text-amber-700 dark:text-amber-400">企业资料缺失 {fullFill.missing_company.length} 项（请在<a className="underline" href="/profile" target="_blank">企业资料库</a>补全后重生成）：{fullFill.missing_company.join("、")}</div>
                  )}
                  {fullFill.pending_business.length > 0 && (
                    <div className="text-gray-500">业务测算类占位 {fullFill.pending_business.length} 项需手工填写：{fullFill.pending_business.slice(0, 8).join("、")}</div>
                  )}
                </div>
              )}
              {fullMatrix.length > 0 && (
                <div className="mb-4">
                  <div className="text-sm font-semibold mb-2">招标要求逐条响应对照表</div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs border-collapse">
                      <thead>
                        <tr className="bg-gray-100 dark:bg-gray-800">
                          {["序号", "招标要求", "类别", "实质性", "投标响应内容", "状态", "章节/说明"].map((h) => (
                            <th key={h} className="border border-gray-300 dark:border-gray-700 px-2 py-1.5 text-left">{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {fullMatrix.map((r) => (
                          <tr key={r.no} className={matrixRowClass(r.status, r.material)}>
                            <td className="border border-gray-300 dark:border-gray-700 px-2 py-1.5">{r.no}</td>
                            <td className="border border-gray-300 dark:border-gray-700 px-2 py-1.5 min-w-[160px]">{r.requirement}</td>
                            <td className="border border-gray-300 dark:border-gray-700 px-2 py-1.5">{r.category}</td>
                            <td className="border border-gray-300 dark:border-gray-700 px-2 py-1.5">{r.material ? "★是" : "否"}</td>
                            <td className="border border-gray-300 dark:border-gray-700 px-2 py-1.5 min-w-[160px]">{r.response || "（投标稿未提及）"}</td>
                            <td className="border border-gray-300 dark:border-gray-700 px-2 py-1.5 whitespace-nowrap">{statusBadge(r.status)}</td>
                            <td className="border border-gray-300 dark:border-gray-700 px-2 py-1.5 text-gray-500">{r.evidence || r.note}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
              {fullMd && (
                <details className="mb-2" open={fullMatrix.length === 0}>
                  <summary className="text-sm text-blue-600 cursor-pointer">查看整本 Markdown（封面/目录/五章/附录/待补清单）</summary>
                  <div className="bid-md text-sm text-gray-800 dark:text-gray-200 mt-2">
                    <ReactMarkdown components={MD_HL}>{fullMd}</ReactMarkdown>
                  </div>
                </details>
              )}
              </>)}
            </div>
            <style>{`
              .bid-md h2 { font-size: 1.05rem; font-weight: 600; margin: 1rem 0 .5rem; }
              .bid-md h3 { font-size: .95rem; font-weight: 600; margin: .8rem 0 .4rem; }
              .bid-md p { margin: .4rem 0; line-height: 1.7; }
              .bid-md ul { list-style: disc; padding-left: 1.4rem; margin: .4rem 0; }
              .bid-md ol { list-style: decimal; padding-left: 1.4rem; margin: .4rem 0; }
              .bid-md li { margin: .2rem 0; line-height: 1.6; }
              .bid-md table { border-collapse: collapse; width: 100%; margin: .6rem 0; font-size: .8rem; }
              .bid-md th, .bid-md td { border: 1px solid #d1d5db; padding: .3rem .5rem; text-align: left; }
              .bid-md th { background: #f3f4f6; }
              .dark .bid-md th { background: #1f2937; }
              .dark .bid-md th, .dark .bid-md td { border-color: #374151; }
            `}</style>
          </div>
        </div>
      )}

      {/* 企业资质输入弹窗 */}
      {qualInputOpen && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={() => setQualInputOpen(false)}>
          <div className="bg-white dark:bg-gray-900 rounded-xl max-w-lg w-full p-5" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-medium">输入企业资质</h3>
              <button onClick={() => setQualInputOpen(false)} className="p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded">
                <X size={18} />
              </button>
            </div>
            <p className="text-xs text-gray-500 mb-2">每行一条资质，用于与招标文件资质要求对比</p>
            <textarea
              value={qualInput}
              onChange={(e) => setQualInput(e.target.value)}
              rows={8}
              placeholder="例如:
营业执照（统一社会信用代码 xxxx）
ISO 9001 质量管理体系认证
市政公用工程施工总承包一级资质
近 3 年类似项目 5 个
..."
              className="w-full rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 p-3 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono"
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => setQualInputOpen(false)}
                className="px-4 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition">
                取消
              </button>
              <button
                onClick={() => {
                  const certs = qualInput.split("\n").map(s => s.trim()).filter(Boolean);
                  if (certs.length === 0) return;
                  setQualInputOpen(false);
                  if (qualTargetId.current) {
                    runQualificationCheck(qualTargetId.current, certs);
                  }
                }}
                disabled={!qualInput.trim()}
                className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-lg transition">
                开始审查
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 废标自查情况输入弹窗 (可留空, 留空仅提取条款清单) */}
      {rejInputOpen && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={() => setRejInputOpen(false)}>
          <div className="bg-white dark:bg-gray-900 rounded-xl max-w-lg w-full p-5" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-medium flex items-center gap-2">
                <FileWarning size={18} className="text-orange-600" /> 废标条款检查
              </h3>
              <button onClick={() => setRejInputOpen(false)} className="p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded">
                <X size={18} />
              </button>
            </div>
            <p className="text-xs text-gray-500 mb-2">
              直接点"提取条款"将列出文件中全部废标/否决投标条款；填写我方投标准备情况后，可同时做废标风险自查
            </p>
            <textarea
              value={rejInput}
              onChange={(e) => setRejInput(e.target.value)}
              rows={7}
              placeholder="可选 — 描述我方准备情况, 例如:
投标报价 820 万元
已按要求盖章签字, 保证金 10 万元已从基本户汇出
投标工期承诺 100 天, 投标有效期 90 天
具备电子与智能化一级资质
非联合体投标..."
              className="w-full rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 p-3 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-orange-500 font-mono"
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => setRejInputOpen(false)}
                className="px-4 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition">
                取消
              </button>
              <button
                onClick={() => {
                  const status = rejInput.trim();
                  setRejInputOpen(false);
                  if (rejTargetId.current) {
                    runRejectionCheck(rejTargetId.current, status || undefined);
                  }
                }}
                className="px-4 py-2 text-sm bg-orange-600 hover:bg-orange-700 text-white rounded-lg transition">
                {rejInput.trim() ? "提取条款并自查" : "仅提取条款"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 投标响应性检查输入弹窗 */}
      {respInputOpen && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={() => setRespInputOpen(false)}>
          <div className="bg-white dark:bg-gray-900 rounded-xl max-w-2xl w-full p-5" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-medium flex items-center gap-2">
                <FileCheck size={18} className="text-teal-600" /> 投标响应性检查
              </h3>
              <button onClick={() => setRespInputOpen(false)} className="p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded">
                <X size={18} />
              </button>
            </div>
            <p className="text-xs text-gray-500 mb-3">
              粘贴投标文件内容, 系统将对照招标文件实质性条款逐条判定响应情况。
              可指定条款号 (如 "3.2") 只检查该条款, 留空则检查全部实质性条款。
            </p>
            <div className="mb-3">
              <label className="block text-xs text-gray-500 mb-1">指定条款号 (可选)</label>
              <input
                value={respClause}
                onChange={(e) => setRespClause(e.target.value)}
                placeholder="如: 3.2"
                className="w-full rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-teal-500"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">投标文件内容</label>
              <textarea
                value={respBidText}
                onChange={(e) => setRespBidText(e.target.value)}
                rows={10}
                placeholder="粘贴投标文件正文, 例如:
投标报价: 人民币 820 万元
投标工期: 100 个日历天
质保期: 3 年..."
                className="w-full rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 p-3 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-teal-500 font-mono"
              />
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => setRespInputOpen(false)}
                className="px-4 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition">
                取消
              </button>
              <button
                onClick={() => {
                  const text = respBidText.trim();
                  if (!text) return;
                  setRespInputOpen(false);
                  if (respTargetId.current) {
                    runResponseCheck(respTargetId.current, text, respClause.trim());
                  }
                }}
                disabled={!respBidText.trim()}
                className="px-4 py-2 text-sm bg-teal-600 hover:bg-teal-700 disabled:opacity-50 text-white rounded-lg transition">
                开始检查
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 多家投标对比弹窗 */}
      {cmpOpen && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={() => setCmpOpen(false)}>
          <div className="bg-white dark:bg-gray-900 rounded-xl max-w-3xl w-full p-5 max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-medium flex items-center gap-2">
                <ClipboardCheck size={18} className="text-indigo-600" /> 多家投标对比
              </h3>
              <button onClick={() => setCmpOpen(false)} className="p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded">
                <X size={18} />
              </button>
            </div>
            <p className="text-xs text-gray-500 mb-3">
              粘贴各投标人的投标文件内容, 系统将抽取关键字段并并排对比。
            </p>
            <div className="space-y-3">
              {cmpBids.map((b, i) => (
                <div key={i} className="border border-gray-200 dark:border-gray-700 rounded-lg p-3">
                  <div className="flex items-center gap-2 mb-2">
                    <input
                      value={b.name}
                      onChange={(e) => {
                        const v = e.target.value;
                        setCmpBids((prev) => prev.map((x, j) => j === i ? { ...x, name: v } : x));
                      }}
                      placeholder={`投标人 ${i + 1} 名称`}
                      className="flex-1 rounded border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 px-2 py-1 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    />
                    {cmpBids.length > 2 && (
                      <button
                        onClick={() => setCmpBids((prev) => prev.filter((_, j) => j !== i))}
                        className="text-red-500 hover:text-red-700 text-xs">移除</button>
                    )}
                  </div>
                  <textarea
                    value={b.text}
                    onChange={(e) => {
                      const v = e.target.value;
                      setCmpBids((prev) => prev.map((x, j) => j === i ? { ...x, text: v } : x));
                    }}
                    rows={4}
                    placeholder="粘贴该投标人的投标文件内容..."
                    className="w-full rounded border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 p-2 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-indigo-500 font-mono"
                  />
                </div>
              ))}
            </div>
            <div className="mt-3 flex items-center justify-between">
              <button
                onClick={() => setCmpBids((prev) => [...prev, { name: `投标人${prev.length + 1}`, text: "" }])}
                className="text-xs text-indigo-600 hover:text-indigo-700">
                + 添加投标人
              </button>
              <div className="flex gap-2">
                <button
                  onClick={() => setCmpOpen(false)}
                  className="px-4 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition">
                  取消
                </button>
                <button
                  onClick={runCompare}
                  disabled={cmpLoading}
                  className="px-4 py-2 text-sm bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white rounded-lg transition">
                  {cmpLoading ? <Loader2 className="animate-spin" size={14} /> : "开始对比"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 检测结果主动预警弹窗 (R17) */}
      {alert && (
        <AlertModal
          alert={alert}
          onClose={() => setAlert(null)}
          onDetail={
            alert.targetId
              ? () => document.getElementById(alert.targetId!)?.scrollIntoView({ behavior: "smooth", block: "start" })
              : undefined
          }
        />
      )}

      {/* 登录 / 注册弹窗 */}
      {authOpen && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={() => setAuthOpen(false)}>
          <div className="bg-white dark:bg-gray-900 rounded-xl max-w-sm w-full p-5" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-medium flex items-center gap-2">
                <User size={18} className="text-gray-600" /> 招投标 Agent 登录
              </h3>
              <button onClick={() => setAuthOpen(false)} className="p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded">
                <X size={18} />
              </button>
            </div>
            <div className="flex gap-2 mb-4 border-b border-gray-200 dark:border-gray-700">
              {(["login", "register"] as const).map((m) => (
                <button key={m} onClick={() => setAuthMode(m)}
                  className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition ${
                    authMode === m ? "border-blue-600 text-blue-600 dark:text-blue-400" : "border-transparent text-gray-500"
                  }`}>
                  {m === "login" ? "登录" : "注册"}
                </button>
              ))}
            </div>
            <AuthFormInline mode={authMode} API={API}
              onSuccess={(token, user) => { setAuthToken(token); setAuthUser(user); setAuthOpen(false); }}
              onError={(e) => setError(e)} />
            <p className="mt-3 text-xs text-gray-400 text-center">默认 admin / admin123</p>
          </div>
        </div>
      )}

      {/* 报价计算弹窗 */}
      {priceOpen && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={() => setPriceOpen(false)}>
          <div className="bg-white dark:bg-gray-900 rounded-xl max-w-2xl w-full p-5 max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-medium flex items-center gap-2">
                <Calculator size={18} className="text-amber-600" /> 报价计算（算术校验 + 价格分）
              </h3>
              <button onClick={() => setPriceOpen(false)} className="p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded"><X size={18} /></button>
            </div>
            <div className="space-y-3 text-sm">
              <div>
                <label className="block text-xs text-gray-500 mb-1">分项报价（每行：名称,数量,单价,填报金额；金额可留空自动计算）</label>
                <textarea value={priceItemsText} onChange={(e) => setPriceItemsText(e.target.value)} rows={5}
                  className="w-full rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 p-2 font-mono text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-amber-500" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs text-gray-500 mb-1">投标总价（数字）</label>
                  <input value={priceTotal} onChange={(e) => setPriceTotal(e.target.value)}
                    className="w-full rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-2 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-amber-500" />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">总价大写</label>
                  <input value={priceCn} onChange={(e) => setPriceCn(e.target.value)}
                    className="w-full rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-2 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-amber-500" />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">最高限价（可空）</label>
                  <input value={priceControl} onChange={(e) => setPriceControl(e.target.value)}
                    className="w-full rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-2 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-amber-500" />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">全部投标报价（逗号分隔，算基准价）</label>
                  <input value={priceOthers} onChange={(e) => setPriceOthers(e.target.value)}
                    className="w-full rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-2 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-amber-500" />
                </div>
              </div>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button onClick={() => setPriceOpen(false)}
                className="px-4 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition">取消</button>
              <button disabled={priceLoading} onClick={runPriceCalc}
                className="px-4 py-2 text-sm bg-amber-600 hover:bg-amber-700 disabled:opacity-50 text-white rounded-lg transition">
                {priceLoading ? <Loader2 className="animate-spin inline" size={14} /> : "开始计算"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 投标解析弹窗 */}
      {bpOpen && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={() => setBpOpen(false)}>
          <div className="bg-white dark:bg-gray-900 rounded-xl max-w-2xl w-full p-5 max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-medium flex items-center gap-2">
                <FileSearch size={18} className="text-sky-600" /> 投标文件解析（商务 / 技术 / 资格）
              </h3>
              <button onClick={() => setBpOpen(false)} className="p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded"><X size={18} /></button>
            </div>
            <div className="space-y-3 text-sm">
              <input value={bpName} onChange={(e) => setBpName(e.target.value)} placeholder="投标人名称（可空，自动从正文提取）"
                className="w-full rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-2 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-sky-500" />
              <textarea value={bpText} onChange={(e) => setBpText(e.target.value)} rows={10}
                placeholder="粘贴投标文件全文（投标函/报价/工期/质保/技术方案/资质业绩...）"
                className="w-full rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 p-2 font-mono text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-sky-500" />
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button onClick={() => setBpOpen(false)}
                className="px-4 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition">取消</button>
              <button disabled={bpLoading} onClick={runBidParse}
                className="px-4 py-2 text-sm bg-sky-600 hover:bg-sky-700 disabled:opacity-50 text-white rounded-lg transition">
                {bpLoading ? <Loader2 className="animate-spin inline" size={14} /> : "开始解析"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 围串标线索弹窗 */}
      {colOpen && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={() => setColOpen(false)}>
          <div className="bg-white dark:bg-gray-900 rounded-xl max-w-xl w-full p-5" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-medium flex items-center gap-2">
                <Radar size={18} className="text-rose-600" /> 围串标线索扫描
              </h3>
              <button onClick={() => setColOpen(false)} className="p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded"><X size={18} /></button>
            </div>
            <div className="space-y-3 text-sm">
              <p className="text-xs text-gray-500">上传 2 份以上投标文件原件（.pdf/.docx/.txt），系统比对文本雷同、文件属性元数据与报价规律。<b>仅输出线索，不自动定性。</b></p>
              <input ref={colInputRef} type="file" multiple accept=".pdf,.docx,.txt,.md"
                className="block w-full text-xs text-gray-600 file:mr-3 file:py-2 file:px-3 file:rounded-lg file:border-0 file:bg-rose-50 file:text-rose-700 hover:file:bg-rose-100" />
              <p className="text-xs text-gray-400">提示：.docx/.pdf 原件可读取作者/最后保存者/生成程序等属性；IP/MAC 非标准元数据，仅识别正文暴露地址。</p>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button onClick={() => setColOpen(false)}
                className="px-4 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition">取消</button>
              <button disabled={colLoading} onClick={runCollusion}
                className="px-4 py-2 text-sm bg-rose-600 hover:bg-rose-700 disabled:opacity-50 text-white rounded-lg transition">
                {colLoading ? <Loader2 className="animate-spin inline" size={14} /> : "开始扫描"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 智能工作流弹窗 */}
      {wfOpen && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={() => setWfOpen(false)}>
          <div className="bg-white dark:bg-gray-900 rounded-xl max-w-xl w-full p-5" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-medium flex items-center gap-2">
                <Shield size={18} className="text-emerald-600" /> 智能工作流
              </h3>
              <button onClick={() => setWfOpen(false)} className="p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded">
                <X size={18} />
              </button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="block text-xs text-gray-500 mb-1">选择预置工作流</label>
                {wfPresets.length === 0 ? (
                  <div className="text-xs text-gray-400">加载中...</div>
                ) : (
                  <div className="grid grid-cols-1 gap-2">
                    {wfPresets.map((p) => (
                      <label key={p.id} className={`flex items-start gap-2 p-3 rounded-lg border cursor-pointer transition ${wfConfig === p.id ? "border-emerald-500 bg-emerald-50 dark:bg-emerald-950/30" : "border-gray-200 dark:border-gray-700 hover:border-gray-400"}`}>
                        <input type="radio" name="wf" value={p.id} checked={wfConfig === p.id}
                          onChange={() => setWfConfig(p.id)} className="mt-1 accent-emerald-600" />
                        <div>
                          <div className="text-sm font-medium text-gray-900 dark:text-gray-100">{p.name}</div>
                          <div className="text-xs text-gray-500 mt-0.5">{p.description}</div>
                        </div>
                      </label>
                    ))}
                  </div>
                )}
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">招标文件 (从已解析文档选 db_id)</label>
                <select value={wfDbId ?? ""} onChange={(e) => setWfDbId(e.target.value ? Number(e.target.value) : null)}
                  className="w-full rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-emerald-500">
                  <option value="">-- 选择 --</option>
                  {docs.map((d: any) => (
                    <option key={d.id} value={d.id}>#{d.id} {d.source_file}</option>
                  ))}
                </select>
              </div>
              {wfConfig === "eval_assist" && (
                <div>
                  <label className="block text-xs text-gray-500 mb-1">投标文件内容 (响应性检查可选)</label>
                  <textarea value={wfBidText} onChange={(e) => setWfBidText(e.target.value)} rows={3}
                    className="w-full rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 p-2 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-emerald-500 font-mono"
                    placeholder="投标报价: xx 万元&#10;投标工期: xxx 天&#10;质保期: x 年..." />
                </div>
              )}
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button onClick={() => setWfOpen(false)}
                className="px-4 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition">取消</button>
              <button disabled={!wfDbId || wfLoading}
                onClick={async () => {
                  setWfLoading(true);
                  setWfResult(null);
                  try {
                    const ctx: any = { db_id: wfDbId };
                    if (wfBidText) ctx.bid_text = wfBidText;
                    const r = await fetch(`${API}/api/workflow/run`, {
                      method: "POST", headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ config: wfConfig, ctx }),
                    });
                    if (!r.ok) throw new Error(await r.text());
                    setWfResult(await r.json());
                    setWfOpen(false);
                  } catch (e: any) { setError(`工作流执行失败: ${e?.message}`); }
                  finally { setWfLoading(false); }
                }}
                className="px-4 py-2 text-sm bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white rounded-lg transition">
                {wfLoading ? <Loader2 className="animate-spin inline" size={14} /> : "执行工作流"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ================== 登录/注册表单 ==================

function AuthFormInline({ mode, API, onSuccess, onError }: {
  mode: "login" | "register"; API: string;
  onSuccess: (token: string, user: any) => void; onError: (msg: string) => void;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [role, setRole] = useState<"bidder" | "purchaser">("bidder");
  const [loading, setLoading] = useState(false);

  const submit = async () => {
    if (username.length < 3 || password.length < 6) { onError("用户名至少3位, 密码至少6位"); return; }
    setLoading(true);
    try {
      const r = await fetch(`${API}/auth/${mode}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(mode === "login"
          ? { username, password }
          : { username, password, display_name: displayName, role }),
      });
      if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || `HTTP ${r.status}`); }
      const data = await r.json();
      if (mode === "login" && data.access_token) { onSuccess(data.access_token, data.user); }
      else {
        const lr = await fetch(`${API}/auth/login`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username, password }),
        });
        if (lr.ok) { const ld = await lr.json(); onSuccess(ld.access_token, ld.user); }
        else { onError("注册成功, 自动登录失败"); }
      }
    } catch (e: any) { onError(e?.message || "请求失败"); }
    finally { setLoading(false); }
  };

  return (
    <div className="space-y-3">
      <div>
        <label className="block text-xs text-gray-500 mb-1">用户名</label>
        <input value={username} onChange={(e) => setUsername(e.target.value)}
          className="w-full rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500" />
      </div>
      <div>
        <label className="block text-xs text-gray-500 mb-1">密码</label>
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
          className="w-full rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500" />
      </div>
      {mode === "register" && (
        <div>
          <label className="block text-xs text-gray-500 mb-1">显示名 (可选)</label>
          <input value={displayName} onChange={(e) => setDisplayName(e.target.value)}
            className="w-full rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
      )}
      {mode === "register" && (
        <div>
          <label className="block text-xs text-gray-500 mb-1">注册身份</label>
          <div className="grid grid-cols-2 gap-2">
            {([["bidder", "投标人（编标自查）"], ["purchaser", "招标人（上传招标）"]] as const).map(([v, label]) => (
              <button key={v} type="button" onClick={() => setRole(v)}
                className={`text-xs px-2 py-2 rounded-lg border transition ${role === v
                  ? "border-blue-500 bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300"
                  : "border-gray-300 dark:border-gray-700 text-gray-600 dark:text-gray-300"}`}>
                {label}
              </button>
            ))}
          </div>
          <p className="text-[11px] text-gray-400 mt-1">专家/管理员账号由系统管理员分配，不在此注册</p>
        </div>
      )}
      <button onClick={submit} disabled={loading}
        className="w-full py-2 text-sm bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-lg transition">
        {loading ? <Loader2 className="animate-spin inline" size={14} /> : mode === "login" ? "登录" : "注册并登录"}
      </button>
    </div>
  );
}

// ================== 工作流结果面板 ==================

function WorkflowPanel({ result, onClose }: { result: any; onClose?: () => void }) {
  const { name, results, summary, nodes } = result;
  const verdictMap: Record<string, { text: string; cls: string }> = {
    ok: { text: "✅ 全部成功", cls: "bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200" },
    partial: { text: "⚠️ 部分降级", cls: "bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200" },
    failed: { text: "❌ 全部失败", cls: "bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-200" },
  };
  return (
    <div className="mt-4 border border-gray-200 dark:border-gray-800 rounded-xl overflow-hidden">
      <div className="bg-emerald-50 dark:bg-emerald-950/30 border-b border-emerald-200 dark:border-emerald-800 p-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Shield className="text-emerald-600" size={18} />
          <span className="text-sm font-medium text-emerald-900 dark:text-emerald-100">智能工作流</span>
          <span className="text-xs text-gray-500 ml-1">{name}</span>
          {summary && (
            <span className={`text-xs px-2 py-0.5 rounded font-medium ${verdictMap[summary.verdict]?.cls || "bg-gray-100"}`}>
              {verdictMap[summary.verdict]?.text || summary.verdict}
              {" "}{summary.success}/{summary.total}
            </span>
          )}
        </div>
        {onClose && <button onClick={onClose} className="text-emerald-500 hover:text-emerald-700 text-xs">关闭</button>}
      </div>
      <div className="p-5">
        <div className="space-y-2">
          {nodes?.map((nid: string, idx: number) => {
            const info = results[nid];
            const isOk = info?.status === "success";
            return (
              <div key={nid} className={`border rounded-lg p-3 ${isOk ? "border-green-200 dark:border-green-800 bg-green-50/50 dark:bg-green-950/20" : "border-red-200 dark:border-red-800 bg-red-50/50 dark:bg-red-950/20"}`}>
                <div className="flex items-center gap-2 flex-wrap mb-1">
                  <span className="text-xs font-mono text-gray-400">#{idx + 1}</span>
                  <span className="text-sm font-medium text-gray-900 dark:text-gray-100">{nid}</span>
                  <span className={`text-xs px-2 py-0.5 rounded font-medium ${isOk ? "bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-300" : "bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-300"}`}>
                    {info?.status}
                  </span>
                  {info?.duration_ms != null && <span className="text-xs text-gray-400">{info.duration_ms}ms</span>}
                </div>
                {info?.output_keys?.length > 0 && (
                  <div className="text-xs text-gray-500 dark:text-gray-400">
                    输出: {info.output_keys.join(", ")}
                  </div>
                )}
                {info?.error && (
                  <div className="text-xs text-red-600 dark:text-red-400">⚠️ {info.error}</div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ================== 报价计算结果 ==================

function PricePanel({ result, onClose }: { result: any; onClose?: () => void }) {
  const verdictMap: Record<string, { text: string; cls: string }> = {
    pass: { text: "✅ 校验通过", cls: "bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200" },
    attention: { text: "⚠️ 存在警告", cls: "bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200" },
    fail: { text: "❌ 存在错误", cls: "bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-200" },
  };
  const v = verdictMap[result.verdict] || verdictMap.attention;
  const fmt = (x: any) => (x == null ? "—" : Number(x).toLocaleString("zh-CN", { maximumFractionDigits: 2 }));
  return (
    <div className="mt-4 border border-gray-200 dark:border-gray-800 rounded-xl overflow-hidden">
      <div className="bg-amber-50 dark:bg-amber-950/30 border-b border-amber-200 dark:border-amber-800 p-3 flex items-center justify-between">
        <div className="flex items-center gap-2 flex-wrap">
          <Calculator className="text-amber-600" size={18} />
          <span className="text-sm font-medium text-amber-900 dark:text-amber-100">报价计算表</span>
          <span className={`text-xs px-2 py-0.5 rounded font-medium ${v.cls}`}>{v.text}</span>
          {result.price_score != null && (
            <span className="text-xs px-2 py-0.5 rounded bg-amber-100 dark:bg-amber-900/50 text-amber-800 dark:text-amber-200">
              价格分 {result.price_score}
            </span>
          )}
        </div>
        {onClose && <button onClick={onClose} className="text-amber-600 hover:text-amber-800 text-xs">关闭</button>}
      </div>
      <div className="p-5 space-y-4">
        <div className="flex flex-wrap gap-4 text-sm text-gray-700 dark:text-gray-200">
          <span>分项合计：<b>{fmt(result.subtotal)}</b></span>
          <span>投标总价：<b>{fmt(result.declared_total)}</b></span>
          <span>差额：<b className={result.total_diff ? "text-red-600" : "text-green-600"}>{fmt(result.total_diff)}</b></span>
          <span>大写解析：<b>{fmt(result.cn_amount)}</b></span>
          {result.base_price != null && <span>评标基准价：<b>{fmt(result.base_price)}</b></span>}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="bg-gray-50 dark:bg-gray-800 text-gray-500">
                {["#", "分项", "数量", "单价", "填报金额", "计算金额", "异常"].map((h) => (
                  <th key={h} className="border border-gray-200 dark:border-gray-700 px-2 py-1 text-left font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.table?.map((r: any) => (
                <tr key={r.row} className={r.row_anomalies?.length ? "bg-red-50/60 dark:bg-red-950/20" : ""}>
                  <td className="border border-gray-200 dark:border-gray-700 px-2 py-1">{r.row}</td>
                  <td className="border border-gray-200 dark:border-gray-700 px-2 py-1">{r.name}</td>
                  <td className="border border-gray-200 dark:border-gray-700 px-2 py-1">{fmt(r.qty)}</td>
                  <td className="border border-gray-200 dark:border-gray-700 px-2 py-1">{fmt(r.unit_price)}</td>
                  <td className="border border-gray-200 dark:border-gray-700 px-2 py-1">{fmt(r.filled_amount)}</td>
                  <td className="border border-gray-200 dark:border-gray-700 px-2 py-1">{fmt(r.calc_amount)}</td>
                  <td className="border border-gray-200 dark:border-gray-700 px-2 py-1 text-red-600 dark:text-red-400">{(r.row_anomalies || []).join("；")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {result.anomalies?.length > 0 && (
          <ul className="space-y-1">
            {result.anomalies.map((a: any, i: number) => (
              <li key={i} className={`text-xs flex gap-2 ${a.level === "error" ? "text-red-600 dark:text-red-400" : "text-yellow-700 dark:text-yellow-400"}`}>
                <span>{a.level === "error" ? "❌" : "⚠️"}</span>
                <span><b>[{a.code}]</b> {a.message}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

// ================== 投标文件解析结果 ==================

function BidParsePanel({ result, onClose }: { result: any; onClose?: () => void }) {
  const commercial = result.commercial || {};
  const technical = result.technical || {};
  const card = "border border-gray-200 dark:border-gray-700 rounded-lg p-3";
  const kv = (d: Record<string, any>) => Object.entries(d).map(([k, v]) => (
    <div key={k} className="flex gap-2 text-xs py-1 border-b border-gray-100 dark:border-gray-800 last:border-0">
      <span className="text-gray-500 w-20 shrink-0">{k}</span>
      <span className="text-gray-800 dark:text-gray-200">{v || <span className="text-gray-400">未提及</span>}</span>
    </div>
  ));
  return (
    <div className="mt-4 border border-gray-200 dark:border-gray-800 rounded-xl overflow-hidden">
      <div className="bg-sky-50 dark:bg-sky-950/30 border-b border-sky-200 dark:border-sky-800 p-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <FileSearch className="text-sky-600" size={18} />
          <span className="text-sm font-medium text-sky-900 dark:text-sky-100">投标文件解析</span>
          <span className="text-xs text-gray-600 dark:text-gray-300">{result.bidder_name || "未知投标人"}</span>
        </div>
        {onClose && <button onClick={onClose} className="text-sky-600 hover:text-sky-800 text-xs">关闭</button>}
      </div>
      <div className="p-5 grid md:grid-cols-2 gap-3">
        <div className={card}>
          <div className="text-xs font-medium text-sky-700 dark:text-sky-300 mb-1">商务响应</div>
          {kv(commercial)}
        </div>
        <div className={card}>
          <div className="text-xs font-medium text-sky-700 dark:text-sky-300 mb-1">技术方案</div>
          {kv(technical)}
        </div>
        <div className={card}>
          <div className="text-xs font-medium text-sky-700 dark:text-sky-300 mb-1">资格资质（{result.qualifications?.length || 0}）</div>
          {result.qualifications?.length ? (
            <ul className="text-xs text-gray-800 dark:text-gray-200 list-disc pl-4 space-y-0.5">
              {result.qualifications.map((q: string, i: number) => <li key={i}>{q}</li>)}
            </ul>
          ) : <span className="text-xs text-gray-400">未抽出</span>}
        </div>
        <div className={card}>
          <div className="text-xs font-medium text-sky-700 dark:text-sky-300 mb-1">同类业绩（{result.performances?.length || 0}）</div>
          {result.performances?.length ? (
            <ul className="text-xs text-gray-800 dark:text-gray-200 list-disc pl-4 space-y-0.5">
              {result.performances.map((p: string, i: number) => <li key={i}>{p}</li>)}
            </ul>
          ) : <span className="text-xs text-gray-400">未抽出</span>}
        </div>
      </div>
    </div>
  );
}

// ================== 围串标线索结果 ==================

function CollusionPanel({ result, onClose }: { result: any; onClose?: () => void }) {
  const lvCls: Record<string, string> = {
    high: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",
    medium: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300",
    low: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300",
  };
  const lvText: Record<string, string> = { high: "高", medium: "中", low: "低" };
  const s = result.summary || {};
  return (
    <div className="mt-4 border border-gray-200 dark:border-gray-800 rounded-xl overflow-hidden">
      <div className="bg-rose-50 dark:bg-rose-950/30 border-b border-rose-200 dark:border-rose-800 p-3 flex items-center justify-between">
        <div className="flex items-center gap-2 flex-wrap">
          <Radar className="text-rose-600" size={18} />
          <span className="text-sm font-medium text-rose-900 dark:text-rose-100">围串标线索扫描</span>
          <span className={`text-xs px-2 py-0.5 rounded font-medium ${result.verdict === "clean"
            ? "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300"
            : "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300"}`}>
            {result.verdict === "clean" ? "未发现明显线索" : `发现 ${s.total_clues ?? 0} 条线索（高 ${s.high ?? 0} / 中 ${s.medium ?? 0} / 低 ${s.low ?? 0}）`}
          </span>
        </div>
        {onClose && <button onClick={onClose} className="text-rose-600 hover:text-rose-800 text-xs">关闭</button>}
      </div>
      <div className="p-5 space-y-3">
        <p className="text-xs text-gray-500 bg-gray-50 dark:bg-gray-800/60 rounded p-2">⚠️ {result.disclaimer}</p>
        {result.clues?.map((c: any) => (
          <div key={c.id} className="border border-gray-200 dark:border-gray-700 rounded-lg p-3">
            <div className="flex items-center gap-2 flex-wrap mb-1">
              <span className="text-xs font-mono text-gray-400">{c.id}</span>
              <span className="text-xs px-1.5 py-0.5 rounded font-medium">{c.pair?.join(" ⇄ ")}</span>
              <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${lvCls[c.level]}`}>{lvText[c.level]}风险</span>
              <span className="text-xs text-gray-500">{c.dimension} · {c.rule}</span>
            </div>
            <div className="text-xs text-gray-800 dark:text-gray-200">{c.reason}</div>
            {(c.evidence?.a || c.evidence?.b) && (
              <div className="mt-1 grid grid-cols-2 gap-2 text-xs">
                <div className="bg-gray-50 dark:bg-gray-800/60 rounded p-1.5 text-gray-600 dark:text-gray-300 truncate">A：{String(c.evidence.a)}</div>
                <div className="bg-gray-50 dark:bg-gray-800/60 rounded p-1.5 text-gray-600 dark:text-gray-300 truncate">B：{String(c.evidence.b)}</div>
              </div>
            )}
          </div>
        ))}
        {result.limitations?.length > 0 && (
          <div className="text-xs text-gray-400 space-y-0.5">
            {result.limitations.map((l: string, i: number) => <div key={i}>· {l}</div>)}
          </div>
        )}
      </div>
    </div>
  );
}
