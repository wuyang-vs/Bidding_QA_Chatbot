"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Building2, Loader2, Save, CheckCircle, AlertTriangle } from "lucide-react";

const API = "http://localhost:8001";

const TEXT_FIELDS: { key: string; label: string; area?: boolean; ph?: string }[] = [
  { key: "company_name", label: "公司全称 *", ph: "以营业执照为准" },
  { key: "company_short", label: "公司简称" },
  { key: "address", label: "注册地址", area: true },
  { key: "legal_person", label: "法定代表人" },
  { key: "registered_capital", label: "注册资本", ph: "如 人民币 5000 万元" },
  { key: "established_date", label: "成立日期", ph: "YYYY-MM-DD" },
  { key: "contact_person", label: "投标联系人" },
  { key: "contact_phone", label: "联系电话" },
  { key: "contact_email", label: "电子邮箱" },
  { key: "bank_name", label: "开户银行" },
  { key: "bank_account", label: "银行账号" },
  { key: "business_scope", label: "经营范围", area: true },
];

interface Cert { name: string; level: string; cert_no: string; valid_until: string; }
interface Project { name: string; owner: string; amount: string; date: string; role: string; }

const emptyProfile = () => ({
  company_name: "", company_short: "", address: "", legal_person: "",
  registered_capital: "", established_date: "", contact_person: "",
  contact_phone: "", contact_email: "", bank_name: "", bank_account: "",
  business_scope: "",
  certs: [] as Cert[], past_projects: [] as Project[],
});

