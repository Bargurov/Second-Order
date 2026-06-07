/**
 * Evidence Coverage card (R4C).
 *
 * Makes the project's denominators visible in Market Overview Section 3
 * WITHOUT pretending the three eligibility gates are one linear funnel.
 * The card composes data that is already fetched on the page — it adds no
 * network call, no backend, and no new metric:
 *
 *   Band A — track-record coverage: the screened denominator and its
 *     resolved breakdown, read from ``GET /stats/track-record``.
 *   Band B — closed FDR pools: Phase 1 / Phase 2 counts (and pass / fail),
 *     read from the tracked ``GET /evidence/summary`` envelope.  Phase 1 and
 *     Phase 2 keep their own denominators and are never summed.  The verbatim
 *     ``fdr_scope_note`` is NOT duplicated here — TrackedEvidenceCard renders
 *     it once authoritatively; non-claim #3 carries the equivalent warning.
 *
 * The benchmark-adjusted event-study readiness count is a SEPARATE gate and
 * is deliberately not shown here (it needs a later read-only endpoint); the
 * card states that absence so it is honest rather than silent.
 *
 * Copy carries no buy / sell / trade / signal / alpha framing and avoids
 * proof / proven / confirmed / validated as positive claims (per the frontend
 * copy rules) — "Any-supporting" is used for the track-record count, matching
 * the Q3 honest framing in TrackRecordStrip.
 */
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import type { TrackRecord, TrackedEvidenceSummaryResponse } from "@/lib/api";

export const EVIDENCE_COVERAGE_COPY = {
  sectionTitle: "Evidence coverage",
  sectionEyebrow: "denominators · separate gates",
  bandACoverageLabel: "Track-record coverage",
  bandBPoolsLabel: "Closed FDR pools",
  eventStudyDeferredNote:
    "Benchmark-adjusted event-study readiness is tracked separately and is not included in this card.",
  nonClaims: [
    "Coverage counts are descriptive eligibility counts, not statistical inference.",
    "Denominators differ by gate and data availability.",
    "Closed FDR pools are separate curated cohorts, not a filter of all screened events.",
  ],
} as const;

interface EvidenceCoverageCardProps {
  trackRecord?: TrackRecord;
  evidence?: TrackedEvidenceSummaryResponse;
  isLoading?: boolean;
  className?: string;
}

export function EvidenceCoverageCard({
  trackRecord,
  evidence,
  isLoading = false,
  className,
}: EvidenceCoverageCardProps) {
  if (isLoading) {
    return (
      <section aria-label={EVIDENCE_COVERAGE_COPY.sectionTitle} className={className}>
        <Skeleton className="h-40 rounded-[4px] bg-[var(--so-bg-1)]" />
      </section>
    );
  }

  const hasA = !!trackRecord && trackRecord.total > 0;
  const summary = evidence?.summary;
  const hasB = !!evidence && !!summary;
  // No screened denominator → no card.  The FDR artifacts are tracked files,
  // so /evidence/summary returns counts even on an empty DB; without Band A
  // the card would be a denominator-less echo of TrackedEvidenceCard below.
  if (!hasA) return null;

  const resolved = trackRecord!.validated + trackRecord!.contradicted;
  const deferredRaw = summary?.deferred_count;

  return (
    <section
      aria-label={EVIDENCE_COVERAGE_COPY.sectionTitle}
      className={cn(
        "rounded-[4px] border border-[color:var(--so-rule)] bg-[var(--so-bg-1)] px-[18px] py-4",
        className,
      )}
    >
      <header className="mb-3.5 flex items-baseline justify-between gap-3">
        <h2 className="font-mono text-[11px] font-medium uppercase tracking-[0.14em] text-[var(--so-ink-1)]">
          {EVIDENCE_COVERAGE_COPY.sectionTitle}
        </h2>
        <div className="shrink-0 font-mono text-[9.5px] uppercase tracking-[0.12em] text-[var(--so-ink-3)]">
          {EVIDENCE_COVERAGE_COPY.sectionEyebrow}
        </div>
      </header>

      {/* Two separated bands with DIFFERENT denominators, split by a hairline
          so a reader never reads track-record coverage and the FDR pools as
          one survivorship funnel. */}
      <div className="flex flex-col divide-y divide-[color:var(--so-rule)]">
        {hasA && (
          <div className="pb-3">
            <div className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-[var(--so-ink-2)]">
              {EVIDENCE_COVERAGE_COPY.bandACoverageLabel}
            </div>
            <div className="flex items-baseline gap-2">
              <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--so-ink-3)]">
                Screened
              </span>
              <span className="font-[family-name:var(--so-display)] text-[22px] font-normal leading-none tabular-nums text-[var(--so-ink-1)]">
                {trackRecord!.total}
              </span>
            </div>
            <div className="mt-1.5 flex flex-wrap items-baseline gap-x-3 gap-y-1 font-mono text-[10px] tracking-[0.02em] text-[var(--so-ink-3)]">
              <span>
                <span className="tabular-nums text-[var(--so-ink-1)]">{resolved}</span> resolved
              </span>
              <span>
                <span className="tabular-nums text-[var(--so-jade-ink)]">{trackRecord!.validated}</span> any-supporting
              </span>
              <span>
                <span className="tabular-nums text-[var(--so-rust-ink)]">{trackRecord!.contradicted}</span> contradicted
              </span>
              <span>
                <span className="tabular-nums text-[var(--so-amber)]">{trackRecord!.unresolved}</span> unresolved
              </span>
            </div>
          </div>
        )}

        {hasB && (
          <div className={cn("pt-3", !hasA && "pt-0")}>
            <div className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-[var(--so-ink-2)]">
              {EVIDENCE_COVERAGE_COPY.bandBPoolsLabel}
            </div>
            <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 font-mono text-[10px] tracking-[0.02em] text-[var(--so-ink-3)]">
              <span>
                Phase 1 · <span className="tabular-nums text-[var(--so-ink-1)]">{summary!.phase1_count}</span> frozen
              </span>
              <span>
                Phase 2 · <span className="tabular-nums text-[var(--so-ink-1)]">{summary!.phase2_count}</span> tested ·{" "}
                <span className="tabular-nums text-[var(--so-jade-ink)]">{summary!.phase2_pass_count}</span> pass ·{" "}
                <span className="tabular-nums text-[var(--so-ink-3)]">{summary!.phase2_fail_count}</span> fail
              </span>
              {deferredRaw !== null && deferredRaw !== undefined && (
                <span>
                  <span className="tabular-nums text-[var(--so-ink-1)]">{deferredRaw}</span> deferred
                </span>
              )}
            </div>
            {/* The verbatim fdr_scope_note is rendered once, authoritatively, by
                TrackedEvidenceCard below; non-claim #3 carries the equivalent
                separation warning here so the prose is not duplicated. */}
          </div>
        )}
      </div>

      {/* Event-study readiness is a separate, benchmark-adjusted gate — stated,
          not silently omitted. */}
      <p className="mt-3 border-t border-[color:var(--so-rule)] pt-2.5 font-mono text-[10px] leading-relaxed tracking-[0.02em] text-[var(--so-ink-3)]">
        {EVIDENCE_COVERAGE_COPY.eventStudyDeferredNote}
      </p>

      <ul className="mt-2 space-y-1">
        {EVIDENCE_COVERAGE_COPY.nonClaims.map((line) => (
          <li
            key={line}
            className="font-[family-name:var(--so-serif)] text-[11px] font-light italic leading-relaxed text-[var(--so-ink-3)]"
          >
            {line}
          </li>
        ))}
      </ul>
    </section>
  );
}
