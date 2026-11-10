"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { Bot, LoaderCircle, Menu, Plus, Send, Trash2 } from "lucide-react";
import { sendChatMessage, ChatApiError } from "@/lib/chat-api";
import type { ResearchSession, ChatMessage, AgentTraceEvent } from "@/app/types";

interface ChatInterfaceProps {
  sessions: ResearchSession[];
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onCreateSession: () => void;
  onDeleteSession: (id: string) => void;
  onRenameSession: (id: string, title: string) => void;
  onUpdateMessages: (id: string, messages: ChatMessage[]) => void;
}

export function ChatInterface({
  sessions,
  activeSessionId,
  onSelectSession,
  onCreateSession,
  onDeleteSession,
  onRenameSession,
  onUpdateMessages,
}: ChatInterfaceProps) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [progress, setProgress] = useState<AgentTraceEvent[]>([]);
  const [pendingSessionId, setPendingSessionId] = useState<string | null>(null);
  const [mobileSessions, setMobileSessions] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  const activeSession =
    sessions.find((session) => session.id === activeSessionId) ?? null;
  const currentProgress = progress.at(-1);
  const isActivePending = loading && pendingSessionId === activeSessionId;

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activeSession?.messages, loading, progress]);

  async function submitMessage(event: FormEvent) {
    event.preventDefault();
    const content = input.trim();
    if (!content || !activeSession || loading) return;

    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content,
      createdAt: new Date().toISOString(),
    };
    const nextMessages = [...activeSession.messages, userMessage];
    onUpdateMessages(activeSession.id, nextMessages);
    setInput("");
    setLoading(true);
    setError("");
    setProgress([]);
    setPendingSessionId(activeSession.id);

    try {
      const response = await sendChatMessage(
        { session_id: activeSession.threadId, message: content },
        nextMessages,
        (event) => setProgress((events) => [...events, event]),
      );
      const assistantMessage: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: response.reply,
        createdAt: new Date().toISOString(),
        trace: response.trace,
        status: response.status,
        mode: response.mode,
      };
      onUpdateMessages(activeSession.id, [...nextMessages, assistantMessage]);
    } catch (caught) {
      setError(
        caught instanceof ChatApiError
          ? caught.message
          : "An unexpected error occurred while contacting the agent.",
      );
    } finally {
      setLoading(false);
    }
  }

  function renameSession(session: ResearchSession) {
    const title = window.prompt("Rename research session", session.title)?.trim();
    if (title) onRenameSession(session.id, title);
  }

  const sessionList = (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-white/[0.06] px-4 py-4">
        <span className="text-xs uppercase tracking-[0.16em] text-white/40">Sessions</span>
        <button
          onClick={onCreateSession}
          aria-label="Create research session"
          className="flex size-8 items-center justify-center rounded-lg bg-[#d0ab61] text-[#17140d] transition hover:bg-[#e0c279]"
        >
          <Plus size={16} />
        </button>
      </div>
      <div className="flex-1 space-y-1 overflow-y-auto p-2">
        {sessions.length === 0 ? (
          <div className="px-3 py-8 text-center text-xs text-white/35">No research sessions</div>
        ) : (
          sessions.map((session) => (
            <div
              key={session.id}
              className={`group flex items-center rounded-lg border transition ${
                session.id === activeSessionId
                  ? "border-[#d3b268]/20 bg-[#d3b268]/[0.08]"
                  : "border-transparent hover:bg-white/[0.035]"
              }`}
            >
              <button
                onClick={() => {
                  onSelectSession(session.id);
                  setMobileSessions(false);
                }}
                className="min-w-0 flex-1 px-3 py-3 text-left"
              >
                <div className="truncate text-sm text-white/75">{session.title}</div>
                <div className="mt-1 text-[10px] text-white/30">
                  {session.messages.length} messages
                </div>
              </button>
              <button
                onClick={() => renameSession(session)}
                className="mr-1 hidden rounded px-1.5 py-2 text-[10px] text-white/35 group-hover:block hover:text-[#d8bc74]"
                aria-label={`Rename ${session.title}`}
              >
                Edit
              </button>
              <button
                onClick={() => onDeleteSession(session.id)}
                className="mr-2 hidden rounded p-1.5 text-white/25 group-hover:block hover:bg-rose-400/10 hover:text-rose-400"
                aria-label={`Delete ${session.title}`}
              >
                <Trash2 size={13} />
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );

  return (
    <div className="flex h-[calc(100vh-124px)] min-h-[520px] overflow-hidden rounded-xl border border-white/[0.07] bg-[#111111] lg:h-[calc(100vh-150px)]">
      <div className="hidden w-[220px] border-r border-white/[0.06] md:block">{sessionList}</div>

      {mobileSessions && (
        <div className="absolute inset-x-3 top-[112px] z-40 h-[360px] rounded-xl border border-white/[0.1] bg-[#111111] shadow-2xl md:hidden">
          {sessionList}
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-[61px] items-center justify-between border-b border-white/[0.06] px-4 sm:px-5">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <button onClick={() => setMobileSessions((value) => !value)} className="text-white/50 md:hidden">
                <Menu size={18} />
              </button>
              <h1 className="truncate text-sm font-medium text-white/85">
                {activeSession?.title ?? "Agent Chat"}
              </h1>
            </div>
            <div className="mt-1 flex items-center gap-1.5 text-[10px] text-white/30">
              <span className={`size-1.5 rounded-full ${loading ? "animate-pulse bg-[#d0ab61]" : "bg-white/30"}`} />
              {loading
                ? `${currentProgress?.agent === "a2a" ? "A2A" : currentProgress?.agent === "validation" ? "Validation Agent" : "Research Agent"} · ${currentProgress?.stage ?? "connecting"}`
                : "Research + Validation · synthetic research demo"}
            </div>
          </div>
          {activeSession && (
            <button onClick={() => renameSession(activeSession)} className="rounded-md border border-white/[0.08] px-3 py-1.5 text-xs text-white/45 hover:text-white/75">
              Rename
            </button>
          )}
        </header>

        <div className="flex-1 overflow-y-auto px-4 py-5 sm:px-6">
          {!activeSession ? (
            <div className="flex h-full items-center justify-center text-sm text-white/35">Create a session to begin</div>
          ) : activeSession.messages.length === 0 ? (
            <div className="mx-auto flex h-full max-w-md flex-col items-center justify-center text-center">
              <div className="flex size-12 items-center justify-center rounded-xl border border-[#d1af66]/20 bg-[#d1af66]/[0.07] text-[#d7ba70]">
                <Bot size={21} />
              </div>
              <h2 className="mt-4 text-sm font-medium text-white/80">Start a research brief</h2>
              <p className="mt-2 text-xs leading-5 text-white/35">Ask about volatility, trends, catalysts, or prepare a backtest hypothesis.</p>
              <div className="mt-5 flex flex-wrap justify-center gap-2">
                {["Analyze gold volatility this week", "Summarize the XAU/USD trend", "Prepare a backtest"].map((prompt) => (
                  <button key={prompt} onClick={() => setInput(prompt)} className="rounded-full border border-white/[0.08] px-3 py-2 text-[11px] text-white/45 hover:border-[#d0ad62]/30 hover:text-[#dcc487]">
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="mx-auto max-w-3xl space-y-5">
              {activeSession.messages.map((message) => (
                <div key={message.id} className={`flex gap-3 ${message.role === "user" ? "justify-end" : ""}`}>
                  {message.role === "assistant" && (
                    <div className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-[#d1af66]/20 bg-[#d1af66]/[0.07] text-[#d7ba70]">
                      <Bot size={15} />
                    </div>
                  )}
                  <div className={`max-w-[82%] rounded-xl px-4 py-3 text-sm leading-6 ${
                    message.role === "user"
                      ? "bg-[#cbaa62] text-[#17140d]"
                      : "border border-white/[0.06] bg-white/[0.025] text-white/70"
                  }`}>
                    {message.role === "assistant" ? (
                      <>
                        {message.mode && <div className="mb-2 text-[10px] uppercase tracking-wider text-[#d7ba70]">{message.mode === "mock" ? "Deterministic demo" : "LLM assisted"} · Synthetic evidence</div>}
                        <div className="markdown"><ReactMarkdown>{message.content}</ReactMarkdown></div>
                        {message.trace && (
                          <details className="mt-4 border-t border-white/[0.08] pt-3 text-xs text-white/45">
                            <summary className="cursor-pointer text-[#d7ba70]">A2A trace · {message.status === "validation_unavailable" ? "validation unavailable" : "completed"}</summary>
                            <ol className="mt-2 space-y-2">
                              {message.trace.map((event, index) => (
                                <li key={index} className="break-words">
                                  <span className="text-white/65">{event.agent.toUpperCase()} · {event.stage}</span> — {event.detail}
                                  <div className="text-[10px] text-white/30">{event.timestamp}{event.message_id ? ` · message ${event.message_id}` : ""}</div>
                                </li>
                              ))}
                            </ol>
                          </details>
                        )}
                      </>
                    ) : message.content}
                  </div>
                </div>
              ))}
              {isActivePending && (
                <div className="flex gap-3">
                  <div className="flex size-8 items-center justify-center rounded-lg border border-[#d1af66]/20 bg-[#d1af66]/[0.07] text-[#d7ba70]">
                    <LoaderCircle size={15} className="animate-spin" />
                  </div>
                  <div role="status" aria-live="polite" className="rounded-xl border border-white/[0.06] bg-white/[0.025] px-4 py-3 text-xs text-white/40">{currentProgress?.detail ?? "Connecting to Research Agent..."}</div>
                </div>
              )}
              <div ref={endRef} />
            </div>
          )}
        </div>

        {error && pendingSessionId === activeSessionId && (
          <div className="mx-4 mb-2 rounded-lg border border-rose-400/20 bg-rose-400/[0.07] px-3 py-2 text-xs text-rose-300 sm:mx-6">
            {error}
          </div>
        )}
        <form onSubmit={submitMessage} className="border-t border-white/[0.06] p-3 sm:p-4">
          <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-xl border border-white/[0.08] bg-[#0d0d0d] p-2 focus-within:border-[#cdaa62]/35">
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              rows={1}
              maxLength={4000}
              aria-label="Research question"
              placeholder="Ask the research agent..."
              className="max-h-32 min-h-9 flex-1 resize-none bg-transparent px-2 py-2 text-sm text-white/80 outline-none placeholder:text-white/25"
              disabled={!activeSession || loading}
            />
            <button
              type="submit"
              disabled={!activeSession || !input.trim() || loading}
              className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-[#cdaa62] text-[#17140d] disabled:cursor-not-allowed disabled:opacity-35"
            >
              <Send size={15} />
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
