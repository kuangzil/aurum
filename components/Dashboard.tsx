"use client";

import { useEffect, useState } from "react";
import type { GoldHistoryResponse, GoldSnapshot } from "@/app/types";
import {
  Bot,
  Gauge,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const activity = [
  { title: "Macro catalysts brief", detail: "Completed 6 minutes ago", icon: Sparkles, color: "text-[#dbb663]" },
  { title: "Volatility regime scan", detail: "Completed 18 minutes ago", icon: Gauge, color: "text-sky-400" },
  { title: "Support & resistance review", detail: "Completed 42 minutes ago", icon: ShieldCheck, color: "text-emerald-400" },
];

export function Dashboard({ onOpenChat }: { onOpenChat: () => void }) {
  const [latest, setLatest] = useState<GoldSnapshot | null>();
  const [history, setHistory] = useState<GoldSnapshot[]>();
  const [latestError, setLatestError] = useState<string>();
  const [historyError, setHistoryError] = useState<string>();

  useEffect(() => {
    let active = true;

    async function loadLatest() {
      try {
        const response = await fetch("/api/market/gold/latest", { cache: "no-store" });
        if (response.status === 404) {
          if (active) setLatest(null);
          return;
        }
        if (!response.ok) throw new Error(`Latest gold price request failed (HTTP ${response.status}).`);
        const snapshot: GoldSnapshot = await response.json();
        if (active) setLatest(snapshot);
      } catch (error) {
        if (active) setLatestError(String(error));
      }
    }

    async function loadHistory() {
      try {
        const response = await fetch("/api/market/gold/history", { cache: "no-store" });
        if (!response.ok) throw new Error(`Gold history request failed (HTTP ${response.status}).`);
        const data: GoldHistoryResponse = await response.json();
        data.snapshots.sort((a, b) => Date.parse(a.observed_hour_utc) - Date.parse(b.observed_hour_utc));
        if (active) setHistory(data.snapshots);
      } catch (error) {
        if (active) setHistoryError(String(error));
      }
    }

    void loadLatest();
    void loadHistory();
    return () => { active = false; };
  }, []);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.18em] text-[#d4b76c]/70">Overview</p>
          <h1 className="mt-1 text-2xl font-semibold text-white">Market Intelligence</h1>
        </div>
        <div className="rounded-md border border-[#d5ad58]/15 bg-[#d5ad58]/[0.06] px-3 py-2 text-[11px] text-[#d9c184]">
          Stored observations · Not a live feed
        </div>
      </div>

      {latestError ? (
        <div role="alert" className="rounded-xl border border-rose-400/20 bg-[#111111] p-5 text-sm text-rose-400">{latestError}</div>
      ) : latest === undefined ? (
        <div role="status" className="rounded-xl border border-white/[0.07] bg-[#111111] p-5 text-sm text-white/50">Loading latest gold observation…</div>
      ) : latest === null ? (
        <div role="status" className="rounded-xl border border-white/[0.07] bg-[#111111] p-5 text-sm text-white/50">No stored gold observation is available.</div>
      ) : (
        <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
          <div className="col-span-2 rounded-xl border border-[#d7b669]/20 bg-gradient-to-br from-[#181713] to-[#101010] p-5 sm:col-span-1">
            <div className="text-xs text-white/40">XAU/USD</div>
            <div className="mt-3 font-mono text-3xl font-semibold text-[#f1d490]">${Number(latest.price).toLocaleString("en-US", { maximumFractionDigits: 12 })}</div>
            <div className="mt-2 text-xs text-white/35">Latest stored price · USD per troy ounce</div>
          </div>
          <div className="rounded-xl border border-white/[0.07] bg-[#111111] p-4">
            <div className="text-[11px] uppercase tracking-[0.16em] text-white/35">Source</div>
            <div className="mt-3 break-words text-sm text-white/90">{latest.source}</div>
          </div>
          <div className="rounded-xl border border-white/[0.07] bg-[#111111] p-4">
            <div className="text-[11px] uppercase tracking-[0.16em] text-white/35">Quote timestamp (UTC)</div>
            <time dateTime={latest.quoted_at_utc} className="mt-3 block text-sm text-white/90">{new Date(latest.quoted_at_utc).toLocaleString("en-US", { timeZone: "UTC" })}</time>
          </div>
          <div className="rounded-xl border border-white/[0.07] bg-[#111111] p-4">
            <div className="text-[11px] uppercase tracking-[0.16em] text-white/35">Stale status</div>
            <div className={`mt-3 text-sm ${latest.is_stale ? "text-amber-400" : "text-emerald-400"}`}>{latest.is_stale ? "Stale · Last known observation" : "Not stale · Within freshness window"}</div>
          </div>
        </div>
      )}

      <div>
        <section className="rounded-xl border border-white/[0.07] bg-[#111111] p-4 sm:p-5">
          <div className="mb-5 flex items-center justify-between">
            <div>
              <h2 className="text-sm font-medium text-white/90">Gold Price History</h2>
              <p className="mt-1 text-xs text-white/35">XAU/USD · Up to 24 stored hourly observations · UTC</p>
            </div>
            <span className="rounded-md border border-white/[0.08] px-3 py-1.5 text-xs text-white/50">Latest 24</span>
          </div>
          <div className="h-[270px] w-full">
            {historyError ? (
              <p role="alert" className="flex h-full items-center justify-center text-sm text-rose-400">{historyError}</p>
            ) : history === undefined ? (
              <p role="status" className="flex h-full items-center justify-center text-sm text-white/50">Loading gold price history…</p>
            ) : history.length === 0 ? (
              <p role="status" className="flex h-full items-center justify-center text-sm text-white/50">No historical gold observations are available.</p>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={history.map((snapshot) => ({ timestamp: Date.parse(snapshot.observed_hour_utc), price: Number(snapshot.price) }))} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="goldFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#d7b669" stopOpacity={0.28} />
                      <stop offset="100%" stopColor="#d7b669" stopOpacity={0.01} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="rgba(255,255,255,.055)" vertical={false} />
                  <XAxis dataKey="timestamp" type="number" scale="time" domain={["dataMin", "dataMax"]} tickFormatter={(value) => new Date(value).toLocaleString("en-US", { timeZone: "UTC", month: "short", day: "numeric", hour: "2-digit" })} tick={{ fill: "rgba(255,255,255,.32)", fontSize: 10 }} tickLine={false} axisLine={false} />
                  <YAxis domain={["auto", "auto"]} tick={{ fill: "rgba(255,255,255,.32)", fontSize: 10 }} tickLine={false} axisLine={false} tickFormatter={(value) => `$${value}`} />
                  <Tooltip
                    contentStyle={{ background: "#171717", border: "1px solid rgba(255,255,255,.08)", borderRadius: 8, fontSize: 12 }}
                    labelStyle={{ color: "rgba(255,255,255,.45)" }}
                    labelFormatter={(value) => new Date(Number(value)).toLocaleString("en-US", { timeZone: "UTC", timeZoneName: "short" })}
                    formatter={(value) => [`$${Number(value).toLocaleString()}`, "XAU/USD"]}
                  />
                  <Area type="linear" dataKey="price" dot={{ r: 3, fill: "#d8b668" }} stroke="#d8b668" strokeWidth={2} fill="url(#goldFill)" />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
        </section>
      </div>

      <div className="grid gap-4 md:grid-cols-[minmax(0,1.4fr)_minmax(260px,.6fr)]">
        <section className="rounded-xl border border-white/[0.07] bg-[#111111] p-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-sm font-medium text-white/90">Recent AI Research</h2>
            <button onClick={onOpenChat} className="text-xs text-[#d8b96d] hover:text-[#efd995]">Open chat</button>
          </div>
          <div className="divide-y divide-white/[0.06]">
            {activity.map((item) => {
              const Icon = item.icon;
              return (
                <div key={item.title} className="flex items-center gap-3 py-3 first:pt-0 last:pb-0">
                  <div className="flex size-9 items-center justify-center rounded-lg border border-white/[0.07] bg-white/[0.025]">
                    <Icon size={15} className={item.color} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm text-white/75">{item.title}</div>
                    <div className="mt-1 text-xs text-white/30">{item.detail}</div>
                  </div>
                  <span className="rounded-md bg-emerald-400/[0.07] px-2 py-1 text-[10px] text-emerald-400">Complete</span>
                </div>
              );
            })}
          </div>
        </section>

        <section className="rounded-xl border border-white/[0.07] bg-[#111111] p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium text-white/90">Agent Status</h2>
            <span className="size-2 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,.55)]" />
          </div>
          <div className="mt-5 space-y-3 text-xs">
            <div className="flex items-center justify-between"><span className="text-white/35">Execution</span><span className="text-emerald-400">Idle</span></div>
            <div className="flex items-center justify-between"><span className="text-white/35">Model</span><span className="font-mono text-white/60">Mock agent</span></div>
            <div className="flex items-center justify-between"><span className="text-white/35">Tools</span><span className="text-white/60">5 available</span></div>
            <button onClick={onOpenChat} className="mt-2 flex w-full items-center justify-center gap-2 rounded-lg bg-[#caa85d] py-2.5 font-medium text-[#17140e] transition hover:bg-[#dfc178]">
              <Bot size={15} /> Run research
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}
