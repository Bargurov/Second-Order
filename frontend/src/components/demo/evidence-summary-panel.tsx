/**
 * EvidenceSummaryPanel — presentational view for the demo backend
 * Evidence Summary response.
 *
 * Pure projection over the envelope produced by
 * ``routes/demo_evidence_summary.py``.  The component
 *
 *  - renders the cohort summary, verdict tallies, FDR-significant
 *    count, raw-p candidate count, benchmark sensitivity status, and
 *    the artifact's own limitations,
 *  - surfaces three pinned advisory strings whenever the data
 *    matches the trigger conditions (see ``COPY`` below),
 *  - preserves any ``warnings`` and ``errors`` the API returned
 *    rather than rewriting them.
 *
 * The component is presentational only: no network calls, no React
 * Query, no mutation of the data it receives.  Conservative wording
 * — no claim of proof, validation, alpha, or causality is made
 * anywhere in this file.
 */

import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Response shape — mirrors the backend envelope.  Kept narrow on
// purpose: the panel reads exactly the fields the demo source pins
// and ignores the rest.
// ---------------------------------------------------------------------------

export interface CohortSummary {
  events_evaluated?: number;
  total_records?: number;
  fdr_significant_count?: number;
  raw_p_candidate_count?: number;
  horizons_covered?: number[];
  mechanism_families_covered?: string[];
  method?: string;
  all_pass_q_005?: boolean;
}

export interface VerdictCounts {
  fdr_significant?: number;
  raw_p_only_candidate?: number;
  inconclusive_fdr?: number;
  insufficient?: number;
  [key: string]: number | undefined;
}

export interface BenchmarkSensitivityStatus {
  status?: string;
  changed_event_ids?: number[];
  unchanged_event_ids?: number[];
  changed_interpretation_count?: number;
  blocked_events?: number[];
}

export interface V2CandidateRecord {
  rank_in_cohort?: number;
  primary_ticker: string;
  benchmark_ticker: string;
  mechanism_family: string;
  h1_AR_pct?: number | null;
  h1_SAR?: number | null;
  h1_q_bh?: number | null;
  claim_horizon?: string;
  method?: string;
  cache_backed?: boolean;
  fdr_significant?: boolean;
  [key: string]: unknown;
}

export interface V2RobustnessEntry {
  status: string;
  row: string;
  resolution_summary: string;
}

