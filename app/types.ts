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
  status?: "completed" | "validation_unavailable";
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
