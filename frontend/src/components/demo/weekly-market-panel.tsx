/**
 * Weekly Market panel — presentational view for the canonicalized
 * Weekly Section C source.  Renders one card per item with the
 * canonicalization metadata (duplicate_count / grouped_event_ids)
 * and the source-attached caution_label.
 *
 * Read-only / props-only by construction
 * --------------------------------------
 *
 * The component performs no fetch, no mutation, and no derivation
 * beyond formatting.  The parent owns data acquisition (typically a
 * GET to ``/demo/weekly-market`` once that adapter lands).  No
 * claims of correctness, validation, alpha, or proof — items surface
 * with the caution_label the backend attached.
 */

import { cn } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export interface WeeklyMarketItem {
  event_id: number | null;
  headline: string;
  duplicate_count: number;
  grouped_event_ids: ReadonlyArray<number>;
  caution_label: string;
}

export interface WeeklyMarketPanelProps {
  items: ReadonlyArray<WeeklyMarketItem>;
  className?: string;
}

const EMPTY_COPY = "No weekly demo items currently.";
const EMPTY_DETAIL =
  "This is expected when the source has no canonicalized cards to surface — not an error.";

export function WeeklyMarketPanel({ items, className }: WeeklyMarketPanelProps) {
  if (items.length === 0) {
    return (
      <section className={cn("space-y-2", className)} aria-labelledby="demo-weekly-empty">
        <h2 id="demo-weekly-empty" className="sr-only">
          Weekly Market — empty
        </h2>
        <p className="text-sm text-on-surface-variant/80">{EMPTY_COPY}</p>
        <p className="text-xs leading-5 text-on-surface-variant/60">{EMPTY_DETAIL}</p>
      </section>
    );
  }

  return (
    <section className={cn("space-y-2", className)} aria-label="Weekly Market demo items">
      <ul className="grid gap-2">
        {items.map((item, index) => (
          <li key={itemKey(item, index)}>
            <Card className="border-border/70">
              <CardHeader className="gap-1 pb-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-on-surface-variant/70">
                    {item.event_id != null ? `#${item.event_id}` : "—"}
                  </span>
                  <CautionPill label={item.caution_label} />
                </div>
                <CardTitle className="text-sm leading-snug">{item.headline}</CardTitle>
              </CardHeader>
              <CardContent className="pt-0">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-on-surface-variant">
                  <DuplicateBadge count={item.duplicate_count} />
                  {item.grouped_event_ids.length > 0 && (
                    <GroupedIdsRow ids={item.grouped_event_ids} />
                  )}
                </div>
              </CardContent>
            </Card>
          </li>
        ))}
      </ul>
    </section>
  );
}

function itemKey(item: WeeklyMarketItem, index: number): string {
  if (item.event_id != null) return `event-${item.event_id}`;
  if (item.grouped_event_ids.length > 0) {
    return `grouped-${item.grouped_event_ids.join("-")}`;
  }
  return `idx-${index}`;
}

function DuplicateBadge({ count }: { count: number }) {
  const isCollapsed = count > 0;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.12em]",
        isCollapsed
          ? "bg-primary/15 text-primary"
          : "bg-surface-container-highest text-on-surface-variant/70",
      )}
    >
      <span className="tabular-nums">{count}</span>
      <span>duplicate{count === 1 ? "" : "s"}</span>
    </span>
  );
}

function GroupedIdsRow({ ids }: { ids: ReadonlyArray<number> }) {
  return (
    <span className="flex min-w-0 items-center gap-1.5">
      <span className="font-bold uppercase tracking-[0.12em] text-on-surface-variant/60">
        Grouped
      </span>
      <span className="truncate font-mono tabular-nums text-on-surface-variant/85">
        {ids.join(", ")}
      </span>
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

export default WeeklyMarketPanel;
