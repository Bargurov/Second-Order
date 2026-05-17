/**
 * Daily Market panel — presentational view for the artifact-backed
 * Daily Section C source.  Renders one card per item with the four
 * artifact-backed fields the gate enforces (mechanism_family /
 * primary_ticker / benchmark_ticker), the operator-supplied
 * candidate_id, and the source-attached caution_label.
 *
 * Read-only / props-only by construction
 * --------------------------------------
 *
 * The component performs no fetch, no mutation, and no derivation
 * beyond formatting.  The parent owns data acquisition (typically a
 * GET to ``/demo/daily-market`` once that adapter lands).  No claims
 * of correctness, validation, alpha, or proof — items surface with
 * the caution_label the backend attached so the operator sees the
 * demo qualifier before any inclusion decision.
 */

import { cn } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export interface DailyMarketItem {
  candidate_id: string;
  headline: string;
  mechanism_family: string;
  primary_ticker: string;
  benchmark_ticker: string;
  caution_label: string;
}

export interface DailyMarketPanelProps {
  items: ReadonlyArray<DailyMarketItem>;
  /**
   * Number of artifact files the source skipped during review (e.g.
   * missing required fields, unreadable JSON).  When ``undefined`` the
   * panel falls back to count-free gate-status phrasing.  Skipped
   * artifacts are artifact-level review skips — they are not failed,
   * rejected, or "bad" candidates.
   */
  skippedArtifactsCount?: number;
  className?: string;
}

const EMPTY_COPY =
  "No operator-reviewed, artifact-backed Daily candidates yet.";

export function DailyMarketPanel({
  items,
  skippedArtifactsCount,
  className,
}: DailyMarketPanelProps) {
  if (items.length === 0) {
    return (
      <section className={cn("space-y-2", className)} aria-labelledby="demo-daily-empty">
        <h2 id="demo-daily-empty" className="sr-only">
          Daily Market — empty
        </h2>
        <GateStatus
          admittedCount={0}
          skippedCount={skippedArtifactsCount}
        />
        <p className="text-sm text-on-surface-variant/80">{EMPTY_COPY}</p>
      </section>
    );
  }

  return (
    <section className={cn("space-y-2", className)} aria-label="Daily Market demo items">
      <GateStatus
        admittedCount={items.length}
        skippedCount={skippedArtifactsCount}
      />
      <ul className="grid gap-2">
        {items.map((item) => (
          <li key={item.candidate_id}>
            <Card className="border-border/70">
              <CardHeader className="gap-1 pb-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-on-surface-variant/70">
                    {item.candidate_id}
                  </span>
                  <CautionPill label={item.caution_label} />
                </div>
                <CardTitle className="text-sm leading-snug">{item.headline}</CardTitle>
              </CardHeader>
              <CardContent className="pt-0">
                <dl className="grid grid-cols-3 gap-2 text-[11px]">
                  <MetaField label="Mechanism" value={item.mechanism_family} />
                  <MetaField label="Primary" value={item.primary_ticker} mono />
                  <MetaField label="Benchmark" value={item.benchmark_ticker} mono />
                </dl>
              </CardContent>
            </Card>
          </li>
        ))}
      </ul>
    </section>
  );
}

function GateStatus({
  admittedCount,
  skippedCount,
}: {
  admittedCount: number;
  skippedCount: number | undefined;
}) {
  if (skippedCount === undefined) {
    return (
      <p
        className="text-[11px] leading-5 text-on-surface-variant/70"
        data-testid="daily-gate-status"
      >
        Showing reviewed artifact-backed Daily items.
      </p>
    );
  }
  const itemLabel = admittedCount === 1 ? "item" : "items";
  const artifactLabel = skippedCount === 1 ? "artifact" : "artifacts";
  return (
    <p
      className="text-[11px] leading-5 text-on-surface-variant/70"
      data-testid="daily-gate-status"
    >
      Showing{" "}
      <span className="font-mono tabular-nums text-on-surface-variant">
        {admittedCount}
      </span>{" "}
      reviewed artifact-backed Daily {itemLabel}
      {skippedCount > 0 && (
        <>
          ;{" "}
          <span className="font-mono tabular-nums text-on-surface-variant">
            {skippedCount}
          </span>{" "}
          {artifactLabel} skipped during artifact review
        </>
      )}
      .
    </p>
  );
}

function MetaField({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="min-w-0">
      <dt className="font-bold uppercase tracking-[0.12em] text-on-surface-variant/60">
        {label}
      </dt>
      <dd
        className={cn(
          "truncate text-on-surface-variant",
          mono && "font-mono tabular-nums",
        )}
        title={value || undefined}
      >
        {value || "—"}
      </dd>
    </div>
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

export default DailyMarketPanel;
