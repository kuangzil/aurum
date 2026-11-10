"use client";

import { FlaskConical, Settings } from "lucide-react";

export function PlaceholderView({ view }: { view: "backtesting" | "settings" }) {
  const backtesting = view === "backtesting";
  const Icon = backtesting ? FlaskConical : Settings;
  return (
    <div>
      <p className="text-xs uppercase tracking-[0.18em] text-[#d4b76c]/70">{backtesting ? "Validation" : "Configuration"}</p>
      <h1 className="mt-1 text-2xl font-semibold text-white">{backtesting ? "Backtesting" : "Settings"}</h1>
      <div className="mt-5 flex min-h-[420px] flex-col items-center justify-center rounded-xl border border-white/[0.07] bg-[#111111] text-center">
        <div className="flex size-12 items-center justify-center rounded-xl border border-[#d1af66]/20 bg-[#d1af66]/[0.07] text-[#d7ba70]">
          <Icon size={21} />
        </div>
        <h2 className="mt-4 text-sm text-white/80">{backtesting ? "Backtesting workspace coming soon" : "Settings workspace coming soon"}</h2>
        <p className="mt-2 max-w-sm text-xs leading-5 text-white/35">
          {backtesting
            ? "This area will connect strategy research to historical XAU/USD validation."
            : "This area will contain agent, MCP tool, and data provider configuration."}
        </p>
      </div>
    </div>
  );
}
