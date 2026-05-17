/**
 * Still Moving Market panel — presentational view for the strict
 * Still Moving Section C source.  Renders one card per item with
 * the lead ticker, an optional persistence_signal, the
 * evidence_reason narrative, and the source-attached caution_label.
 *
 * Read-only / props-only by construction
 * --------------------------------------
 *
 * The component performs no fetch, no mutation, and no derivation
 * beyond formatting.  The parent owns data acquisition (typically a
 * GET to ``/demo/still-moving-market`` once that adapter lands).  No
 * claims of correctness, validation, alpha, or proof — items surface
 * with the caution_label the backend attached so the operator sees
 * the demo qualifier before any inclusion decision.
 */

import { cn } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export interface StillMovingMarketItem {
  event_id?: number | null;
  headline: string;
  /**
   * Lead ticker for the row.  The source emits ``primary_ticker``;
   * the panel also accepts ``top_mover`` so a caller that maps from
   * an alternate upstream shape does not have to rename the field.
   * When both are present ``primary_ticker`` wins.
   */
  primary_ticker?: string | null;
  top_mover?: string | null;
  persistence_signal?: string | null;
  evidence_reason: string;
  caution_label: string;
}

export interface StillMovingMarketPanelProps {
  items: ReadonlyArray<StillMovingMarketItem>;
  className?: string;
}

const EMPTY_COPY = "No eligible Still Moving items currently.";

export function StillMovingMarketPanel({ items, className }: StillMovingMarketPanelProps) {
  if (items.length === 0) {
    return (
      <section className={cn("space-y-2", className)} aria-labelledby="demo-still-moving-empty">
        <h2 id="demo-still-moving-empty" className="sr-only">
          Still Moving Market — empty
        </h2>
        <p className="text-sm text-on-surface-variant/80">{EMPTY_COPY}</p>
      </section>
    );
  }

  return (
    <section className={cn("space-y-2", className)} aria-label="Still Moving Market demo items">
      <ul className="grid gap-2">
        {items.map((item, index) => (
          <li key={itemKey(item, index)}>
            <Card className="border-border/70">
              <CardHeader className="gap-1 pb-2">
                <div className="flex items-center justify-between gap-2">
                  <LeadTicker
                    primary={item.primary_ticker ?? null}
                    fallback={item.top_mover ?? null}
                  />
                  <CautionPill label={item.caution_label} />
                </div>
                <CardTitle className="text-sm leading-snug">{item.headline}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-1.5 pt-0">
                {item.persistence_signal && (
                  <PersistencePill signal={item.persistence_signal} />
                )}
                {item.evidence_reason && (
                  <p className="text-[12px] leading-snug text-on-surface-variant/85">
                    {item.evidence_reason}
                  </p>
                )}
              </CardContent>
            </Card>
          </li>
        ))}
      </ul>
    </section>
  );
}

function itemKey(item: StillMovingMarketItem, index: number): string {
  if (item.event_id != null) return `event-${item.event_id}`;
  const ticker = item.primary_ticker || item.top_mover;
  if (ticker) return `ticker-${ticker}-${index}`;
  return `idx-${index}`;
}

function LeadTicker({
  primary,
  fallback,
}: {
  primary: string | null;
  fallback: string | null;
}) {
  const ticker = primary || fallback || "";
  if (!ticker) {
    return (
      <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-on-surface-variant/55">
        —
      </span>
    );
  }
  return (
    <span className="font-mono text-[12px] font-semibold uppercase tracking-[0.06em] text-on-surface-variant">
      {ticker}
    </span>
  );
}

function PersistencePill({ signal }: { signal: string }) {
  return (
    <span className="inline-flex items-center rounded-full bg-primary/12 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.12em] text-primary">
      {signal}
    </span>
  );
}

function CautionPill({ label }: { label: string }) {
  if (!label) return null;
  return (
    <span
      className="inline-flex items-center rounded-full bg-surface-container-highest px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.12em] text-on-surface-variant/75"
      title={label}
    >
      Demo
    </span>
  );
}

export default StillMovingMarketPanel;
