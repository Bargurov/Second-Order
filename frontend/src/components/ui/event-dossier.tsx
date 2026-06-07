/**
 * EventDossier (R5A) — shared, read-only research note for one analyzed event.
 *
 * Consolidates substance that already exists on the frontend into one coherent
 * note: event metadata, the claimed mechanism, what changed, affected assets +
 * their realized 1d/5d/20d move, the optional benchmark-adjusted event-study
 * readout, the optional horizon falsifier, the scored outcome, and the standing
 * claim boundary.  It adds NO new analytics and NO new claims.
 *
 * Inputs are existing types only:
 *   - ``event``      (SavedEvent) — always present.
 *   - ``eventStudy`` (EventStudyBlock) — optional; surfaces that fetch
 *     ``GET /events/{id}/event-study`` (e.g. Share) can pass it.
 *   - ``horizons``   (HorizonCheckpoints) — optional; the falsifier lives on
 *     the analyze-time payload, NOT on SavedEvent, so it is absent on /share.
 *
 * Optional sections degrade by OMISSION (no fake stub).  Copy carries no
 * buy/sell/long/short/alpha/signal/trade framing and no proof/confirmed/
 * validated-as-success framing; the n=1 / event-window caveats stay visible.
 */
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";
import type { SavedEvent, EventStudyBlock, HorizonCheckpoints } from "@/lib/api";
import { VALIDATION_V2_SCOPE_CAVEAT, VALIDATION_V2_NOT_CLAIMED } from "@/lib/claim-copy";

// Research roles — never L/S trade legs (Q2).
function roleLabel(role: string | null | undefined): string {
  const r = (role ?? "").toLowerCase();
  if (r === "beneficiary") return "Beneficiary";
  if (r === "loser") return "Exposed";
  return role ? role.charAt(0).toUpperCase() + role.slice(1) : "—";
}

