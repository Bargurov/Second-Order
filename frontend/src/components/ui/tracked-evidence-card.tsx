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
 * Styled to the Slice 02 design package (`.mo-evi`): a charcoal card with
 * hairline rules, mono labels, citrine/jade accents, and a serif scope note.
 * Colours come from the design palette CSS vars set by the Market Overview
 * page root (charcoal surfaces, jade/citrine/rust). Kept deliberately
 * compact and phase-separated; identifiers in JetBrains Mono; no buy / sell /
 * trading-signal language — the card describes a closed historical evidence
 * layer, not a prescription.
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
  scopeStamp:       "fdr_scope_note · verbatim from /evidence/summary",
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
  className,
}: {
  eyebrow: string;
  count: string;
  countLabel: string;
  sub: string;
  detail?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("min-w-0", className)}>
      <div className="font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-[var(--so-ink-2)]">
        {eyebrow}
      </div>
      <div className="mt-1.5 flex items-baseline gap-2">
        <span className="font-[family-name:var(--so-display)] text-[26px] font-normal leading-none tabular-nums text-[var(--so-ink-0)]">
          {count}
        </span>
        <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-[var(--so-ink-3)]">
          {countLabel}
        </span>
      </div>
      <div className="mt-1 font-mono text-[10px] tracking-[0.02em] text-[var(--so-ink-3)]">
        {sub}
      </div>
      {detail ? (
        <div className="mt-2.5 border-t border-[color:var(--so-rule)] pt-2">
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
    tone === "positive" ? "text-[var(--so-jade-ink)]"
    : tone === "muted"  ? "text-[var(--so-ink-3)]"
    : "text-[var(--so-ink-1)]";
  return (
    <div className="flex items-baseline gap-2">
      <span className={cn(
        "font-[family-name:var(--so-display)] text-[14px] font-normal leading-none tabular-nums",
        toneClass,
      )}>
        {value}
      </span>
      <span className="font-mono text-[10px] leading-snug tracking-[0.02em] text-[var(--so-ink-3)]">
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
        className={className}
      >
        <Skeleton className="h-40 rounded-[4px] bg-[var(--so-bg-1)]" />
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
        "rounded-[4px] border border-[color:var(--so-rule)] bg-[var(--so-bg-1)] px-[18px] py-4",
        className,
      )}
    >
      {/* Header — `.mo-card-title` style: mono title left, eyebrow + schema
          right. */}
      <header className="mb-3.5 flex items-baseline justify-between gap-3">
        <h2 className="font-mono text-[11px] font-medium uppercase tracking-[0.14em] text-[var(--so-ink-1)]">
          {TRACKED_EVIDENCE_COPY.sectionTitle}
        </h2>
        <div className="shrink-0 font-mono text-[9.5px] uppercase tracking-[0.12em] text-[var(--so-ink-3)]">
          {TRACKED_EVIDENCE_COPY.sectionEyebrow} · schema {data.schema_version}
        </div>
      </header>

      {/* Phase 1 / Phase 2 side-by-side, split by a vertical hairline — the
          two FDR scopes are kept visually separate and never combined.
          Phase 2 carries an inline pass / fail breakdown beneath its count. */}
      <div className="grid grid-cols-2 divide-x divide-[color:var(--so-rule)]">
        <PhaseColumn
          className="pr-4"
          eyebrow={TRACKED_EVIDENCE_COPY.phase1Label}
          count={phase1Count}
          countLabel="rows"
          sub={TRACKED_EVIDENCE_COPY.phase1Sub}
        />
        <PhaseColumn
          className="pl-4"
          eyebrow={TRACKED_EVIDENCE_COPY.phase2Label}
          count={phase2Count}
          countLabel="tests"
          sub={TRACKED_EVIDENCE_COPY.phase2Sub}
          detail={
            phase2Absent ? (
              <span className="font-mono text-[10px] text-[var(--so-ink-3)]">
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

      {/* Deferred lessons — single quiet row beneath the two columns. */}
      <div className="mt-3 flex items-baseline gap-2 border-t border-[color:var(--so-rule)] pt-2.5">
        <span className="font-[family-name:var(--so-display)] text-[14px] font-normal leading-none tabular-nums text-[var(--so-ink-1)]">
          {deferred}
        </span>
        <span className="font-mono text-[10px] uppercase tracking-[0.06em] text-[var(--so-ink-3)]">
          {TRACKED_EVIDENCE_COPY.deferredLabel}
        </span>
      </div>

      {/* FDR scope caveat — a mono provenance stamp over the verbatim note. */}
      <div className="mt-3">
        <span className="mb-1 block font-mono text-[9px] uppercase tracking-[0.16em] text-[var(--so-ink-4)]">
          {TRACKED_EVIDENCE_COPY.scopeStamp}
        </span>
        <p className="font-[family-name:var(--so-serif)] text-[12px] italic leading-relaxed text-[var(--so-ink-3)]">
          {scopeNote}
        </p>
      </div>

      {/* Documentation references.  Rendered as muted label + repo-path
          captions rather than clickable links: the docs live inside this
          repo at the printed paths, and there is no public static host yet
          to point an <a> element at.  The path itself is the affordance —
          an operator opens the file in the repo.  Identifiers render in
          JetBrains Mono so they read as code-style references. */}
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 border-t border-[color:var(--so-rule)] pt-3 text-[11px]">
        <dt className="font-mono text-[10px] uppercase tracking-[0.12em] text-[var(--so-ink-2)]">
          {TRACKED_EVIDENCE_COPY.methodologyLabel} <span className="text-[var(--so-citrine)]">→</span>
        </dt>
        <dd className="m-0 break-all font-mono text-[10.5px] text-[var(--so-ink-3)]">
          {TRACKED_EVIDENCE_COPY.methodologyPath}
        </dd>
        <dt className="font-mono text-[10px] uppercase tracking-[0.12em] text-[var(--so-ink-2)]">
          {TRACKED_EVIDENCE_COPY.phaseHistoryLabel} <span className="text-[var(--so-citrine)]">→</span>
        </dt>
        <dd className="m-0 break-all font-mono text-[10.5px] text-[var(--so-ink-3)]">
          {TRACKED_EVIDENCE_COPY.phaseHistoryPath}
        </dd>
      </dl>

      {/* Error footer — muted rust, single line, only when the envelope
          reports errors.  ``ok`` is True iff ``errors`` is empty, so this
          branch is the same signal surfaced as a readable string. */}
      {firstError ? (
        <p className="mt-3 font-mono text-[11px] leading-snug text-[var(--so-rust-ink)]">
          {TRACKED_EVIDENCE_COPY.errorPrefix}
          {firstError}
        </p>
      ) : null}
    </section>
  );
}
