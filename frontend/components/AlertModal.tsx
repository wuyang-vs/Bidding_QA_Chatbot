"use client";

/**
 * 检测结果主动预警弹窗 (R17)
 * 检测完成后发现不合格/风险项时主动弹出, 列出摘要, 支持"查看详情"跳转到结果面板。
 */
import { AlertTriangle, X } from "lucide-react";

export type AlertPayload = {
  level: "high" | "medium";
  title: string;
  docId?: number;
  items: string[];
  targetId?: string;
};

const MAX_ITEMS = 5;

export default function AlertModal({
  alert,
  onClose,
  onDetail,
}: {
  alert: AlertPayload;
  onClose: () => void;
  onDetail?: () => void;
}) {
  const high = alert.level === "high";
  const shown = alert.items.slice(0, MAX_ITEMS);
  const rest = alert.items.length - shown.length;
  return (
    <div className="fixed inset-0 bg-black/40 z-[60] flex items-center justify-center p-4" onClick={onClose}>
      <div
        className={`bg-white dark:bg-gray-900 rounded-xl max-w-lg w-full p-5 border-t-4 ${
          high ? "border-red-500" : "border-amber-400"
        }`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-3">
          <h3 className={`font-medium flex items-center gap-2 ${high ? "text-red-600 dark:text-red-400" : "text-amber-600 dark:text-amber-400"}`}>
            <AlertTriangle size={18} />
            {high ? "发现不合格项，请及时处理" : "检测发现风险项"}
          </h3>
          <button onClick={onClose} className="p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded">
            <X size={18} />
          </button>
        </div>
        <div className="space-y-3 text-sm">
          <div className={`text-xs px-3 py-2 rounded-lg ${high ? "bg-red-50 dark:bg-red-950/30 text-red-700 dark:text-red-300" : "bg-amber-50 dark:bg-amber-950/30 text-amber-700 dark:text-amber-300"}`}>
            <b>{alert.title}</b>
            {alert.docId != null && <span className="ml-2 opacity-70">文档 #{alert.docId}</span>}
            <span className="ml-2 opacity-70">共 {alert.items.length} 项</span>
          </div>
          <ul className="space-y-1.5 max-h-56 overflow-y-auto">
            {shown.map((it, i) => (
              <li key={i} className="text-xs text-gray-700 dark:text-gray-200 flex gap-2">
                <span className={high ? "text-red-500" : "text-amber-500"}>•</span>
                <span className="break-all">{it}</span>
              </li>
            ))}
          </ul>
          {rest > 0 && (
            <p className="text-xs text-gray-400">…等共 {alert.items.length} 项，详情见检测结果面板</p>
          )}
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={onClose}
            className="px-4 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition">
            知道了
          </button>
          {onDetail && (
            <button onClick={() => { onClose(); onDetail(); }}
              className={`px-4 py-2 text-sm text-white rounded-lg transition ${
                high ? "bg-red-600 hover:bg-red-700" : "bg-amber-500 hover:bg-amber-600"
              }`}>
              查看详情
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
