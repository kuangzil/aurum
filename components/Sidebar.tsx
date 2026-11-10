"use client";

import {
  Activity,
  Bot,
  FlaskConical,
  LayoutDashboard,
  Settings,
  Waypoints,
} from "lucide-react";

export type View = "dashboard" | "chat" | "research" | "backtesting" | "settings";

const navigation: Array<{
  id: View;
  label: string;
  icon: typeof LayoutDashboard;
}> = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "chat", label: "Agent Chat", icon: Bot },
  { id: "research", label: "Research Sessions", icon: Waypoints },
  { id: "backtesting", label: "Backtesting", icon: FlaskConical },
  { id: "settings", label: "Settings", icon: Settings },
];

export function Sidebar({
  activeView,
  onNavigate,
}: {
  activeView: View;
  onNavigate: (view: View) => void;
}) {
  return (
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-[238px] flex-col border-r border-white/[0.07] bg-[#0d0d0d] lg:flex">
      <div className="flex h-[76px] items-center gap-3 border-b border-white/[0.07] px-6">
        <div className="flex size-9 items-center justify-center rounded-xl border border-[#d5aa55]/30 bg-[#d5aa55]/10 text-[#d5b15e]">
          <Activity size={18} />
        </div>
        <div>
          <div className="font-serif text-xl tracking-[0.12em] text-[#f1d49b]">AURUM</div>
          <div className="text-[10px] uppercase tracking-[0.24em] text-white/35">Research agent</div>
        </div>
      </div>

      <nav className="flex-1 space-y-1 px-3 py-5">
        {navigation.map((item) => {
          const Icon = item.icon;
          const active = item.id === activeView;
          return (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition ${
                active
                  ? "bg-[#d6ad60]/10 text-[#e4c77e]"
                  : "text-white/48 hover:bg-white/[0.04] hover:text-white/80"
              }`}
            >
              <Icon size={17} strokeWidth={1.7} />
              {item.label}
            </button>
          );
        })}
      </nav>

      <div className="m-3 rounded-xl border border-white/[0.07] bg-white/[0.025] p-3">
        <div className="mb-2 flex items-center gap-2 text-xs text-white/55">
          <span className="size-2 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,.55)]" />
          Agent system
        </div>
        <div className="flex items-center justify-between text-xs">
          <span className="text-white/35">Demo mode</span>
          <span className="font-mono text-[#d9b96d]">Ready</span>
        </div>
      </div>
    </aside>
  );
}
