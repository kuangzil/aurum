"use client";

import { useEffect, useState } from "react";
import { Bot, FlaskConical, LayoutDashboard, Settings, Waypoints } from "lucide-react";
import { Sidebar, type View } from "@/components/Sidebar";
import { Dashboard } from "@/components/Dashboard";
import { ChatInterface } from "@/components/ChatInterface";
import { ResearchSessions } from "@/components/ResearchSessions";
import { PlaceholderView } from "@/components/PlaceholderView";
import type { ChatMessage, ResearchSession } from "@/app/types";

const STORAGE_KEY = "aurum-research-sessions-v1";

function createSession(title = "New gold research"): ResearchSession {
  const id = crypto.randomUUID();
  return {
    id,
    title,
    threadId: `thread_${id}`,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    messages: [],
  };
}

function initialSessions(): ResearchSession[] {
  const first = createSession("XAU/USD volatility brief");
  const second = createSession("Macro catalyst scan");
  const now = Date.now();
  first.updatedAt = new Date(now - 1000 * 60 * 18).toISOString();
  second.updatedAt = new Date(now - 1000 * 60 * 55).toISOString();
  first.messages = [
    {
      id: crypto.randomUUID(),
      role: "user",
      content: "Analyze gold volatility this week",
      createdAt: new Date(now - 1000 * 60 * 18).toISOString(),
    },
    {
      id: crypto.randomUUID(),
      role: "assistant",
      content: "### Demo volatility brief\n\nSynthetic data indicates an elevated but balanced volatility regime. Validate with live market feeds before drawing conclusions.",
      createdAt: new Date(now - 1000 * 60 * 17).toISOString(),
    },
  ];
  return [first, second];
}

const mobileNavigation: Array<{ id: View; label: string; icon: typeof LayoutDashboard }> = [
  { id: "dashboard", label: "Home", icon: LayoutDashboard },
  { id: "chat", label: "Chat", icon: Bot },
  { id: "research", label: "Sessions", icon: Waypoints },
  { id: "backtesting", label: "Test", icon: FlaskConical },
  { id: "settings", label: "Settings", icon: Settings },
];

export default function Home() {
  const [activeView, setActiveView] = useState<View>("dashboard");
  const [sessions, setSessions] = useState<ResearchSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    queueMicrotask(() => {
      try {
        const stored = localStorage.getItem(STORAGE_KEY);
        const loaded = stored ? (JSON.parse(stored) as ResearchSession[]) : initialSessions();
        setSessions(loaded);
        setActiveSessionId(loaded[0]?.id ?? null);
      } catch {
        const loaded = initialSessions();
        setSessions(loaded);
        setActiveSessionId(loaded[0]?.id ?? null);
      } finally {
        setHydrated(true);
      }
    });
  }, []);

  useEffect(() => {
    if (hydrated) localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions));
  }, [sessions, hydrated]);

  function createSessionAndOpen() {
    const session = createSession();
    setSessions((current) => [session, ...current]);
    setActiveSessionId(session.id);
    setActiveView("chat");
  }

  function updateMessages(id: string, messages: ChatMessage[]) {
    setSessions((current) =>
      current.map((session) =>
        session.id === id
          ? { ...session, messages, updatedAt: new Date().toISOString() }
          : session,
      ),
    );
  }

  function renameSession(id: string, title: string) {
    setSessions((current) =>
      current.map((session) =>
        session.id === id
          ? { ...session, title, updatedAt: new Date().toISOString() }
          : session,
      ),
    );
  }

  function deleteSession(id: string) {
    if (!window.confirm("Delete this research session?")) return;
    setSessions((current) => {
      const remaining = current.filter((session) => session.id !== id);
      if (activeSessionId === id) setActiveSessionId(remaining[0]?.id ?? null);
      return remaining;
    });
  }

  if (!hydrated) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#0a0a0a]">
        <div className="size-6 animate-spin rounded-full border-2 border-[#d2b16a]/20 border-t-[#d2b16a]" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white">
      <Sidebar activeView={activeView} onNavigate={setActiveView} />
      <main className="pb-20 lg:ml-[238px] lg:pb-0">
        <header className="flex h-[76px] items-center justify-between border-b border-white/[0.07] px-4 sm:px-7 lg:px-8">
          <div className="lg:hidden">
            <div className="font-serif text-lg tracking-[0.12em] text-[#f1d49b]">AURUM</div>
          </div>
          <div className="hidden text-xs text-white/35 lg:block">Research workspace / {activeView}</div>
          <div className="flex items-center gap-3">
            <span className="hidden text-xs text-white/35 sm:inline">Synthetic market mode</span>
            <div className="flex size-8 items-center justify-center rounded-full border border-[#d1ad62]/20 bg-[#d1ad62]/10 text-xs font-medium text-[#dbc174]">AR</div>
          </div>
        </header>
        <div className="p-4 sm:p-6 lg:p-8">
          {activeView === "dashboard" && <Dashboard onOpenChat={() => setActiveView("chat")} />}
          {activeView === "chat" && (
            <ChatInterface
              sessions={sessions}
              activeSessionId={activeSessionId}
              onSelectSession={setActiveSessionId}
              onCreateSession={createSessionAndOpen}
              onDeleteSession={deleteSession}
              onRenameSession={renameSession}
              onUpdateMessages={updateMessages}
            />
          )}
          {activeView === "research" && (
            <ResearchSessions
              sessions={sessions}
              onCreate={createSessionAndOpen}
              onOpen={(id) => {
                setActiveSessionId(id);
                setActiveView("chat");
              }}
              onRename={renameSession}
              onDelete={deleteSession}
            />
          )}
          {(activeView === "backtesting" || activeView === "settings") && (
            <PlaceholderView view={activeView} />
          )}
        </div>
      </main>

      <nav className="fixed inset-x-0 bottom-0 z-40 grid h-[68px] grid-cols-5 border-t border-white/[0.07] bg-[#0d0d0d]/95 px-2 backdrop-blur lg:hidden">
        {mobileNavigation.map((item) => {
          const Icon = item.icon;
          const active = item.id === activeView;
          return (
            <button key={item.id} onClick={() => setActiveView(item.id)} className={`flex flex-col items-center justify-center gap-1 text-[9px] ${active ? "text-[#dbbc73]" : "text-white/35"}`}>
              <Icon size={17} />
              {item.label}
            </button>
          );
        })}
      </nav>
    </div>
  );
}
