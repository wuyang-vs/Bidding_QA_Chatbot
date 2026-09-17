"use client";
import { useEffect, useRef, useState } from "react";
import { Plus, Search, Trash2, Moon, Sun, MoreVertical, X, BarChart3, Share2, Bot } from "lucide-react";
import Link from "next/link";

interface Props {
  conversations: any[];
  currentId: string;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onDeleteAll: () => void;
  onSearch: (q: string) => void;
  darkMode: boolean;
  setDarkMode: (v: boolean) => void;
  mobileOpen: boolean;
  setMobileOpen: (v: boolean) => void;
}

export function Sidebar({
  conversations, currentId, onSelect, onNew, onDelete, onDeleteAll,
  onSearch, darkMode, setDarkMode, mobileOpen, setMobileOpen,
}: Props) {
  const [q, setQ] = useState("");
  const [menuOpen, setMenuOpen] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => { if (debounceRef.current) clearTimeout(debounceRef.current); }, []);

  const handleSearchChange = (v: string) => {
    setQ(v);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => onSearch(v), 300);
  };

  return (
    <>
      {mobileOpen && (
        <div className="fixed inset-0 bg-black/40 z-30 md:hidden" onClick={() => setMobileOpen(false)} />
      )}
      <aside className={`fixed md:static z-40 h-full w-64 border-r border-gray-200 dark:border-gray-800
                        bg-gray-50 dark:bg-gray-900 flex flex-col transition-transform
                        ${mobileOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"}`}>
        <div className="p-3 flex items-center gap-2">
          <button onClick={onNew}
                  className="flex-1 flex items-center justify-center gap-1 px-3 py-2 bg-blue-600 text-white
                             rounded-lg hover:bg-blue-700 transition text-sm">
            <Plus size={16} /> 新建对话
          </button>
          <button onClick={() => setDarkMode(!darkMode)}
                  className="p-2 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition">
            {darkMode ? <Sun size={16} /> : <Moon size={16} />}
          </button>
          <button onClick={() => setMobileOpen(false)} className="md:hidden p-2 text-gray-500">
            <X size={16} />
          </button>
        </div>

        <div className="px-3 pb-2">
          <div className="flex items-center gap-2 px-2 py-1.5 border border-gray-300 dark:border-gray-700 rounded-lg">
            <Search size={14} className="text-gray-400" />
            <input value={q} onChange={(e) => handleSearchChange(e.target.value)}
                   placeholder="搜索历史对话"
                   className="flex-1 bg-transparent outline-none text-sm" />
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-2 space-y-0.5">
          {conversations.length === 0 && (
            <div className="text-xs text-gray-400 text-center py-4">暂无历史对话</div>
          )}
          {conversations.map((c: any) => (
            <div key={c.session_id}
                 className={`group relative flex items-center rounded-lg px-2 py-1.5 cursor-pointer text-sm
                             ${currentId === c.session_id
                               ? "bg-blue-100 dark:bg-blue-900 text-blue-900 dark:text-blue-100"
                               : "hover:bg-gray-100 dark:hover:bg-gray-800"}`}>
              <span className="flex-1 truncate" onClick={() => onSelect(c.session_id)}>
                {c.title || "未命名对话"}
              </span>
              <button onClick={(e) => { e.stopPropagation();
                       setMenuOpen(menuOpen === c.session_id ? null : c.session_id); }}
                      className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-gray-600 transition">
                <MoreVertical size={14} />
              </button>
              {menuOpen === c.session_id && (
                <div className="absolute right-2 top-8 bg-white dark:bg-gray-800 border border-gray-200
                                dark:border-gray-700 rounded-lg shadow-lg z-10 text-xs">
                  <button onClick={() => { onDelete(c.session_id); setMenuOpen(null); }}
                          className="flex items-center gap-1 px-3 py-1.5 text-red-500 hover:bg-red-50 dark:hover:bg-red-950 w-full">
                    <Trash2 size={12} /> 删除
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>

        {conversations.length > 0 && (
          <button onClick={onDeleteAll}
                  className="m-2 py-1.5 text-xs text-red-500 hover:bg-red-50 dark:hover:bg-red-950 rounded-lg transition">
            删除所有对话
          </button>
        )}

        <div className="border-t border-gray-200 dark:border-gray-800 p-2 space-y-1">
          <Link href="/agent" className="flex items-center gap-2 px-2 py-1.5 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition">
            <Bot size={16} /> Agent 过程
          </Link>
          <Link href="/dashboard" className="flex items-center gap-2 px-2 py-1.5 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition">
            <BarChart3 size={16} /> 数据看板
          </Link>
          <Link href="/graph" className="flex items-center gap-2 px-2 py-1.5 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition">
            <Share2 size={16} /> 图谱可视化
          </Link>
        </div>
      </aside>
    </>
  );
}
