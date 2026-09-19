"use client";
import React, { useState, useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Copy, Check, RefreshCw, ThumbsUp, ThumbsDown, ChevronDown, ChevronRight, Wrench, Users } from "lucide-react";
import { SourceCard } from "./SourceCard";

const TOOL_LABELS: Record<string, string> = {
  search_bidding_knowledge: "已搜索知识库",
  search_knowledge_graph: "已查询知识图谱",
  search_postgresql: "已查询数据库",
  search_web: "已联网搜索",
  search_exa: "已语义搜索",
  multi_agent: "多专家协作",
};

const SPECIALIST_META: Record<string, { label: string; cls: string }> = {
  law_retrieval: { label: "法规专家", cls: "border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-950" },
  case_retrieval: { label: "案例专家", cls: "border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-950" },
  price_analysis: { label: "价格专家", cls: "border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950" },
  writing: { label: "写作专家", cls: "border-purple-200 dark:border-purple-800 bg-purple-50 dark:bg-purple-950" },
};

function ChatMessageInner({ message, userQuestion, onRegenerate, onFeedback }: any) {
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const [showThinking, setShowThinking] = useState(true);
  const [showExperts, setShowExperts] = useState(false);
  const [feedback, setFeedback] = useState<"up" | "down" | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current); }, []);

  const copy = async () => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(message.content);
      } else {
        throw new Error("no clipboard");
      }
      setCopied(true);
      timerRef.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      try {
        const ta = document.createElement("textarea");
        ta.value = message.content;
        ta.style.position = "fixed"; ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select(); document.execCommand("copy");
        document.body.removeChild(ta);
        setCopied(true);
        timerRef.current = setTimeout(() => setCopied(false), 2000);
      } catch {
        setCopyFailed(true);
        timerRef.current = setTimeout(() => setCopyFailed(false), 2000);
      }
    }
  };

  const handleFeedback = (rating: "up" | "down") => {
    setFeedback(rating);
    onFeedback?.(userQuestion, message.content, rating);
  };

  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-2xl">
          {message.image && (
            <img src={`data:image/jpeg;base64,${message.image}`} alt=""
                 className="max-w-xs rounded-lg mb-1 ml-auto" />
          )}
          <div className="bg-blue-600 text-white rounded-2xl px-4 py-2 text-sm whitespace-pre-wrap">
            {message.content}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start">
      <div className="max-w-3xl w-full">
        {message.toolName && (
          <div className="inline-flex items-center gap-1 text-xs text-gray-500 bg-gray-100 dark:bg-gray-800 rounded-full px-2 py-0.5 mb-1">
            {message.toolName === "multi_agent" ? <Users size={12} /> : <Wrench size={12} />}
            {TOOL_LABELS[message.toolName] || "已搜索知识库"}
          </div>
        )}

        {message.multiAgent && (
          <div className="border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/40 rounded-lg mb-2 text-sm overflow-hidden">
            <button onClick={() => setShowExperts(!showExperts)}
                    className="w-full flex items-center gap-1 px-3 py-1.5 text-amber-700 dark:text-amber-300 hover:bg-amber-100 dark:hover:bg-amber-900/50 transition">
              {showExperts ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              <Users size={14} />
              多专家协作过程
              <span className="flex items-center gap-1 ml-1">
                {(message.multiAgent.planSpecialists || []).map((s: string) => (
                  <span key={s} className="text-[11px] bg-amber-200/70 dark:bg-amber-900 rounded-full px-1.5 py-0.5">
                    {SPECIALIST_META[
                      s === "LAW" ? "law_retrieval" : s === "CASE" ? "case_retrieval"
                      : s === "PRICE" ? "price_analysis" : s]?.label || s}
                  </span>
                ))}
              </span>
            </button>
            {showExperts && (
              <div className="px-3 py-2 space-y-2 border-t border-amber-200 dark:border-amber-800">
                {(message.multiAgent.expertResults || []).map((e: any, i: number) => {
                  const meta = SPECIALIST_META[e.role] || { label: e.role, cls: "border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900" };
                  return (
                    <div key={`${e.role}-${i}`} className={`border rounded-lg p-2 text-xs ${meta.cls}`}>
                      <div className="flex items-center gap-2 mb-1 font-medium">
                        {meta.label}
                        {e.rounds != null && <span className="text-gray-500">· {e.rounds} 轮</span>}
                        {e.elapsed_ms != null && <span className="text-gray-500">· {(e.elapsed_ms / 1000).toFixed(1)}s</span>}
                      </div>
                      <div className="text-gray-700 dark:text-gray-300 whitespace-pre-wrap max-h-40 overflow-y-auto">
                        {e.answer || "（该专家无输出）"}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {message.thinking && (
          <div className="border border-purple-200 dark:border-purple-800 bg-purple-50 dark:bg-purple-950 rounded-lg mb-2 text-sm overflow-hidden">
            <button onClick={() => setShowThinking(!showThinking)}
                    className="w-full flex items-center gap-1 px-3 py-1.5 text-purple-700 dark:text-purple-300 hover:bg-purple-100 dark:hover:bg-purple-900 transition">
              {showThinking ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              思考过程
            </button>
            {showThinking && (
              <div className="px-3 py-2 text-purple-900 dark:text-purple-200 whitespace-pre-wrap text-xs border-t border-purple-200 dark:border-purple-800">
                {message.thinking}
              </div>
            )}
          </div>
        )}

        <div className="prose prose-sm dark:prose-invert max-w-none text-sm">
          <ReactMarkdown remarkPlugins={[remarkGfm]}
            components={{
              a: ({ node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
              table: ({ node, ...props }) => (<div className="overflow-x-auto"><table {...props} /></div>),
            }}>
            {message.content}
          </ReactMarkdown>
        </div>

        {message.sources?.length > 0 && (
          <div className="mt-2 space-y-1">
            {message.sources.map((s: any, i: number) => (
              <SourceCard key={`${s.question}|${s.url || ""}|${i}`} source={s} />
            ))}
          </div>
        )}

        {!message.pending && (
          <div className="flex items-center gap-3 mt-2 text-gray-400">
            <button onClick={copy} title="复制"
                    className="hover:text-gray-600 transition flex items-center gap-1 text-xs">
              {copied ? <Check size={14} className="text-green-500" /> : <Copy size={14} />}
              {copied ? "已复制" : copyFailed ? "复制失败" : ""}
            </button>
            <button onClick={onRegenerate} title="重新生成" className="hover:text-gray-600 transition">
              <RefreshCw size={14} />
            </button>
            <button onClick={() => handleFeedback("up")} title="满意"
                    className={`transition ${feedback === "up" ? "text-green-500" : "hover:text-gray-600"}`}>
              <ThumbsUp size={14} />
            </button>
            <button onClick={() => handleFeedback("down")} title="不满意"
                    className={`transition ${feedback === "down" ? "text-red-500" : "hover:text-gray-600"}`}>
              <ThumbsDown size={14} />
            </button>
            {message.elapsedMs != null && (
              <span className="text-xs ml-auto">{(message.elapsedMs / 1000).toFixed(1)}s</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export const ChatMessage = React.memo(ChatMessageInner);
