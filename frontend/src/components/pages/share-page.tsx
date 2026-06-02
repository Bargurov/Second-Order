/**
 * Share Page — read-only presentation view for a saved analysis.
 *
 * Rendered shell-free when the URL matches /share/:eventId.
 * Fetches from /events/{id}/export/json (no auth required in self-hosted mode).
 */

import { useQuery } from "@tanstack/react-query";
import { api, type SavedEvent, type Ticker } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";
import { EventStudyCard } from "@/components/ui/event-study-card";
import { MARKET_REACTION_LABEL, MARKET_REACTION_SUBLABEL } from "@/lib/claim-copy";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function pct(v: number | null | undefined): string {
  if (v == null) return "—";
  return (v > 0 ? "+" : "") + v.toFixed(1) + "%";
}

function retClass(v: number | null | undefined): string {
  if (v == null) return "text-muted-foreground";
  if (v > 0) return "text-[#93d1d3]";
  if (v < 0) return "text-[#ee7d77]";
  return "text-muted-foreground";
}

function fmtDate(s: string | null | undefined): string {
  if (!s) return "";
  const d = new Date(s);
  if (isNaN(d.getTime())) return s;
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

function capitalize(s: string): string {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : "";
}

function stageColor(stage: string): string {
  switch (stage?.toLowerCase()) {
    case "realized": return "border-[#93d1d3]/40 bg-[#93d1d3]/8 text-[#93d1d3]";
    case "anticipated": return "border-amber-500/30 bg-amber-500/8 text-amber-400";
    case "speculative": return "border-purple-400/30 bg-purple-400/8 text-purple-300";
    default: return "border-border bg-surface-container text-muted-foreground";
  }
}

function confidenceColor(c: string): string {
  switch (c?.toLowerCase()) {
    case "high": return "text-[#93d1d3]";
    case "medium": return "text-amber-400";
    case "low": return "text-[#ee7d77]";
    default: return "text-muted-foreground";
  }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SectionHeader({ label }: { label: string }) {
  return (
    <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-muted-foreground/50 mb-3">
      {label}
    </p>
  );
}

function ListBlock({ items, accent }: { items: string[]; accent?: boolean }) {
  if (!items?.length) return <p className="text-xs text-muted-foreground italic">None identified.</p>;
  return (
    <ul className="space-y-1.5">
      {items.map((item, i) => (
        <li key={i} className="flex items-start gap-2 text-sm leading-snug text-muted-foreground">
          <span className={cn("mt-[5px] h-1 w-1 shrink-0 rounded-full", accent ? "bg-[#93d1d3]" : "bg-[#ee7d77]")} />
          {item}
        </li>
      ))}
    </ul>
  );
}

function TickerRow({ ticker }: { ticker: Ticker }) {
  const supports = (ticker.direction_tag ?? "").startsWith("supports");
  const contradicts = (ticker.direction_tag ?? "").startsWith("contradicts");
  return (
    <tr className="border-b border-border/40 last:border-0">
      <td className="py-2 pr-3">
        <div className="flex items-center gap-2">
          <span className={cn(
            "h-1.5 w-1.5 rounded-full shrink-0",
            supports && "bg-[#93d1d3]",
            contradicts && "bg-[#ee7d77]",
            !supports && !contradicts && "bg-border",
          )} />
          <span className="font-mono text-[13px] font-semibold text-foreground">{ticker.symbol}</span>
        </div>
      </td>
      <td className="py-2 pr-4">
        <span className={cn(
          "text-[10px] font-medium uppercase tracking-wide px-1.5 py-0.5 rounded-full border",
          ticker.role === "beneficiary"
            ? "border-[#93d1d3]/20 bg-[#93d1d3]/5 text-[#93d1d3]/70"
            : "border-[#ee7d77]/20 bg-[#ee7d77]/5 text-[#ee7d77]/70",
        )}>
          {ticker.role === "beneficiary" ? "long" : "short"}
        </span>
      </td>
      <td className={cn("py-2 pr-4 text-right font-mono text-xs tabular-nums", retClass(ticker.return_1d))}>
        {pct(ticker.return_1d)}
      </td>
      <td className={cn("py-2 pr-4 text-right font-mono text-xs tabular-nums", retClass(ticker.return_5d))}>
        {pct(ticker.return_5d)}
      </td>
      <td className={cn("py-2 text-right font-mono text-xs tabular-nums", retClass(ticker.return_20d))}>
        {pct(ticker.return_20d)}
      </td>
      <td className="py-2 pl-4 text-xs text-muted-foreground">
        {ticker.direction_tag ?? "—"}
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Loading skeleton
// ---------------------------------------------------------------------------

function ShareSkeleton() {
  return (
    <div className="animate-pulse space-y-6 max-w-3xl mx-auto px-5 py-12">
      <div className="h-3 w-24 rounded bg-white/5" />
      <div className="h-8 w-3/4 rounded bg-white/5" />
      <div className="h-4 w-1/2 rounded bg-white/5" />
      <div className="space-y-2 mt-8">
        {[1, 2, 3].map((k) => <div key={k} className="h-3 w-full rounded bg-white/5" />)}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Share Page
// ---------------------------------------------------------------------------

export function SharePage({ eventId }: { eventId: number }) {
  const { data: ev, isLoading, isError } = useQuery({
    queryKey: qk.eventShare(eventId),
    queryFn: () => api.getEventJson(eventId),
    staleTime: 300_000,
    retry: 1,
  });

  // Force dark mode for this shell-free page
  if (typeof document !== "undefined") {
    document.documentElement.classList.add("dark");
  }

  return (
    <div
      className="min-h-dvh"
      style={{ background: "#0a0a0f" }}
    >
      {/* ── Top bar ── */}
      <header className="border-b border-white/[0.06] bg-[#0a0a0f]/80 backdrop-blur-sm sticky top-0 z-20">
        <div className="max-w-4xl mx-auto px-5 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="h-5 w-5 rounded bg-[#93d1d3]/15 border border-[#93d1d3]/25 flex items-center justify-center">
              <div className="h-2 w-2 rounded-sm bg-[#93d1d3]/80" />
            </div>
            <span
              className="text-[13px] font-semibold text-white/60 tracking-tight"
              style={{ fontFamily: "'Manrope', 'Inter', sans-serif" }}
            >
              Second Order
            </span>
            <span className="text-white/15 text-xs">·</span>
            <span className="text-[11px] text-white/30 uppercase tracking-wider">Research Brief</span>
          </div>
          <button
            onClick={() => {
              if (navigator.clipboard) {
                navigator.clipboard.writeText(window.location.href);
              }
            }}
            className="text-[11px] text-white/30 hover:text-white/60 transition-colors px-2 py-1 rounded border border-white/[0.06] hover:border-white/[0.12]"
          >
            Copy link
          </button>
        </div>
      </header>

      {/* ── Content ── */}
      <main className="max-w-4xl mx-auto px-5 pb-20">
        {isLoading && <ShareSkeleton />}

        {isError && (
          <div className="pt-20 text-center">
            <p className="text-sm text-muted-foreground">Analysis not found or unavailable.</p>
          </div>
        )}

        {ev && <ShareContent ev={ev} />}
      </main>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Content — separated so skeleton renders during load
// ---------------------------------------------------------------------------

export function ShareContent({ ev }: { ev: SavedEvent }) {
  const tickers = ev.market_tickers ?? [];
  const beneficiaryTickers = tickers.filter((t) => t.role === "beneficiary");
  const loserTickers = tickers.filter((t) => t.role !== "beneficiary");

  // Read-only event-study readout (AR / SAR / CAR point estimates) for this
  // saved event.  Fetched from the gated, tracked-only GET — no paid calls,
  // no scoring.  Renders nothing until the block resolves so the snapshot
  // stays calm on load and for events that are not computable.
  const { data: eventStudy } = useQuery({
    queryKey: qk.eventStudy(ev.id),
    queryFn: () => api.getEventStudy(ev.id),
    staleTime: 300_000,
  });

  return (
    <div className="space-y-0">
      {/* ── Hero ── */}
      <section
        className="pt-10 pb-8 border-b border-white/[0.06]"
        style={{ animation: "page-in 300ms ease-out" }}
      >
        {/* Meta strip */}
        <div className="flex flex-wrap items-center gap-2 mb-5">
          {ev.stage && (
            <span className={cn(
              "text-[10px] font-bold uppercase tracking-widest px-2 py-0.5 rounded border",
              stageColor(ev.stage),
            )}>
              {ev.stage}
            </span>
          )}
          {ev.confidence && (
            <span className={cn("text-[10px] font-semibold uppercase tracking-widest", confidenceColor(ev.confidence))}>
              {capitalize(ev.confidence)} conviction
            </span>
          )}
          {(ev.event_date || ev.timestamp) && (
            <span className="text-[11px] text-white/25 ml-auto tabular-nums">
              {fmtDate(ev.event_date ?? ev.timestamp)}
            </span>
          )}
        </div>

        {/* Headline */}
        <h1
          className="text-[22px] sm:text-[28px] font-bold leading-tight text-white/90 mb-4 tracking-tight"
          style={{ fontFamily: "'Manrope', 'Inter', sans-serif" }}
        >
          {ev.headline}
        </h1>

        {/* Mechanism */}
        {ev.mechanism_summary && (
          <p className="text-sm leading-relaxed text-white/50 max-w-2xl">
            {ev.mechanism_summary}
          </p>
        )}
      </section>

      {/* ── Thesis — beneficiaries + exposed ── */}
      {((ev.beneficiaries?.length ?? 0) > 0 || (ev.losers?.length ?? 0) > 0) && (
        <section
          className="py-8 border-b border-white/[0.06]"
          style={{ animation: "page-in 350ms ease-out" }}
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-8">
            {(ev.beneficiaries?.length ?? 0) > 0 && (
              <div>
                <SectionHeader label="Beneficiaries" />
                <ListBlock items={ev.beneficiaries} accent={true} />
              </div>
            )}
            {(ev.losers?.length ?? 0) > 0 && (
              <div>
                <SectionHeader label="Exposed" />
                <ListBlock items={ev.losers} accent={false} />
              </div>
            )}
          </div>
        </section>
      )}

      {/* ── What changed ── */}
      {ev.what_changed && (
        <section
          className="py-8 border-b border-white/[0.06]"
          style={{ animation: "page-in 400ms ease-out" }}
        >
          <SectionHeader label="What Changed" />
          <p className="text-sm leading-relaxed text-white/55">{ev.what_changed}</p>
        </section>
      )}

      {/* ── Market validation ── */}
      {tickers.length > 0 && (
        <section
          className="py-8 border-b border-white/[0.06]"
          style={{ animation: "page-in 450ms ease-out" }}
        >
          <SectionHeader label={MARKET_REACTION_LABEL} />
          <p className="text-[11px] text-white/30 mb-3 leading-relaxed max-w-2xl">
            {MARKET_REACTION_SUBLABEL}
          </p>
          {ev.market_note && (
            <p className="text-xs text-white/35 mb-4 leading-relaxed">{ev.market_note}</p>
          )}
          <div className="rounded-lg border border-white/[0.07] overflow-hidden">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-white/[0.07] bg-white/[0.02]">
                  <th className="py-2 pl-3 pr-3 text-[10px] font-bold uppercase tracking-widest text-white/25">Ticker</th>
                  <th className="py-2 pr-4 text-[10px] font-bold uppercase tracking-widest text-white/25">Side</th>
                  <th className="py-2 pr-4 text-right text-[10px] font-bold uppercase tracking-widest text-white/25">1d</th>
                  <th className="py-2 pr-4 text-right text-[10px] font-bold uppercase tracking-widest text-white/25">5d</th>
                  <th className="py-2 text-right text-[10px] font-bold uppercase tracking-widest text-white/25">20d</th>
                  <th className="py-2 pl-4 text-[10px] font-bold uppercase tracking-widest text-white/25 hidden sm:table-cell">Signal</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.04]">
                {beneficiaryTickers.map((t) => <TickerRow key={t.symbol} ticker={t} />)}
                {loserTickers.map((t) => <TickerRow key={t.symbol} ticker={t} />)}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* ── Event-study readout ── */}
      {eventStudy && (
        <section
          className="py-8 border-b border-white/[0.06]"
          style={{ animation: "page-in 475ms ease-out" }}
        >
          <EventStudyCard block={eventStudy} />
        </section>
      )}

      {/* ── Assets to watch ── */}
      {(ev.assets_to_watch?.length ?? 0) > 0 && (
        <section
          className="py-8"
          style={{ animation: "page-in 500ms ease-out" }}
        >
          <SectionHeader label="Assets to Watch" />
          <div className="flex flex-wrap gap-2">
            {ev.assets_to_watch.map((sym) => (
              <span
                key={sym}
                className="font-mono text-[11px] px-2.5 py-1 rounded border border-white/[0.08] bg-white/[0.02] text-white/40"
              >
                {sym}
              </span>
            ))}
          </div>
        </section>
      )}

      {/* ── Footer ── */}
      <div className="pt-4 pb-8 flex items-center justify-between border-t border-white/[0.04]">
        <span className="text-[10px] text-white/15 uppercase tracking-widest">
          Second Order · Read-only snapshot
        </span>
        {ev.timestamp && (
          <span className="text-[10px] text-white/15 tabular-nums">
            Saved {fmtDate(ev.timestamp)}
          </span>
        )}
      </div>
    </div>
  );
}