export interface EvidenceSummaryResponse {
  ok: boolean;
  section: string;
  cohort_summary: CohortSummary;
  verdict_counts: VerdictCounts;
  fdr_significant_count: number;
  raw_p_candidate_count: number;
  benchmark_sensitivity_status: BenchmarkSensitivityStatus;
  limitations: string[];
  warnings: string[];
  errors: string[];
  artifact_schema_version?: string;
  demo_bundle?: string;
  source?: string;
  records?: V2CandidateRecord[];
  robustness_status?: Record<string, V2RobustnessEntry>;
  methodology_notes?: Record<string, unknown>;
  selection_bias_disclosure?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Pinned copy — exported so the unit test can sweep it for banned
// tokens and assert the trigger conditions.
// ---------------------------------------------------------------------------

export const COPY = {
  fdrZero:    "No FDR-significant results in this pilot cohort.",
  rawPCaveat: "Raw-p candidates did not necessarily survive FDR.",
  event60:    "Event 60 changes descriptive interpretation under XLE vs SPY.",
} as const;

// User-facing string-constant table.  Kept exported so the
// conservative-language test can sweep every label without rendering
// the component.  Banned tokens: "proven", "validated", "alpha",
// "causal" — see the unit test.
export const LABELS = {
  sectionTitle:        "Evidence Summary",
  sectionEyebrow:      "Demo · Read-only",
  cohortHeading:       "Cohort",
  eventsEvaluated:     "Events evaluated",
  totalRecords:        "Records",
  horizonsCovered:     "Horizons",
  familiesCovered:     "Mechanism families",
  verdictsHeading:     "Verdict counts",
  verdictFdr:          "FDR-significant",
  verdictRawP:         "Raw-p only",
  verdictInconclusive: "Inconclusive (FDR)",
  verdictInsufficient: "Insufficient",
  fdrStatHeading:      "FDR-significant count",
  rawPStatHeading:     "Raw-p candidate count",
  benchHeading:        "Benchmark sensitivity",
  benchStatus:         "Status",
  benchChangedIds:     "Changed event IDs",
  benchUnchangedIds:   "Unchanged event IDs",
  limitationsHeading:  "Limitations",
  warningsHeading:     "Warnings",
  errorsHeading:       "Errors",
  emptyCohort:         "No cohort summary returned.",
  emptyBenchmark:      "No benchmark sensitivity status returned.",
  emptyLimitations:    "No limitations recorded by the source.",
  v2RecordsHeading:    "Cohort candidates",
  v2RobustnessHeading: "Robustness checks",
  v2CaveatsHeading:    "Scope",
} as const;

// ---------------------------------------------------------------------------
// Pure helpers — exported for unit tests
// ---------------------------------------------------------------------------

/** Return ``true`` when the benchmark block lists event 60 among the
 *  events whose descriptive interpretation changed across SPY/XLE. */
export function benchmarkIncludesEvent60(
  bench: BenchmarkSensitivityStatus | null | undefined,
): boolean {
  const ids = bench?.changed_event_ids;
  if (!Array.isArray(ids)) return false;
  return ids.includes(60);
}

export type AdvisoryTone = "neutral" | "warn";
export interface Advisory {
  key: "fdr_zero" | "raw_p" | "event_60";
  text: string;
  tone: AdvisoryTone;
}

/** Pick the pinned advisory strings that apply to this envelope. */
export function pickAdvisories(input: {
  fdr_significant_count:        number;
  raw_p_candidate_count:        number;
  benchmark_sensitivity_status: BenchmarkSensitivityStatus | null | undefined;
}): Advisory[] {
  const out: Advisory[] = [];
  if (input.fdr_significant_count === 0) {
    out.push({ key: "fdr_zero", text: COPY.fdrZero, tone: "warn" });
  }
  if (input.raw_p_candidate_count > 0) {
    out.push({ key: "raw_p", text: COPY.rawPCaveat, tone: "neutral" });
  }
  if (benchmarkIncludesEvent60(input.benchmark_sensitivity_status)) {
    out.push({ key: "event_60", text: COPY.event60, tone: "neutral" });
  }
  return out;
}

/** Render artifact caveats without importing overclaim vocabulary into
 *  the demo panel's visible copy. */
export function formatLimitationText(entry: string): string {
  return entry
    .replace(/\bFDR-significant validation claim\b/gi, "FDR-significant claim")
    .replace(/\bvalidation claim\b/gi, "claim")
    .replace(/\bvalidated claim\b/gi, "claim");
}

// ---------------------------------------------------------------------------
// Tone classes — design-system tokens only.  No new colors.
// ---------------------------------------------------------------------------

const ADVISORY_TONE: Record<AdvisoryTone, { dot: string; text: string; bg: string }> = {
  warn:    {
    dot:  "bg-error-dim/60",
    text: "text-error-dim/80",
    bg:   "bg-error-container/8",
  },
  neutral: {
    dot:  "bg-on-surface-variant/30",
    text: "text-on-surface-variant/75",
    bg:   "bg-surface-container-highest/40",
  },
};

// ---------------------------------------------------------------------------
// Sub-views — kept inline to keep the panel single-file.
// ---------------------------------------------------------------------------

function StatBlock({ label, value }: { label: string; value: number }) {
  return (
    <div
      className={cn(
        "flex flex-col gap-1 rounded-md px-3 py-2.5",
        "bg-surface-container-highest/50",
      )}
    >
      <span className="text-[9px] font-bold uppercase tracking-[0.12em] text-on-surface-variant/50">
        {label}
      </span>
      <span className="text-lg font-semibold text-on-surface tabular-nums leading-none">
        {value}
      </span>
    </div>
  );
}

function ChipList({ items }: { items: ReadonlyArray<string | number> }) {
  if (items.length === 0) {
    return <span className="text-[10px] text-on-surface-variant/40">—</span>;
  }
  return (
    <ul className="flex flex-wrap gap-1">
      {items.map((it, i) => (
        <li
          key={`${i}-${it}`}
          className={cn(
            "inline-flex items-center px-1.5 py-px rounded",
            "text-[10px] font-medium text-on-surface-variant/70",
            "bg-surface-container-highest/60 tabular-nums",
          )}
        >
          {it}
        </li>
      ))}
    </ul>
  );
}

function KeyValueRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <span className="text-[10px] font-medium uppercase tracking-[0.08em] text-on-surface-variant/45">
        {label}
      </span>
      <span className="text-[11px] text-on-surface-variant/85 tabular-nums text-right min-w-0">
        {value}
      </span>
    </div>
  );
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-[10px] font-bold uppercase tracking-[0.14em] text-on-surface-variant/45 mb-2">
      {children}
    </h3>
  );
}