export default function ProfilePage() {
  const [token, setToken] = useState("");
  const [loginUser, setLoginUser] = useState("");
  const [loginPwd, setLoginPwd] = useState("");
  const [loginErr, setLoginErr] = useState("");
  const [logging, setLogging] = useState(false);

  const [data, setData] = useState(emptyProfile());
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const [saved, setSaved] = useState(false);
  const [completeness, setCompleteness] = useState<any>(null);

  useEffect(() => {
    setToken(localStorage.getItem("qa_auth_token") || "");
  }, []);

  const load = async (tk: string) => {
    setLoading(true);
    setErr("");
    try {
      const r = await fetch(`${API}/api/profile`, {
        headers: { Authorization: `Bearer ${tk}` },
      });
      if (r.status === 401) { localStorage.removeItem("qa_auth_token"); setToken(""); return; }
      if (!r.ok) throw new Error(`加载失败 (${r.status})`);
      const d = await r.json();
      setData({ ...emptyProfile(), ...(d.profile || {}) });
      setCompleteness(d.completeness || null);
    } catch (e: any) {
      setErr(e?.message || "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { if (token) load(token); /* eslint-disable-next-line */ }, [token]);

  const doLogin = async () => {
    if (!loginUser.trim() || !loginPwd) { setLoginErr("请输入用户名和密码"); return; }
    setLogging(true);
    setLoginErr("");
    try {
      const r = await fetch(`${API}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: loginUser.trim(), password: loginPwd }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || `登录失败 (${r.status})`);
      localStorage.setItem("qa_auth_token", d.access_token);
      setToken(d.access_token);
    } catch (e: any) {
      setLoginErr(e?.message || "登录失败");
    } finally {
      setLogging(false);
    }
  };

  const setField = (k: string, v: string) => {
    setData((d) => ({ ...d, [k]: v }));
    setSaved(false);
  };

  const save = async () => {
    if (!data.company_name.trim()) { setErr("请至少填写公司全称"); return; }
    setSaving(true);
    setErr("");
    try {
      const r = await fetch(`${API}/api/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify(data),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || `保存失败 (${r.status})`);
      setData({ ...emptyProfile(), ...(d.profile || {}) });
      setCompleteness(d.completeness || null);
      setSaved(true);
    } catch (e: any) {
      setErr(e?.message || "保存失败");
    } finally {
      setSaving(false);
    }
  };

  if (!token) {
    return (
      <div className="max-w-sm mx-auto mt-24 p-6 border border-gray-200 dark:border-gray-800 rounded-xl">
        <h1 className="text-lg font-semibold flex items-center gap-2 mb-4">
          <Building2 className="text-blue-600" size={18} /> 企业资料库登录
        </h1>
        <p className="text-xs text-gray-500 mb-4">企业资料按登录账号 1:1 保存，请先登录（投标/招标账号均可）。</p>
        <div className="space-y-3">
          <input value={loginUser} onChange={(e) => setLoginUser(e.target.value)}
                 placeholder="用户名" className="w-full border border-gray-300 dark:border-gray-700 rounded-lg px-3 py-2 text-sm dark:bg-gray-900" />
          <input type="password" value={loginPwd} onChange={(e) => setLoginPwd(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && doLogin()}
                 placeholder="密码" className="w-full border border-gray-300 dark:border-gray-700 rounded-lg px-3 py-2 text-sm dark:bg-gray-900" />
          {loginErr && <div className="text-xs text-red-600">{loginErr}</div>}
          <button onClick={doLogin} disabled={logging}
                  className="w-full bg-blue-600 hover:bg-blue-700 text-white text-sm py-2 rounded-lg disabled:opacity-50 inline-flex items-center justify-center gap-2">
            {logging && <Loader2 size={14} className="animate-spin" />} 登录
          </button>
          <Link href="/documents" className="block text-center text-xs text-blue-600 hover:underline">← 返回文件库</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Building2 className="text-blue-600" /> 企业资料库
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            保存后，标书生成时自动回填 [公司全称]/[法定代表人]/[资质证书编号] 等占位符，并作为资格自动比对依据。
          </p>
        </div>
        <Link href="/documents" className="text-blue-600 hover:underline text-sm whitespace-nowrap">← 返回文件库</Link>
      </div>

      {loading && <div className="text-sm text-gray-400 flex items-center gap-2"><Loader2 size={14} className="animate-spin" />加载中…</div>}
      {err && <div className="text-sm text-red-600 bg-red-50 dark:bg-red-950/40 rounded-lg p-3 flex items-center gap-2"><AlertTriangle size={14} />{err}</div>}
      {saved && <div className="text-sm text-green-700 bg-green-50 dark:bg-green-950/40 rounded-lg p-3 flex items-center gap-2"><CheckCircle size={14} />已保存，后续标书生成将自动使用这些信息</div>}
      {completeness && (
        <div className="text-xs text-gray-500">
          基础字段 {completeness.filled_fields}/{completeness.total_fields} 已填 · 资质证书 {completeness.certs_count} 项 · 同类业绩 {completeness.projects_count} 条
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {TEXT_FIELDS.map((f) => (
          <div key={f.key} className={f.area ? "sm:col-span-2" : ""}>
            <label className="block text-xs text-gray-500 mb-1">{f.label}</label>
            {f.area ? (
              <textarea rows={2} value={(data as any)[f.key]} placeholder={f.ph}
                        onChange={(e) => setField(f.key, e.target.value)}
                        className="w-full border border-gray-300 dark:border-gray-700 rounded-lg px-3 py-2 text-sm dark:bg-gray-900" />
            ) : (
              <input value={(data as any)[f.key]} placeholder={f.ph}
                     onChange={(e) => setField(f.key, e.target.value)}
                     className="w-full border border-gray-300 dark:border-gray-700 rounded-lg px-3 py-2 text-sm dark:bg-gray-900" />
            )}
          </div>
        ))}
      </div>

      <section>
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-semibold">资质证书</h2>
          <button onClick={() => setData((d) => ({ ...d, certs: [...d.certs, { name: "", level: "", cert_no: "", valid_until: "" }] }))}
                  className="text-xs text-blue-600 hover:underline">+ 添加证书</button>
        </div>
        <div className="space-y-2">
          {data.certs.map((c, i) => (
            <div key={i} className="grid grid-cols-12 gap-2 items-center">
              <input value={c.name} placeholder="证书名称（如 软件企业证书/CMMI3）"
                     onChange={(e) => setData((d) => ({ ...d, certs: d.certs.map((x, j) => j === i ? { ...x, name: e.target.value } : x) }))}
                     className="col-span-4 border border-gray-300 dark:border-gray-700 rounded-lg px-2 py-1.5 text-sm dark:bg-gray-900" />
              <input value={c.level} placeholder="等级"
                     onChange={(e) => setData((d) => ({ ...d, certs: d.certs.map((x, j) => j === i ? { ...x, level: e.target.value } : x) }))}
                     className="col-span-2 border border-gray-300 dark:border-gray-700 rounded-lg px-2 py-1.5 text-sm dark:bg-gray-900" />
              <input value={c.cert_no} placeholder="证书编号"
                     onChange={(e) => setData((d) => ({ ...d, certs: d.certs.map((x, j) => j === i ? { ...x, cert_no: e.target.value } : x) }))}
                     className="col-span-3 border border-gray-300 dark:border-gray-700 rounded-lg px-2 py-1.5 text-sm dark:bg-gray-900" />
              <input value={c.valid_until} placeholder="有效期至"
                     onChange={(e) => setData((d) => ({ ...d, certs: d.certs.map((x, j) => j === i ? { ...x, valid_until: e.target.value } : x) }))}
                     className="col-span-2 border border-gray-300 dark:border-gray-700 rounded-lg px-2 py-1.5 text-sm dark:bg-gray-900" />
              <button onClick={() => setData((d) => ({ ...d, certs: d.certs.filter((_, j) => j !== i) }))}
                      className="col-span-1 text-xs text-red-500 hover:underline">删除</button>
            </div>
          ))}
          {data.certs.length === 0 && <p className="text-xs text-gray-400">暂无证书，占位符 [资质证书编号] 将保留待手填。</p>}
        </div>
      </section>

      <section>
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-semibold">同类项目业绩</h2>
          <button onClick={() => setData((d) => ({ ...d, past_projects: [...d.past_projects, { name: "", owner: "", amount: "", date: "", role: "" }] }))}
                  className="text-xs text-blue-600 hover:underline">+ 添加业绩</button>
        </div>
        <div className="space-y-2">
          {data.past_projects.map((pjt, i) => (
            <div key={i} className="grid grid-cols-12 gap-2 items-center">
              <input value={pjt.name} placeholder="项目名称"
                     onChange={(e) => setData((d) => ({ ...d, past_projects: d.past_projects.map((x, j) => j === i ? { ...x, name: e.target.value } : x) }))}
                     className="col-span-4 border border-gray-300 dark:border-gray-700 rounded-lg px-2 py-1.5 text-sm dark:bg-gray-900" />
              <input value={pjt.owner} placeholder="业主单位"
                     onChange={(e) => setData((d) => ({ ...d, past_projects: d.past_projects.map((x, j) => j === i ? { ...x, owner: e.target.value } : x) }))}
                     className="col-span-3 border border-gray-300 dark:border-gray-700 rounded-lg px-2 py-1.5 text-sm dark:bg-gray-900" />
              <input value={pjt.amount} placeholder="合同额"
                     onChange={(e) => setData((d) => ({ ...d, past_projects: d.past_projects.map((x, j) => j === i ? { ...x, amount: e.target.value } : x) }))}
                     className="col-span-2 border border-gray-300 dark:border-gray-700 rounded-lg px-2 py-1.5 text-sm dark:bg-gray-900" />
              <input value={pjt.date} placeholder="年份"
                     onChange={(e) => setData((d) => ({ ...d, past_projects: d.past_projects.map((x, j) => j === i ? { ...x, date: e.target.value } : x) }))}
                     className="col-span-1 border border-gray-300 dark:border-gray-700 rounded-lg px-2 py-1.5 text-sm dark:bg-gray-900" />
              <input value={pjt.role} placeholder="角色"
                     onChange={(e) => setData((d) => ({ ...d, past_projects: d.past_projects.map((x, j) => j === i ? { ...x, role: e.target.value } : x) }))}
                     className="col-span-1 border border-gray-300 dark:border-gray-700 rounded-lg px-2 py-1.5 text-sm dark:bg-gray-900" />
              <button onClick={() => setData((d) => ({ ...d, past_projects: d.past_projects.filter((_, j) => j !== i) }))}
                      className="col-span-1 text-xs text-red-500 hover:underline">删除</button>
            </div>
          ))}
        </div>
      </section>

      <div className="pt-2">
        <button onClick={save} disabled={saving}
                className="inline-flex items-center gap-2 px-5 py-2.5 text-sm bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-lg">
          {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
          {saving ? "保存中…" : "保存企业资料"}
        </button>
      </div>
    </div>
  );
}
