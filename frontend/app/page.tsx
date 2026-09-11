"use client";
import { useEffect, useRef, useState, useCallback } from "react";
import { Menu } from "lucide-react";
import { ChatContainer } from "@/components/ChatContainer";
import { ChatInput } from "@/components/ChatInput";
import { Sidebar } from "@/components/Sidebar";
import {
  chatWithAgentStream, saveConversation, listConversations,
  loadConversation, deleteConversation, saveFeedback, toPersistedMessage,
} from "@/lib/api";

function generateId(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return Date.now().toString(36) + Math.random().toString(36).slice(2);
}

const EXAMPLES = [
  "什么是单一来源采购？",
  "有哪些关于空调的采购？",
  "采购最多的标的是什么？",
  "空调的供应商和采购人有哪些？",
  "对比中国大陆和香港招投标流程法规",
  "知识图谱中有多少数据？",
];

export default function Page() {
  const [messages, setMessages] = useState<any[]>([]);
  const [conversations, setConversations] = useState<any[]>([]);
  const [sessionId, setSessionId] = useState("");
  const [loading, setLoading] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  const [darkMode, setDarkMode] = useState(() => {
    if (typeof window === "undefined") return false;
    const saved = localStorage.getItem("chat_dark_mode");
    if (saved !== null) return saved === "1";
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  });
  const [webSearch, setWebSearch] = useState(() =>
    typeof window !== "undefined" && localStorage.getItem("chat_web_search") === "1");
  const [deepThinking, setDeepThinking] = useState(() =>
    typeof window !== "undefined" && localStorage.getItem("chat_deep_thinking") === "1");
  const [provider, setProvider] = useState(() =>
    (typeof window !== "undefined" && localStorage.getItem("chat_llm_provider")) || "deepseek");

  const abortRef = useRef<AbortController | null>(null);
  const requestSeqRef = useRef(0);
  const sessionIdRef = useRef(sessionId);
  const messagesRef = useRef(messages);
  sessionIdRef.current = sessionId;
  messagesRef.current = messages;

  useEffect(() => { localStorage.setItem("chat_dark_mode", darkMode ? "1" : "0"); }, [darkMode]);
  useEffect(() => { localStorage.setItem("chat_web_search", webSearch ? "1" : "0"); }, [webSearch]);
  useEffect(() => { localStorage.setItem("chat_deep_thinking", deepThinking ? "1" : "0"); }, [deepThinking]);
  useEffect(() => { localStorage.setItem("chat_llm_provider", provider); }, [provider]);

  useEffect(() => {
    listConversations().then((list: any) => setConversations(list)).catch(() => {});
  }, []);

  const persistConversation = useCallback(
    async (sid: string, msgs: any[], title: string) => {
      const persisted = msgs.map(toPersistedMessage).filter(Boolean);
      try {
        await saveConversation(sid, title, persisted as any);
        const list = await listConversations();
        setConversations(list);
      } catch {
        console.warn("会话保存失败，请检查数据库连接");
      }
    }, []);

  const handleSend = useCallback(
    async (content: string, image?: { base64: string; name: string }) => {
      if (loading) return;
      const seq = ++requestSeqRef.current;
      const sendSessionId = sessionIdRef.current;
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      const isVision = Boolean(image) && !content;
      const question = content || "请分析这张图片";

      const userMsg = { id: generateId(), role: "user", content,
                        image: image?.base64, imageName: image?.name };
      const thinkingMsg = { id: generateId(), role: "assistant", content: "", pending: true };

      let sid = sendSessionId;
      if (!sid) {
        sid = generateId();
        setSessionId(sid);
        sessionIdRef.current = sid;
      }

      setMessages((prev) => [...prev, userMsg, thinkingMsg]);
      setLoading(true);

      let streamedContent = "";
      let answer = "";
      let thinking = "";
      let sources: any[] = [];
      let webSources: any[] = [];
      let toolName = "";
      let elapsedMs: number | undefined;

      try {
        if (isVision) {
          const resp = await fetch("http://localhost:8001/api/vision", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ image_base64: image!.base64 }),
            signal: controller.signal,
          });
          if (!resp.ok) throw new Error((await resp.json()).detail || "图片解析失败");
          const data = await resp.json();
          answer = data.analysis;
          streamedContent = answer;
        } else {
          await chatWithAgentStream(
            {
              question,
              history: messagesRef.current.slice(-10).map((m) => ({ role: m.role, content: m.content })),
              web_search_enabled: webSearch,
              provider,
              deep_thinking_enabled: deepThinking,
            },
            (type, data) => {
              if (seq !== requestSeqRef.current) return;
              if (type === "status") {
                setMessages((prev) => prev.map((m) =>
                  m.id === thinkingMsg.id ? { ...m, content: data.content } : m));
              } else if (type === "token") {
                streamedContent += data.content;
                setMessages((prev) => prev.map((m) =>
                  m.id === thinkingMsg.id ? { ...m, content: streamedContent, pending: true } : m));
              } else if (type === "thinking") {
                thinking += data.content;
                setMessages((prev) => prev.map((m) =>
                  m.id === thinkingMsg.id ? { ...m, thinking } : m));
              } else if (type === "reset") {
                streamedContent = "";
                setMessages((prev) => prev.map((m) =>
                  m.id === thinkingMsg.id ? { ...m, content: "" } : m));
              } else if (type === "done") {
                sources = data.sources || [];
                webSources = data.web_sources || [];
                toolName = data.tool_name || "";
                elapsedMs = data.elapsed_ms;
              } else if (type === "error") {
                answer = data.content;
                streamedContent = data.content;
              }
            },
            controller.signal,
          );
          if (!answer) answer = streamedContent;
          if (!answer) answer = "连接中断，请重试。";
        }
      } catch (e: any) {
        if (e.name === "AbortError") return;
        answer = streamedContent ? streamedContent + "\n\n> ⚠️ 回答可能不完整" : "连接中断，请重试。";
      }

      const finalMsg = {
        id: thinkingMsg.id, role: "assistant", content: answer,
        sources: [...sources, ...webSources], toolName,
        thinking: thinking || undefined, pending: false, elapsedMs,
      };

      const currentMsgs = messagesRef.current.filter(
        (m) => m.id !== userMsg.id && m.id !== thinkingMsg.id);
      const finalList = [...currentMsgs, userMsg, finalMsg];
      setMessages(finalList);

      const title = content || (image?.name ? `图片: ${image.name}` : "图片分析");
      persistConversation(sid, finalList, title);

      if (seq === requestSeqRef.current) setLoading(false);
    },
    [loading, webSearch, provider, deepThinking, persistConversation],
  );

  const handleRegenerate = useCallback(() => {
    const msgs = messagesRef.current;
    const lastUser = [...msgs].reverse().find((m) => m.role === "user");
    if (!lastUser) return;
    const idx = msgs.lastIndexOf(lastUser);
    setMessages(msgs.slice(0, idx));
    const img = lastUser.image ? { base64: lastUser.image, name: lastUser.imageName } : undefined;
    setTimeout(() => handleSend(lastUser.content, img), 0);
  }, [handleSend]);

  const onSelectConversation = async (sid: string) => {
    abortRef.current?.abort();
    setMobileOpen(false);
    setSessionId(sid);
    sessionIdRef.current = sid;
    try {
      const data = await loadConversation(sid);
      const msgs = (data.messages || [])
        .map((m: any) => {
          const p = toPersistedMessage(m);
          return p ? { ...p, id: generateId() } : null;
        }).filter(Boolean);
      setMessages(msgs);
    } catch {
      setMessages([]);
    }
  };

  const onNew = () => {
    abortRef.current?.abort();
    const sid = generateId();
    setSessionId(sid);
    sessionIdRef.current = sid;
    setMessages([]);
    setMobileOpen(false);
  };

  const onDelete = async (sid: string) => {
    try {
      await deleteConversation(sid);
      setConversations((prev) => prev.filter((c) => c.session_id !== sid));
      if (sid === sessionIdRef.current) onNew();
    } catch { console.warn("删除失败"); }
  };

  const onDeleteAll = async () => {
    if (!confirm("确定删除所有对话？")) return;
    try {
      await fetch("http://localhost:8001/api/conversations", { method: "DELETE" });
      setConversations([]);
      onNew();
    } catch { console.warn("删除失败"); }
  };

  const onFeedback = useCallback((question: string, answer: string, rating: string) => {
    saveFeedback({ session_id: sessionIdRef.current, question, answer, rating }).catch(() => {});
  }, []);

  const onSearch = useCallback((q: string) => {
    listConversations(q).then((l: any) => setConversations(l)).catch(() => {});
  }, []);

  return (
    <div className={darkMode ? "dark" : ""}>
      <div className="flex h-screen bg-white dark:bg-gray-950 text-gray-900 dark:text-gray-100">
        <Sidebar conversations={conversations} currentId={sessionId}
                 onSelect={onSelectConversation} onNew={onNew}
                 onDelete={onDelete} onDeleteAll={onDeleteAll} onSearch={onSearch}
                 darkMode={darkMode} setDarkMode={setDarkMode}
                 mobileOpen={mobileOpen} setMobileOpen={setMobileOpen} />

        <main className="flex-1 flex flex-col min-w-0">
          <header className="h-12 px-3 border-b border-gray-200 dark:border-gray-800 flex items-center gap-2">
            <button onClick={() => setMobileOpen(true)} className="md:hidden p-1.5 text-gray-500">
              <Menu size={18} />
            </button>
            <div className="flex-1" />
            <select value={provider} onChange={(e) => setProvider(e.target.value)}
                    className="border border-gray-300 dark:border-gray-700 rounded-lg px-2 py-1 text-xs bg-white dark:bg-gray-800">
              <option value="deepseek">DeepSeek</option>
              <option value="zhipu">智谱AI</option>
              <option value="vllm">vLLM</option>
              <option value="ollama">Ollama</option>
            </select>
          </header>

          <ChatContainer messages={messages} loading={loading} examples={EXAMPLES}
                         onExampleClick={(q) => handleSend(q)}
                         onRegenerate={handleRegenerate}
                         onFeedback={onFeedback} />

          <div className="p-3 md:p-4">
            <div className="max-w-3xl mx-auto">
              <ChatInput onSend={handleSend} webSearch={webSearch} setWebSearch={setWebSearch}
                         deepThinking={deepThinking} setDeepThinking={setDeepThinking}
                         loading={loading} />
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