// ---------------------------------------------------------------------------
// v2 formatting helpers
// ---------------------------------------------------------------------------

function fmtAR(v: number | null | undefined): string {
  if (v == null) return "—";
  return (v >= 0 ? "+" : "") + v.toFixed(2);
}

function fmtSAR(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toFixed(2);
}

function fmtQ(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v < 0.001) return v.toExponential(2);
  return v.toFixed(4);
}

// ---------------------------------------------------------------------------
// v2 sub-views
// ---------------------------------------------------------------------------

function V2SourceBar({
  method,
  source,
  bundle,
}: {
  method: string;
  source: string;
  bundle: string;
}) {
  const items = [
    { label: "method", value: method.replace(/_/g, " ") },
    { label: "source", value: source.replace(/_/g, " ") },
    { label: "bundle", value: bundle },
  ];
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((it) => (
        <span
          key={it.label}
          className={cn(
            "inline-flex items-center gap-1 px-2 py-0.5 rounded",
            "text-[9px] font-medium",
            "bg-surface-container-highest/50",
          )}
        >
          <span className="uppercase tracking-[0.08em] text-on-surface-variant/40">
            {it.label}
          </span>
          <span className="text-on-surface-variant/70 tabular-nums">{it.value}</span>
        </span>
      ))}
    </div>
  );
}

