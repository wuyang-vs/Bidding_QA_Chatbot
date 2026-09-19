const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8001";

export interface Source {
  question: string;
  answer: string;
  score: number;
  url?: string;
}

export interface ExpertResult {
  role: string;
  answer: string;
  tool_called?: boolean;
  tool_name?: string;
  rounds?: number;
  elapsed_ms?: number;
}

export interface MultiAgentPanel {
  planSpecialists: string[];
  expertResults: ExpertResult[];
  specialistsCount: number;
}

export interface PersistedMessage {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  toolCalled?: boolean;
  toolName?: string;
  image?: string;
  imageName?: string;
  multiAgent?: MultiAgentPanel;
}

export function toPersistedMessage(raw: any): PersistedMessage | null {
  if (!raw || typeof raw !== "object") return null;
  if (raw.role !== "user" && raw.role !== "assistant") return null;
  if (typeof raw.content !== "string") return null;
  const out: PersistedMessage = { role: raw.role, content: raw.content };
  if (Array.isArray(raw.sources)) {
    out.sources = raw.sources.filter(
      (s: any) => s && typeof s.question === "string" && typeof s.answer === "string"
    );
  }
  if (typeof raw.toolCalled === "boolean") out.toolCalled = raw.toolCalled;
  if (typeof raw.toolName === "string") out.toolName = raw.toolName;
  if (typeof raw.image === "string") out.image = raw.image;
  if (typeof raw.imageName === "string") out.imageName = raw.imageName;
  if (raw.multiAgent && Array.isArray(raw.multiAgent.expertResults)
      && Array.isArray(raw.multiAgent.planSpecialists)) {
    out.multiAgent = {
      planSpecialists: raw.multiAgent.planSpecialists.filter((x: any) => typeof x === "string"),
      expertResults: raw.multiAgent.expertResults
        .filter((x: any) => x && typeof x.role === "string" && typeof x.answer === "string")
        .map((x: any) => ({ role: x.role, answer: x.answer,
                           tool_called: x.tool_called, tool_name: x.tool_name,
                           rounds: x.rounds, elapsed_ms: x.elapsed_ms })),
      specialistsCount: Number(raw.multiAgent.specialistsCount) || 0,
    };
  }
  return out;
}

function mapError(err: any): Error {
  if (err?.name === "AbortError") return err;
  if (err?.message?.includes("Failed to fetch") || err?.message?.includes("NetworkError")) {
    return new Error("网络连接中断，请检查后端服务");
  }
  return err;
}

export async function fetchAPI(path: string, init?: RequestInit) {
  try {
    const resp = await fetch(`${API_BASE}${path}`, init);
    if (!resp.ok) {
      const detail = await resp.json().catch(() => ({}));
      throw new Error(detail.detail || `请求失败 (${resp.status})`);
    }
    return resp.json();
  } catch (e) {
    throw mapError(e);
  }
}

export async function chatWithAgentStream(
  body: any,
  onEvent: (type: string, data: any) => void,
  signal?: AbortSignal,
) {
  const resp = await fetch(`${API_BASE}/api/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}));
    throw new Error(detail.detail || `请求失败 (${resp.status})`);
  }
  const reader = resp.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith("data: ")) continue;
      const payload = trimmed.slice(6);
      if (payload === "[DONE]") continue;
      try {
        const data = JSON.parse(payload);
        onEvent(data.type, data);
      } catch (e) {
        console.warn("SSE 行解析失败:", payload);
      }
    }
  }
}

export async function runMultiAgent(body: {
  question: string;
  provider?: string;
  deep_thinking?: boolean;
}, signal?: AbortSignal): Promise<any> {
  const resp = await fetch(`${API_BASE}/api/multi-agent/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}));
    throw new Error(detail.detail || `请求失败 (${resp.status})`);
  }
  return resp.json();
}

export async function saveConversation(sessionId: string, title: string, messages: PersistedMessage[]) {
  return fetchAPI("/api/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, title, messages }),
  });
}

export async function listConversations(q = "") {
  return fetchAPI(`/api/conversations${q ? `?q=${encodeURIComponent(q)}` : ""}`);
}

export async function loadConversation(sessionId: string) {
  return fetchAPI(`/api/conversations/${sessionId}`);
}

export async function deleteConversation(sessionId: string) {
  return fetchAPI(`/api/conversations/${sessionId}`, { method: "DELETE" });
}

export async function saveFeedback(body: {
  session_id: string; question: string; answer: string; rating: string;
}) {
  return fetchAPI("/api/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