// Event-study AR / CAR are fractional BHAR values (raw_return - benchmark
// return, e.g. 0.012) — render as signed percent by ×100.
function fmtPct(x: number | null | undefined): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  const pct = x * 100;
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`;
}

// market_tickers 1d / 5d / 20d returns already arrive as PERCENT
// (market_check.py computes (end - start) / start * 100), e.g. -2.9 == -2.9%.
// Render at face value — never ×100 — and mirror the raw-table formatter so
// the same figure reads identically on both Share surfaces.
function fmtTickerPct(x: number | null | undefined): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  return `${x > 0 ? "+" : ""}${x.toFixed(1)}%`;
}

// Honest status labels — "validated" is shown as "Any-supporting" (Q3), never
// as a success verdict.
const STATUS_LABEL: Record<string, string> = {
  validated: "Any-supporting",
  contradicted: "Contradicted",
  unresolved: "Unresolved",
  pending: "Pending",
};

function FieldLabel({ children }: { children: ReactNode }) {
  return (
    <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
      {children}
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <FieldLabel>{label}</FieldLabel>
      <p className="mt-1 text-[12.5px] leading-relaxed text-foreground/80">{children}</p>
    </div>
  );
}

interface EventDossierProps {
  event: SavedEvent;
  eventStudy?: EventStudyBlock | null;
  horizons?: HorizonCheckpoints | null;
  className?: string;
}

export function EventDossier({ event, eventStudy, horizons, className }: EventDossierProps) {
  const tickers = event.market_tickers ?? [];
  const dateStr = event.event_date ?? (event.timestamp ? event.timestamp.slice(0, 10) : null);

  const esAvailable =
    !!eventStudy &&
    eventStudy.status === "event_study_available" &&
    (eventStudy.per_horizon?.length ?? 0) > 0;

  // Primary falsifier — earliest horizon with a non-empty falsifies_if
  // (the R2B pattern); payload text only, never invented.
  const primaryFalsifier = (() => {
    for (const h of horizons?.horizons ?? []) {
      const text = h.falsifies_if?.[0];
      if (text) return { horizon: h.horizon, text };
    }
    return null;
  })();

  const v2 = event.validation_status_v2;
  const statusLabel = v2 ? STATUS_LABEL[v2.status] ?? v2.status : null;

  const eyebrow = [
    event.stage,
    event.confidence ? `${event.confidence} conviction` : null,
    dateStr,
  ]
    .filter(Boolean)
    .join("  ·  ");

  const hasAssetBlock =
    tickers.length > 0 || (event.beneficiaries?.length ?? 0) > 0 || (event.losers?.length ?? 0) > 0;

  return (
    <article className={cn("rounded-[6px] border border-border bg-card/40 p-5", className)}>
      <header className="mb-4">
        {eyebrow && (
          <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
            {eyebrow}
          </div>
        )}
        <h3 className="mt-1.5 font-headline text-[17px] font-semibold leading-snug tracking-[-0.01em] text-foreground">
          {event.headline}
        </h3>
      </header>

      <div className="flex flex-col gap-3.5">
        {event.mechanism_summary && <Field label="Mechanism">{event.mechanism_summary}</Field>}
        {event.what_changed && <Field label="What changed">{event.what_changed}</Field>}

        {hasAssetBlock && (
          <div>
            <FieldLabel>Affected assets</FieldLabel>
            {tickers.length > 0 ? (
              <ul className="mt-1 flex flex-col gap-1">
                {tickers.map((t) => (
                  <li
                    key={t.symbol}
                    className="flex flex-wrap items-baseline gap-x-2 font-mono text-[11px]"
                  >
                    <span className="font-semibold tabular-nums text-foreground">{t.symbol}</span>
                    <span className="text-muted-foreground">{roleLabel(t.role)}</span>
                    <span className="tabular-nums text-foreground/70">
                      1d {fmtTickerPct(t.return_1d)} · 5d {fmtTickerPct(t.return_5d)} · 20d{" "}
                      {fmtTickerPct(t.return_20d)}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-1 text-[11.5px] text-foreground/70">
                {[...(event.beneficiaries ?? []), ...(event.losers ?? [])].join(" · ")}
              </p>
            )}
          </div>
        )}

        {esAvailable && (
          <div>
            <FieldLabel>Event-study · benchmark-adjusted</FieldLabel>
            <ul className="mt-1 flex flex-col gap-0.5 font-mono text-[11px] text-foreground/75">
              {eventStudy!.per_horizon!.map((h) => (
                <li key={h.horizon} className="tabular-nums">
                  {h.horizon}d — AR {fmtPct(h.abnormal_return)} · CAR {fmtPct(h.car)} · SAR{" "}
                  {h.sar === null || h.sar === undefined ? "—" : h.sar.toFixed(2)}
                </li>
              ))}
            </ul>
            <p className="mt-1 text-[10.5px] italic leading-relaxed text-muted-foreground">
              Point estimates at n=1 — descriptive, not statistical significance.
            </p>
          </div>
        )}

        {primaryFalsifier && (
          <div>
            <FieldLabel>Thesis fails if</FieldLabel>
            <p className="mt-1 text-[12px] leading-relaxed text-foreground/80">
              <span className="font-mono tabular-nums text-muted-foreground">
                {primaryFalsifier.horizon}
              </span>
              {" · "}
              {primaryFalsifier.text}
            </p>
          </div>
        )}

        {v2 && statusLabel && (
          <div>
            <FieldLabel>Scored outcome</FieldLabel>
            <p className="mt-1 text-[12px] leading-relaxed text-foreground/80">
              <span className="font-semibold text-foreground">{statusLabel}</span>
              {typeof v2.ratio === "number" && (
                <span className="ml-2 font-mono text-[11px] tabular-nums text-muted-foreground">
                  support {Math.round(v2.ratio * 100)}%
                </span>
              )}
            </p>
            {v2.reason && (
              <p className="mt-0.5 text-[11.5px] italic leading-relaxed text-foreground/65">
                {v2.reason}
              </p>
            )}
          </div>
        )}

        {/* Standing claim boundary — always present, reusing the shared
            caveat + not-claimed constants. */}
        <div className="border-t border-border pt-2.5">
          <p className="text-[11px] italic leading-relaxed text-muted-foreground">
            {VALIDATION_V2_SCOPE_CAVEAT}
          </p>
          <p className="mt-1 font-mono text-[10px] tracking-[0.02em] text-muted-foreground">
            {VALIDATION_V2_NOT_CLAIMED}
          </p>
          <p className="mt-1.5 font-mono text-[10px] leading-relaxed tracking-[0.02em] text-muted-foreground">
            Evidence: descriptive event-window reads
            {esAvailable ? " with a benchmark-adjusted event-study readout" : ""} — no
            benchmark-adjusted significance claimed.
          </p>
        </div>
      </div>
    </article>
  );
}
