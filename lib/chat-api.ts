import type { AgentTraceEvent, ChatMessage } from "@/app/types";

export interface ChatRequest {
  session_id: string;
  message: string;
}

export interface ChatResponse {
  session_id: string;
  reply: string;
  status: "completed" | "validation_unavailable";
  mode: "mock" | "openai";
  trace: AgentTraceEvent[];
}

export class ChatApiError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ChatApiError";
  }
}

export async function sendChatMessage(
  request: ChatRequest,
  history: ChatMessage[] = [],
  onProgress?: (event: AgentTraceEvent) => void,
): Promise<ChatResponse> {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: onProgress ? "application/x-ndjson" : "application/json",
    },
    body: JSON.stringify({ ...request, history }),
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new ChatApiError(
      payload?.error || "The research agent could not complete this request.",
    );
  }

  if (!response.headers.get("content-type")?.includes("application/x-ndjson")) {
    return response.json();
  }
  if (!response.body) throw new ChatApiError("The research stream was empty.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: ChatResponse | undefined;

  function consume(line: string) {
    if (!line.trim()) return;
    const event = JSON.parse(line);
    if (event.type === "progress") onProgress?.(event.event);
    if (event.type === "result") result = event.result;
    if (event.type === "error") throw new ChatApiError(event.error);
  }

  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) consume(line);
      if (done) break;
    }
    consume(buffer);
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
  if (!result) throw new ChatApiError("The research connection ended before a final result. Please retry.");
  return result;
}
