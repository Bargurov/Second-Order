/**
 * Share Page — read-only presentation view for a saved analysis.
 *
 * Rendered shell-free when the URL matches /share/:eventId.
 * Fetches from /events/{id}/export/json (no auth required in self-hosted mode).
 */

import { useQuery } from "@tanstack/react-query";
import { api, type SavedEvent, type Ticker, type EventStudyBlock } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";
import { EventDossier } from "@/components/ui/event-dossier";
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

/**
 * Research role label — research wording, never directional long/short
 * framing.  The /share route is publicly linkable, so the copy rule applies.
 */
export function roleLabel(role: string | null | undefined): string {
  return role === "beneficiary" ? "Beneficiary" : "Exposed";
}

export function TickerRow({ ticker }: { ticker: Ticker }) {
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
          {roleLabel(ticker.role)}
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
  // Read-only event-study readout (AR / SAR / CAR point estimates) for this
  // saved event.  Fetched from the gated, tracked-only GET — no paid calls,
  // no scoring.  Stays absent until the block resolves and for events that
  // are not computable, so the dossier's event-study section degrades by
  // omission rather than showing a fabricated readout.
  const { data: eventStudy } = useQuery({
    queryKey: qk.eventStudy(ev.id),
    queryFn: () => api.getEventStudy(ev.id),
    staleTime: 300_000,
  });

  return <ShareDossierView ev={ev} eventStudy={eventStudy} />;
}

// ---------------------------------------------------------------------------
// Share dossier view — pure presentation (no data fetching), so it renders
// the same on the server snapshot and in tests.
//
// The shared EventDossier leads as the research note (R5B): it consolidates
// the headline, mechanism, what-changed, affected assets + realized move, the
// optional benchmark-adjusted event-study readout, the scored outcome, and the
// standing claim boundary from this saved event.  Share carries no horizon /
// falsifier payload, so `horizons` is intentionally NOT passed — the dossier's
// "Thesis fails if" section degrades by omission, never faked.
//
// The "Market reaction (raw)" table stays below as supporting tape: it keeps
// the raw, not-benchmark-adjusted framing (honesty guard) the dossier's
// compact line does not spell out, with the same per-ticker figures.
// ---------------------------------------------------------------------------

export function ShareDossierView({
  ev,
  eventStudy,
}: {
  ev: SavedEvent;
  eventStudy?: EventStudyBlock | null;
}) {
  const tickers = ev.market_tickers ?? [];
  const beneficiaryTickers = tickers.filter((t) => t.role === "beneficiary");
  const loserTickers = tickers.filter((t) => t.role !== "beneficiary");

  return (
    <div className="space-y-0">
      {/* ── Research note (EventDossier) ── */}
      <section className="pt-10 pb-8" style={{ animation: "page-in 300ms ease-out" }}>
        <EventDossier
          event={ev}
          eventStudy={eventStudy}
          className="border-white/[0.08] bg-white/[0.02]"
        />
      </section>

      {/* ── Market reaction (raw) — supporting tape, honestly labelled ── */}
      {tickers.length > 0 && (
        <section
          className="py-8 border-t border-white/[0.06]"
          style={{ animation: "page-in 400ms ease-out" }}
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
                  <th className="py-2 pl-4 text-[10px] font-bold uppercase tracking-widest text-white/25 hidden sm:table-cell">Direction</th>
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

      {/* ── Assets to watch ── */}
      {(ev.assets_to_watch?.length ?? 0) > 0 && (
        <section
          className="py-8 border-t border-white/[0.06]"
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
      <div className="pt-4 pb-8 mt-8 flex items-center justify-between border-t border-white/[0.04]">
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
