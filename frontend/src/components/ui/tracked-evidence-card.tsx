/**
 * TrackedEvidenceCard — compact institutional readout for the tracked
 * Phase 1 + Phase 2 evidence layer.
 *
 * Presentational only: no network calls, no React Query, no mutation
 * of the data it receives.  The component reads the envelope shape
 * pinned by ``routes/tracked_evidence.build_tracked_evidence_summary``
 * and surfaces the per-phase counts side by side.  Phase 1 and Phase 2
 * are independent FDR scopes and are never combined here — the
 * envelope's ``fdr_scope_note`` is rendered verbatim as a quiet caveat
 * below the counts.
 *
 * Aesthetic constraints (project CLAUDE.md / DESIGN.md):
 *
 *   - muted teal accent only; muted coral only for the error footer;
 *   - tonal contrast (raised-surface on section-surface) for the
 *     card boundary, never new border lines;
 *   - tabular numerics for every count;
 *   - Manrope for headlines, Inter for body, JetBrains Mono for
 *     identifiers;
 *   - tight radii (8px cap) and tight spacing;
 *   - no buy / sell / trading-signal language anywhere in the
 *     rendered output; the card describes a closed historical
 *     evidence layer, not a prescription.
 */

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { TrackedEvidenceSummaryResponse } from "@/lib/api";

// Copy constants — exported so the smoke test can pin verbatim strings
// without re-typing them.  Lowercase tokens kept conservative: the
// project bans "proof / proven / validated / alpha / prediction /
// predicted / interview / pitch" plus "confirms the mechanism" across
// public-facing surfaces.
export const TRACKED_EVIDENCE_COPY = {
  sectionEyebrow:    "Phase 1 + Phase 2",
  sectionTitle:     "Tracked evidence layer",
  phase1Label:      "Phase 1 freeze cohort",
  phase1Sub:        "frozen q-values · h = 1",
  phase2Label:      "Phase 2 BH/FDR pool",
  phase2Sub:        "closed pool · h = 1",
  phase2PassLabel:  "discoveries at q ≤ 0.05",
  phase2FailLabel:  "denominator members that did not pass the screen",
  deferredLabel:    "deferred methodology lessons",
  fallbackScopeNote:
    "Phase 1 and Phase 2 are independent FDR scopes. q-values are " +
    "not compared across phases.",
  phase2AbsentLine: "Phase 2 pool not declared in this snapshot.",
  errorPrefix:      "Tracked evidence layer unavailable: ",
  methodologyLabel: "Methodology",
  methodologyPath:
    "demo_artifacts/section_c_v2/phase_evidence_methodology.md",
  phaseHistoryLabel: "Phase history",
  phaseHistoryPath:
    "demo_artifacts/section_c_v2/phase_history.md",
} as const;

export interface TrackedEvidenceCardProps {
  /** Envelope returned by ``api.trackedEvidenceSummary()``.  ``null``
   *  / ``undefined`` collapses the card to the loading skeleton; tests
   *  pass the live shape directly. */
  data: TrackedEvidenceSummaryResponse | null | undefined;
  isLoading?: boolean;
  className?: string;
}