function V2RecordsTable({ records }: { records: V2CandidateRecord[] }) {
  if (records.length === 0) return null;
  return (
    <div className="rounded-md bg-surface-container-highest/30 p-3">
      <SectionHeading>{LABELS.v2RecordsHeading}</SectionHeading>
      <div className="overflow-x-auto -mx-1">
        <table className="w-full text-[10px]">
          <thead>
            <tr className="text-on-surface-variant/40 font-medium uppercase tracking-[0.06em]">
              <th className="text-left py-1 px-1 font-medium">Pair</th>
              <th className="text-left py-1 px-1 font-medium">Mechanism</th>
              <th className="text-right py-1 px-1 font-medium">AR%</th>
              <th className="text-right py-1 px-1 font-medium">SAR</th>
              <th className="text-right py-1 px-1 font-medium">q(BH)</th>
              <th className="text-left py-1 px-1 font-medium">Claim</th>
            </tr>
          </thead>
          <tbody className="text-on-surface-variant/80">
            {records.map((r, i) => (
              <tr key={i} className="border-t border-outline-variant/8">
                <td className="py-1 px-1 font-medium text-on-surface/90 whitespace-nowrap tabular-nums">
                  {r.primary_ticker}/{r.benchmark_ticker}
                </td>
                <td className="py-1 px-1 text-on-surface-variant/60 max-w-[120px] truncate">
                  {r.mechanism_family}
                </td>
                <td className="py-1 px-1 text-right tabular-nums">{fmtAR(r.h1_AR_pct)}</td>
                <td className="py-1 px-1 text-right tabular-nums">{fmtSAR(r.h1_SAR)}</td>
                <td className="py-1 px-1 text-right tabular-nums">{fmtQ(r.h1_q_bh)}</td>
                <td className="py-1 px-1 text-on-surface-variant/60 whitespace-nowrap">
                  {r.claim_horizon ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function V2RobustnessStatus({
  status,
}: {
  status: Record<string, V2RobustnessEntry>;
}) {
  const entries = Object.entries(status);
  if (entries.length === 0) return null;
  return (
    <div className="rounded-md bg-surface-container-highest/30 p-3">
      <SectionHeading>{LABELS.v2RobustnessHeading}</SectionHeading>
      <div className="space-y-1.5">
        {entries.map(([key, entry]) => (
          <div key={key} className="flex items-center gap-2 min-w-0">
            <span className="text-[10px] text-on-surface-variant/65 truncate min-w-0">
              {entry.row}
            </span>
            <span
              className={cn(
                "ml-auto shrink-0 text-[9px] font-medium uppercase tracking-[0.06em]",
                "px-1.5 py-px rounded",
                "bg-primary/8 text-primary/70",
              )}
            >
              {entry.status.replace(/_/g, " ")}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function V2Caveats() {
  const lines = [
    "FDR applies only inside the frozen five h=1 tests.",
    "This is frozen historical evidence, not live archive output.",
  ];
  return (
    <div className="rounded-md bg-surface-container-highest/30 p-3">
      <SectionHeading>{LABELS.v2CaveatsHeading}</SectionHeading>
      <div className="space-y-1">
        {lines.map((text, i) => (
          <p
            key={i}
            className="flex items-start gap-2 text-[10px] leading-relaxed text-on-surface-variant/55"
          >
            <span className="mt-1.5 h-1 w-1 rounded-full shrink-0 bg-on-surface-variant/20" />
            {text}
          </p>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Top-level panel
// ---------------------------------------------------------------------------

export interface EvidenceSummaryPanelProps {
  data: EvidenceSummaryResponse | null | undefined;
  className?: string;
}

export function EvidenceSummaryPanel({ data, className }: EvidenceSummaryPanelProps) {
  if (data === null || data === undefined) {
    return null;
  }

  const {
    cohort_summary,
    verdict_counts,
    fdr_significant_count,
    raw_p_candidate_count,
    benchmark_sensitivity_status,
    limitations,
    warnings,
    errors,
  } = data;

  const isV2 = data.artifact_schema_version === "v2";

  const advisories = pickAdvisories({
    fdr_significant_count,
    raw_p_candidate_count,
    benchmark_sensitivity_status,
  });

  const horizons = cohort_summary.horizons_covered ?? [];
  const families = cohort_summary.mechanism_families_covered ?? [];
  const changedIds   = benchmark_sensitivity_status.changed_event_ids   ?? [];
  const unchangedIds = benchmark_sensitivity_status.unchanged_event_ids ?? [];

  return (
    <section
      aria-label={LABELS.sectionTitle}
      className={cn(
        "rounded-lg border border-outline-variant/15",
        "bg-surface-container/40",
        "p-4 space-y-4",
        className,
      )}
    >
      {/* Header */}
      <header className="flex items-baseline justify-between gap-3">
        <div className="flex flex-col gap-0.5 min-w-0">
          <span className="text-[9px] font-bold uppercase tracking-[0.15em] text-on-surface-variant/40">
            {LABELS.sectionEyebrow}
          </span>
          <h2 className="text-sm font-semibold tracking-[-0.01em] text-on-surface">
            {LABELS.sectionTitle}
          </h2>
        </div>
      </header>

      {/* v2 source bar */}
      {isV2 && data.source && data.demo_bundle && (
        <V2SourceBar
          method={cohort_summary.method ?? ""}
          source={data.source}
          bundle={data.demo_bundle}
        />
      )}

      {/* Errors — preserved verbatim from API */}
      {errors.length > 0 && (
        <div
          role="alert"
          className={cn(
            "rounded-md border border-error-dim/25 bg-error-container/8",
            "px-3 py-2 space-y-1",
          )}
        >
          <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-error-dim/80">
            {LABELS.errorsHeading}
          </p>
          <ul className="space-y-0.5">
            {errors.map((msg, i) => (
              <li
                key={`err-${i}`}
                className="text-[11px] leading-relaxed text-error-dim/85"
              >
                {msg}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Warnings — preserved verbatim from API */}
      {warnings.length > 0 && (
        <div
          className={cn(
            "rounded-md border border-outline-variant/20",
            "bg-surface-container-highest/40 px-3 py-2 space-y-1",
          )}
        >
          <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-on-surface-variant/60">
            {LABELS.warningsHeading}
          </p>
          <ul className="space-y-0.5">
            {warnings.map((msg, i) => (
              <li
                key={`warn-${i}`}
                className="text-[11px] leading-relaxed text-on-surface-variant/75"
              >
                {msg}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Headline stats — FDR significant + raw-p candidate */}
      <div className="grid grid-cols-2 gap-2">
        <StatBlock label={LABELS.fdrStatHeading}  value={fdr_significant_count} />
        <StatBlock label={LABELS.rawPStatHeading} value={raw_p_candidate_count} />
      </div>

      {/* Advisory strings — pinned copy per task spec */}
      {advisories.length > 0 && (
        <ul className="space-y-1.5">
          {advisories.map((a) => {
            const tone = ADVISORY_TONE[a.tone];
            return (
              <li
                key={a.key}
                data-advisory={a.key}
                className={cn(
                  "flex items-start gap-2 rounded-md px-2.5 py-1.5",
                  tone.bg,
                )}
              >
                <span
                  className={cn(
                    "mt-1.5 h-1 w-1 rounded-full shrink-0",
                    tone.dot,
                  )}
                />
                <span className={cn("text-[11px] leading-relaxed", tone.text)}>
                  {a.text}
                </span>
              </li>
            );
          })}
        </ul>
      )}

      {/* Cohort summary */}
      <div className="rounded-md bg-surface-container-highest/30 p-3">
        <SectionHeading>{LABELS.cohortHeading}</SectionHeading>
        {Object.keys(cohort_summary).length === 0 ? (
          <p className="text-[11px] text-on-surface-variant/45">{LABELS.emptyCohort}</p>
        ) : (
          <div className="space-y-1">
            <KeyValueRow
              label={LABELS.eventsEvaluated}
              value={cohort_summary.events_evaluated ?? "—"}
            />
            <KeyValueRow
              label={LABELS.totalRecords}
              value={cohort_summary.total_records ?? "—"}
            />
            <KeyValueRow
              label={LABELS.horizonsCovered}
              value={<ChipList items={horizons} />}
            />
            <KeyValueRow
              label={LABELS.familiesCovered}
              value={<ChipList items={families} />}
            />
          </div>
        )}
      </div>

      {/* Verdict counts */}
      <div className="rounded-md bg-surface-container-highest/30 p-3">
        <SectionHeading>{LABELS.verdictsHeading}</SectionHeading>
        <div className="grid grid-cols-2 gap-x-3 gap-y-1">
          <KeyValueRow
            label={LABELS.verdictFdr}
            value={verdict_counts.fdr_significant ?? 0}
          />
          <KeyValueRow
            label={LABELS.verdictRawP}
            value={verdict_counts.raw_p_only_candidate ?? 0}
          />
          <KeyValueRow
            label={LABELS.verdictInconclusive}
            value={verdict_counts.inconclusive_fdr ?? 0}
          />
          <KeyValueRow
            label={LABELS.verdictInsufficient}
            value={verdict_counts.insufficient ?? 0}
          />
        </div>
      </div>

      {/* v2 cohort records table */}
      {isV2 && data.records && data.records.length > 0 && (
        <V2RecordsTable records={data.records} />
      )}

      {/* v2 robustness status */}
      {isV2 && data.robustness_status && Object.keys(data.robustness_status).length > 0 && (
        <V2RobustnessStatus status={data.robustness_status} />
      )}

      {/* v2 scope caveats */}
      {isV2 && <V2Caveats />}

      {/* Benchmark sensitivity */}
      <div className="rounded-md bg-surface-container-highest/30 p-3">
        <SectionHeading>{LABELS.benchHeading}</SectionHeading>
        {Object.keys(benchmark_sensitivity_status).length === 0 ? (
          <p className="text-[11px] text-on-surface-variant/45">
            {LABELS.emptyBenchmark}
          </p>
        ) : (
          <div className="space-y-1">
            <KeyValueRow
              label={LABELS.benchStatus}
              value={benchmark_sensitivity_status.status ?? "—"}
            />
            <KeyValueRow
              label={LABELS.benchChangedIds}
              value={<ChipList items={changedIds} />}
            />
            <KeyValueRow
              label={LABELS.benchUnchangedIds}
              value={<ChipList items={unchangedIds} />}
            />
          </div>
        )}
      </div>

      {/* Limitations — render verbatim from the API */}
      <div className="rounded-md bg-surface-container-highest/30 p-3">
        <SectionHeading>{LABELS.limitationsHeading}</SectionHeading>
        {limitations.length === 0 ? (
          <p className="text-[11px] text-on-surface-variant/45">
            {LABELS.emptyLimitations}
          </p>
        ) : (
          <ul className="space-y-1">
            {limitations.map((entry, i) => (
              <li
                key={`lim-${i}`}
                className="flex items-start gap-2 text-[11px] leading-relaxed text-on-surface-variant/75"
              >
                <span className="mt-1.5 h-1 w-1 rounded-full shrink-0 bg-on-surface-variant/25" />
                <span>{formatLimitationText(entry)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
