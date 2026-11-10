"use client";

import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
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

const priceData = [
  { date: "Oct 07", price: 2324 },
  { date: "Oct 09", price: 2338 },
  { date: "Oct 11", price: 2329 },
  { date: "Oct 13", price: 2351 },
  { date: "Oct 15", price: 2344 },
  { date: "Oct 17", price: 2362 },
  { date: "Oct 19", price: 2356 },
  { date: "Oct 21", price: 2374 },
  { date: "Oct 23", price: 2368 },
  { date: "Oct 25", price: 2382 },
  { date: "Oct 27", price: 2376 },
  { date: "Oct 29", price: 2391 },
  { date: "Oct 31", price: 2384 },
  { date: "Nov 02", price: 2369 },
  { date: "Nov 04", price: 2379 },
  { date: "Nov 06", price: 2387 },
];

const activity = [
  { title: "Macro catalysts brief", detail: "Completed 6 minutes ago", icon: Sparkles, color: "text-[#dbb663]" },
  { title: "Volatility regime scan", detail: "Completed 18 minutes ago", icon: Gauge, color: "text-sky-400" },
  { title: "Support & resistance review", detail: "Completed 42 minutes ago", icon: ShieldCheck, color: "text-emerald-400" },
];

function Metric({ label, value, change, negative }: { label: string; value: string; change: string; negative?: boolean }) {
  return (
    <div className="rounded-xl border border-white/[0.07] bg-[#111111] p-4">
      <div className="text-[11px] uppercase tracking-[0.16em] text-white/35">{label}</div>
      <div className="mt-3 flex items-end justify-between gap-2">
        <span className="text-xl font-semibold text-white/90">{value}</span>
        <span className={`flex items-center text-xs ${negative ? "text-rose-400" : "text-emerald-400"}`}>
          {negative ? <ArrowDownRight size={14} /> : <ArrowUpRight size={14} />}
          {change}
        </span>
      </div>
    </div>
  );
}

export function Dashboard({ onOpenChat }: { onOpenChat: () => void }) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.18em] text-[#d4b76c]/70">Overview</p>
          <h1 className="mt-1 text-2xl font-semibold text-white">Market Intelligence</h1>
        </div>
        <div className="rounded-md border border-[#d5ad58]/15 bg-[#d5ad58]/[0.06] px-3 py-2 text-[11px] text-[#d9c184]">
          Demo data · Not real-time market data
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <div className="col-span-2 rounded-xl border border-[#d7b669]/20 bg-gradient-to-br from-[#181713] to-[#101010] p-5 sm:col-span-1">
          <div className="flex items-center justify-between text-xs text-white/40">
            <span>XAU/USD</span>
            <span className="rounded bg-emerald-400/10 px-2 py-1 text-emerald-400">+0.42%</span>
          </div>
          <div className="mt-3 font-mono text-3xl font-semibold text-[#f1d490]">$2,387.42</div>
          <div className="mt-2 text-xs text-white/35">Synthetic spot reference</div>
        </div>
        <Metric label="30D High" value="$2,391.80" change="0.18%" />
        <Metric label="30D Low" value="$2,324.10" change="2.70%" />
        <Metric label="Dollar Index" value="104.21" change="0.31%" negative />
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.7fr)_minmax(260px,.7fr)]">
        <section className="rounded-xl border border-white/[0.07] bg-[#111111] p-4 sm:p-5">
          <div className="mb-5 flex items-center justify-between">
            <div>
              <h2 className="text-sm font-medium text-white/90">Gold Price History</h2>
              <p className="mt-1 text-xs text-white/35">XAU/USD · 30 day synthetic series</p>
            </div>
            <button className="rounded-md border border-white/[0.08] px-3 py-1.5 text-xs text-white/50">30D</button>
          </div>
          <div className="h-[270px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={priceData} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="goldFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#d7b669" stopOpacity={0.28} />
                    <stop offset="100%" stopColor="#d7b669" stopOpacity={0.01} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="rgba(255,255,255,.055)" vertical={false} />
                <XAxis dataKey="date" tick={{ fill: "rgba(255,255,255,.32)", fontSize: 10 }} tickLine={false} axisLine={false} interval={2} />
                <YAxis domain={[2300, 2400]} tick={{ fill: "rgba(255,255,255,.32)", fontSize: 10 }} tickLine={false} axisLine={false} tickFormatter={(value) => `$${value}`} />
                <Tooltip
                  contentStyle={{ background: "#171717", border: "1px solid rgba(255,255,255,.08)", borderRadius: 8, fontSize: 12 }}
                  labelStyle={{ color: "rgba(255,255,255,.45)" }}
                  formatter={(value) => [`$${Number(value).toLocaleString()}`, "XAU/USD"]}
                />
                <Area type="monotone" dataKey="price" stroke="#d8b668" strokeWidth={2} fill="url(#goldFill)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </section>

        <section className="rounded-xl border border-white/[0.07] bg-[#111111] p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium text-white/90">Market Metrics</h2>
            <Activity size={15} className="text-[#d4b66c]" />
          </div>
          <div className="mt-5 space-y-5">
            {[
              ["Volatility", "14.8%", 68],
              ["Momentum", "+62", 62],
              ["Sentiment", "Bullish", 71],
              ["Liquidity", "High", 82],
            ].map(([label, value, width]) => (
              <div key={String(label)}>
                <div className="mb-2 flex justify-between text-xs">
                  <span className="text-white/40">{label}</span>
                  <span className="font-mono text-white/75">{value}</span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
                  <div className="h-full rounded-full bg-gradient-to-r from-[#9d7a36] to-[#e0c47c]" style={{ width: `${width}%` }} />
                </div>
              </div>
            ))}
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
