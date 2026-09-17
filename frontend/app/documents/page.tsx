"use client";

import { useEffect, useRef, useState } from "react";
import { FileText, Upload, Loader2, CheckCircle, AlertCircle, Eye, X, Shield, ClipboardCheck, AlertTriangle, CheckSquare } from "lucide-react";

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
}

const API = "http://localhost:8001";

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

  // 弹窗（企业资质输入）
  const [qualInputOpen, setQualInputOpen] = useState(false);
  const [qualInput, setQualInput] = useState("");
  const qualTargetId = useRef<number | null>(null);

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

  const handleFile = async (file: File) => {
    setError(null);
    setParsed(null);
    setCompResult(null);
    setQualResult(null);
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("save_to_db", "true");
      const r = await fetch(`${API}/api/document/upload`, { method: "POST", body: fd });
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
      setCompResult(await r.json());
    } catch (e: any) {
      setCompResult({
        summary: { high: 0, medium: 0, low: 0, total_checked: 0, risks_found: 0 },
        risks: [], clean_rules: [], status: "warn",
        note: `检查失败: ${e?.message || "未知错误"}`,
      });
    } finally {
      setCompLoading(false);
    }
  };

  const runQualificationCheck = async (dbId: number, companyCerts: string[]) => {
    setQualLoading(true);
    setQualResult(null);
    try {
      const r = await fetch(`${API}/api/qualification/check`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ db_id: dbId, company_qualifications: companyCerts }),
      });
      if (!r.ok) throw new Error(await r.text());
      setQualResult(await r.json());
    } catch (e: any) {
      setQualResult({
        summary: { total_req: 0, full: 0, partial: 0, missing: 0 },
        checks: [],
        gap_report: "",
        verdict: "unknown",
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

  return (
    <div className="max-w-5xl mx-auto p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <FileText className="text-blue-600" /> 招标文件解析 & 审查
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          上传 PDF / Word / TXT / Markdown，自动抽取项目信息；支持合规性检查和资格条件审查。
        </p>
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
          accept=".pdf,.docx,.doc,.txt,.md"
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
        <p className="text-xs text-gray-400 mt-1">支持 .pdf / .docx / .doc / .txt / .md</p>
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
              </div>
            )}

            {compResult && (
              <CompliancePanel result={compResult} onClose={() => setCompResult(null)} />
            )}
            {qualResult && (
              <QualificationPanel result={qualResult} onClose={() => setQualResult(null)} />
            )}
          </div>
        </div>
      )}

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
                    <button onClick={() => setDetail(d)}
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
              </div>
            </div>
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
    </div>
  );
}