function _formatCount(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (!Number.isFinite(n)) return "—";
  return String(Math.trunc(n));
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function PhaseColumn({
  eyebrow,
  count,
  countLabel,
  sub,
  detail,
}: {
  eyebrow: string;
  count: string;
  countLabel: string;
  sub: string;
  detail?: React.ReactNode;
}) {
  return (
    <div className="rounded-md bg-surface-container px-4 py-3.5">
      <div className="mb-2 font-headline text-[10.5px] font-semibold uppercase tracking-[0.14em] text-on-surface-variant/60">
        {eyebrow}
      </div>
      <div className="flex items-baseline gap-2">
        <span className="font-headline text-[28px] font-semibold leading-none text-on-surface tabular-nums">
          {count}
        </span>
        <span className="text-[11px] uppercase tracking-[0.1em] text-on-surface-variant/55">
          {countLabel}
        </span>
      </div>
      <div className="mt-1 text-[11px] leading-snug text-on-surface-variant/50">
        {sub}
      </div>
      {detail ? (
        <div className="mt-3 border-t border-outline-variant/15 pt-2.5 text-[11.5px] leading-relaxed text-on-surface-variant/75">
          {detail}
        </div>
      ) : null}
    </div>
  );
}

function CountRow({
  value,
  tone,
  label,
}: {
  value: string;
  tone: "positive" | "muted" | "neutral";
  label: string;
}) {
  const toneClass =
    tone === "positive" ? "text-primary"
    : tone === "muted"  ? "text-on-surface-variant/55"
    : "text-on-surface/85";
  return (
    <div className="flex items-baseline gap-2">
      <span className={cn(
        "font-headline text-[14px] font-semibold leading-none tabular-nums",
        toneClass,
      )}>
        {value}
      </span>
      <span className="text-[11px] leading-snug text-on-surface-variant/60">
        {label}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Top-level card
// ---------------------------------------------------------------------------

export function TrackedEvidenceCard({
  data,
  isLoading = false,
  className,
}: TrackedEvidenceCardProps) {
  if (isLoading || data === null || data === undefined) {
    return (
      <section
        aria-label={TRACKED_EVIDENCE_COPY.sectionTitle}
        className={cn("mb-8", className)}
      >
        <Skeleton className="h-44 rounded-lg bg-surface-container-low" />
      </section>
    );
  }

  const summary = data.summary;
  const phase1Count = _formatCount(summary?.phase1_count);
  const phase2Count = _formatCount(summary?.phase2_count);
  const phase2Pass  = _formatCount(summary?.phase2_pass_count);
  const phase2Fail  = _formatCount(summary?.phase2_fail_count);
  const deferredRaw = summary?.deferred_count;
  const deferred    = deferredRaw === null || deferredRaw === undefined
    ? "—"
    : _formatCount(deferredRaw);

  const phase2Absent =
    typeof summary?.phase2_count === "number" && summary.phase2_count === 0;

  const scopeNote =
    data.fdr_scope_note && data.fdr_scope_note.trim().length > 0
      ? data.fdr_scope_note.trim()
      : TRACKED_EVIDENCE_COPY.fallbackScopeNote;

  const firstError = (data.errors ?? []).find(
    (e) => typeof e === "string" && e.trim().length > 0,
  );

  return (
    <section
      aria-label={TRACKED_EVIDENCE_COPY.sectionTitle}
      className={cn(
        "mb-8 rounded-lg bg-surface-container-low p-5",
        className,
      )}
    >
      {/* Header */}
      <header className="mb-4 flex items-baseline justify-between gap-3">
        <div className="min-w-0">
          <div className="font-headline text-[10px] font-bold uppercase tracking-[0.15em] text-on-surface-variant/45">
            {TRACKED_EVIDENCE_COPY.sectionEyebrow}
          </div>
          <h2 className="font-headline text-[13.5px] font-semibold tracking-[-0.005em] text-on-surface">
            {TRACKED_EVIDENCE_COPY.sectionTitle}
          </h2>
        </div>
        <div className="shrink-0 text-[10.5px] uppercase tracking-[0.12em] text-on-surface-variant/45">
          schema {data.schema_version}
        </div>
      </header>

      {/* Two-column grid: Phase 1 left, Phase 2 right.  Phase 2 column
          carries an inline pass / fail breakdown.  Deferred lessons sit
          beneath as a single quiet row so the methodology record stays
          complete without competing with the per-phase columns. */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <PhaseColumn
          eyebrow={TRACKED_EVIDENCE_COPY.phase1Label}
          count={phase1Count}
          countLabel="rows"
          sub={TRACKED_EVIDENCE_COPY.phase1Sub}
        />
        <PhaseColumn
          eyebrow={TRACKED_EVIDENCE_COPY.phase2Label}
          count={phase2Count}
          countLabel="tests"
          sub={TRACKED_EVIDENCE_COPY.phase2Sub}
          detail={
            phase2Absent ? (
              <span className="text-on-surface-variant/55">
                {TRACKED_EVIDENCE_COPY.phase2AbsentLine}
              </span>
            ) : (
              <div className="flex flex-col gap-1.5">
                <CountRow
                  value={phase2Pass}
                  tone="positive"
                  label={TRACKED_EVIDENCE_COPY.phase2PassLabel}
                />
                <CountRow
                  value={phase2Fail}
                  tone="muted"
                  label={TRACKED_EVIDENCE_COPY.phase2FailLabel}
                />
              </div>
            )
          }
        />
      </div>

      {/* Deferred lessons — single line beneath the two columns. */}
      <div className="mt-3 flex items-baseline gap-2 rounded-md bg-surface-container px-4 py-3">
        <span className="font-headline text-[14px] font-semibold leading-none text-on-surface/80 tabular-nums">
          {deferred}
        </span>
        <span className="text-[11.5px] leading-snug text-on-surface-variant/65">
          {TRACKED_EVIDENCE_COPY.deferredLabel}
        </span>
      </div>

      {/* FDR scope caveat — verbatim from the envelope when present. */}
      <p className="mt-4 text-[11.5px] leading-relaxed text-on-surface-variant/55">
        {scopeNote}
      </p>

      {/* Documentation references.  Rendered as muted label + path
          captions rather than clickable links: the docs live inside
          this repo at the printed paths, and there is no public
          static host yet to point an &lt;a&gt; element at.  The path
          itself is the affordance — an operator opens the file in
          the repo.  Identifiers are rendered in JetBrains Mono so
          they read as code-style references, not as call-to-action
          buttons. */}
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[11px]">
        <dt className="font-headline text-[10.5px] font-bold uppercase tracking-[0.12em] text-on-surface-variant/40">
          {TRACKED_EVIDENCE_COPY.methodologyLabel}
        </dt>
        <dd className="m-0 break-all font-mono text-[11px] text-on-surface-variant/65">
          {TRACKED_EVIDENCE_COPY.methodologyPath}
        </dd>
        <dt className="font-headline text-[10.5px] font-bold uppercase tracking-[0.12em] text-on-surface-variant/40">
          {TRACKED_EVIDENCE_COPY.phaseHistoryLabel}
        </dt>
        <dd className="m-0 break-all font-mono text-[11px] text-on-surface-variant/65">
          {TRACKED_EVIDENCE_COPY.phaseHistoryPath}
        </dd>
      </dl>

      {/* Error footer — muted coral, single line, only when the
          envelope reports errors.  ``ok`` is True iff ``errors`` is
          empty, so this branch is the same signal surfaced as a
          readable string. */}
      {firstError ? (
        <p className="mt-3 text-[11.5px] leading-snug text-error-dim">
          {TRACKED_EVIDENCE_COPY.errorPrefix}
          {firstError}
        </p>
      ) : null}
    </section>
  );
}
