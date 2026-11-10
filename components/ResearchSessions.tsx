"use client";

import { Bot, Clock3, Plus, Trash2 } from "lucide-react";
import type { ResearchSession } from "@/app/types";

export function ResearchSessions({
  sessions,
  onCreate,
  onOpen,
  onRename,
  onDelete,
}: {
  sessions: ResearchSession[];
  onCreate: () => void;
  onOpen: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <div>
      <div className="mb-5 flex items-end justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.18em] text-[#d4b76c]/70">Library</p>
          <h1 className="mt-1 text-2xl font-semibold text-white">Research Sessions</h1>
        </div>
        <button onClick={onCreate} className="flex items-center gap-2 rounded-lg bg-[#cdaa62] px-3 py-2.5 text-xs font-medium text-[#17140d] hover:bg-[#dfc178]">
          <Plus size={15} /> New session
        </button>
      </div>

      {sessions.length === 0 ? (
        <div className="flex min-h-[350px] flex-col items-center justify-center rounded-xl border border-white/[0.07] bg-[#111111] text-center">
          <Bot size={22} className="text-[#d6b768]" />
          <h2 className="mt-3 text-sm text-white/75">No sessions yet</h2>
          <button onClick={onCreate} className="mt-4 text-xs text-[#d4b76c]">Create your first research session</button>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {sessions.map((session) => (
            <article key={session.id} className="rounded-xl border border-white/[0.07] bg-[#111111] p-4 transition hover:border-[#d2b164]/20">
              <div className="flex items-start justify-between gap-3">
                <button onClick={() => onOpen(session.id)} className="min-w-0 text-left">
                  <h2 className="truncate text-sm font-medium text-white/80">{session.title}</h2>
                  <div className="mt-2 flex items-center gap-1.5 text-[11px] text-white/30">
                    <Clock3 size={12} />
                    Updated {new Date(session.updatedAt).toLocaleDateString()}
                  </div>
                </button>
                <button
                  onClick={() => {
                    const title = window.prompt("Rename research session", session.title)?.trim();
                    if (title) onRename(session.id, title);
                  }}
                  className="text-[10px] text-white/35 hover:text-[#d9bc74]"
                >
                  Edit
                </button>
              </div>
              <div className="mt-5 flex items-center justify-between border-t border-white/[0.06] pt-3">
                <span className="text-xs text-white/35">{session.messages.length} messages</span>
                <div className="flex gap-2">
                  <button onClick={() => onDelete(session.id)} aria-label={`Delete ${session.title}`} className="text-white/25 hover:text-rose-400">
                    <Trash2 size={14} />
                  </button>
                  <button onClick={() => onOpen(session.id)} className="text-xs text-[#d5b568]">Open</button>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
