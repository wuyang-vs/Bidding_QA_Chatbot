"use client";
import { useEffect, useRef } from "react";
import { ChatMessage } from "./ChatMessage";

interface Props {
  messages: any[];
  loading: boolean;
  examples: string[];
  onExampleClick: (q: string) => void;
  onRegenerate: () => void;
  onFeedback: (question: string, answer: string, rating: string) => void;
}

export function ChatContainer({
  messages, loading, examples, onExampleClick, onRegenerate, onFeedback,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const nearBottomRef = useRef(true);

  const onScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    nearBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };

  useEffect(() => {
    const el = containerRef.current;
    if (!el || !nearBottomRef.current) return;
    const streaming = messages.some((m) => m.pending);
    el.scrollTo({ top: el.scrollHeight, behavior: streaming ? "auto" : "smooth" });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="flex-1 overflow-y-auto p-8">
        <div className="max-w-2xl mx-auto text-center mt-20">
          <h1 className="text-2xl font-semibold mb-2">招投标智能问答</h1>
          <p className="text-gray-500 text-sm mb-8">基于知识库、知识图谱、结构化数据库与联网搜索</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {examples.map((q) => (
              <button key={q} onClick={() => onExampleClick(q)}
                      className="text-left px-4 py-3 border border-gray-200 dark:border-gray-700 rounded-xl
                                 text-sm hover:bg-gray-50 dark:hover:bg-gray-800 transition">
                {q}
              </button>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div ref={containerRef} onScroll={onScroll} className="flex-1 overflow-y-auto px-4 py-6">
      <div className="max-w-3xl mx-auto space-y-6">
        {messages.map((m, idx) => {
          let userQuestion = "";
          if (m.role === "assistant") {
            for (let i = idx - 1; i >= 0; i--) {
              if (messages[i].role === "user") {
                userQuestion = messages[i].content || messages[i].imageName || "";
                break;
              }
            }
          }
          return (
            <ChatMessage key={m.id || idx} message={m}
                         userQuestion={userQuestion}
                         onRegenerate={onRegenerate}
                         onFeedback={onFeedback} />
          );
        })}
      </div>
    </div>
  );
}
