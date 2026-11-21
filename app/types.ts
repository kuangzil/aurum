export interface GoldSnapshot {
  price: string;
  source: string;
  quoted_at_utc: string;
  observed_hour_utc: string;
  is_stale: boolean;
}

export interface GoldHistoryResponse {
  snapshots: GoldSnapshot[];
}

export interface AgentTraceEvent {
  timestamp: string;
  agent: "research" | "validation" | "a2a";
  stage: string;
  detail: string;
  message_id?: string | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
  trace?: AgentTraceEvent[];
  status?: "queued" | "running" | "waiting_review" | "blocked" | "completed";
  mode?: "mock" | "openai";
}

export interface ResearchSession {
  id: string;
  title: string;
  threadId: string;
  createdAt: string;
  updatedAt: string;
  messages: ChatMessage[];
}
