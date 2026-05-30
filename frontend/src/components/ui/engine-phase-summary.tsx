/**
 * EnginePhaseSummary — compact engine-rigor block on Event Detail.
 *
 * Surfaces the nine engine-phase fields that ``GET /events/{id}``
 * carries (composed / lifted by ``engine_phase_surface.decorate_full``):
 * quality_tier, quality_warnings, actionability_check, counterfactual_check,
 * thesis_timing, critical_breakpoints, evidence_sources,
 * confidence_rationale, validation_rationale.
 *
 * Design rules:
 *   * Five visual groups, never nine separate cards.
 *   * Every group skip-empty cleanly.  When every group is empty the
 *     wrapper renders nothing — no placeholder card.
 *   * Renders in BOTH the strong-signal and low-signal branches; on
 *     low_information events the actionability + counterfactual blocks
 *     are exactly what diagnoses *why* the read isn't decision-relevant,
 *     so hiding them on the low-info path defeats the point.
 *   * Visually secondary to thesis / proof / falsifier content — small
 *     type, tabular numbers, no heavy borders.
 *
 * Pure helpers (``isActionabilityEmpty``, ``isCounterfactualEmpty``,
 * ``isTimingEmpty``, ``hasAnyEnginePhaseContent``) are exported so the
 * skip-empty contract has unit-test coverage without a React mount.
 */

import { cn } from "@/lib/utils";
import type {
  ActionabilityCheck,
  AnalysisDetail,
  CounterfactualCheck,
  CriticalBreakpoint,
  EvidenceSource,
  QualityTier,
  ThesisTiming,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Pure helpers (exported for tests)
// ---------------------------------------------------------------------------

/** True when ``actionability_check`` carries no composer output.  The
 *  composer always populates the dict on actionable / watch_only /
 *  low_information tiers, so this only fires when the field is missing
 *  entirely (legacy row, decorator failure). */
export function isActionabilityEmpty(ac?: ActionabilityCheck | null): boolean {
  if (!ac || typeof ac !== "object") return true;
  return Object.keys(ac).length === 0;
}

/** True when ``counterfactual_check`` carries no composer output. */
export function isCounterfactualEmpty(
  cc?: CounterfactualCheck | null,
): boolean {
  if (!cc || typeof cc !== "object") return true;
  return Object.keys(cc).length === 0;
}

/** True when none of the four window fields are populated. */
export function isTimingEmpty(t?: ThesisTiming | null): boolean {
  if (!t || typeof t !== "object") return true;
  return !(
    t.expected_reaction_window ||
    t.follow_through_window ||
    t.stale_after ||
    t.timing_rationale
  );
}

/** True when the wrapper would render nothing — every group is empty. */
export function hasAnyEnginePhaseContent(a?: AnalysisDetail | null): boolean {
  if (!a) return false;
  if (a.quality_tier) return true;
  if ((a.mechanism_subtype ?? "").trim().length > 0) return true;
  if ((a.quality_warnings ?? []).length > 0) return true;
  if (!isActionabilityEmpty(a.actionability_check)) return true;
  if (!isCounterfactualEmpty(a.counterfactual_check)) return true;
  if (!isTimingEmpty(a.thesis_timing)) return true;
  if ((a.critical_breakpoints ?? []).length > 0) return true;
  if ((a.evidence_sources ?? []).length > 0) return true;
  if ((a.confidence_rationale ?? "").trim().length > 0) return true;
  if ((a.validation_rationale ?? "").trim().length > 0) return true;
  return false;
}

// ---------------------------------------------------------------------------
// Style tokens — borrowed from analysis-view.tsx so the block sits in
// the same visual stack without re-importing private constants.
// ---------------------------------------------------------------------------

const SECTION_CARD = "bg-surface-container-low rounded-lg";
const INNER_CARD = "bg-surface-container-highest rounded-md";

// Viewer-facing tier labels.  The map KEYS are the backend ``quality_tier``
// values (unchanged); the VALUES are observation-only research labels — the
// project reports research evidence, not a trade recommendation, so no
// "actionable" / position language reaches the reader.
const _TIER_LABEL: Record<QualityTier, string> = {
  actionable: "Research-grade",
  watch_only: "Watch only",
  low_information: "Low information",
};

const _TIER_CLASS: Record<QualityTier, string> = {
  actionable: "bg-primary/12 text-primary border-primary/30",
  watch_only: "bg-on-surface-variant/12 text-on-surface-variant border-on-surface-variant/25",
  low_information: "bg-error-dim/12 text-error-dim border-error-dim/25",
};

const _RISK_CLASS: Record<NonNullable<ActionabilityCheck["risk_level"]>, string> = {
  standard: "text-primary",
  elevated: "text-[#e5b56e]",
  high: "text-error-dim",
};

function _fmtToken(token: string): string {
  return token.replace(/_/g, " ");
}

// ---------------------------------------------------------------------------
// Sub-components — every one returns null when its data is empty so the
// caller can place them unconditionally.
// ---------------------------------------------------------------------------

function DisciplineStrip({ analysis }: { analysis: AnalysisDetail }) {
  const tier = analysis.quality_tier;
  const subtype = (analysis.mechanism_subtype ?? "").trim();
  const warnings = analysis.quality_warnings ?? [];
  const ac = analysis.actionability_check;
  const tradableShown =
    !isActionabilityEmpty(ac) && typeof ac?.tradable === "boolean";
  if (!tier && !subtype && warnings.length === 0 && !tradableShown) return null;

  return (
    <div className="flex flex-wrap items-center gap-2">
      {tier && (
        <span
          className={cn(
            "px-2 py-1 rounded-full border text-[11px] font-bold uppercase tracking-[0.15em]",
            _TIER_CLASS[tier],
          )}
        >
          {_TIER_LABEL[tier]}
        </span>
      )}
      {subtype && (
        <span className="px-2 py-1 rounded-full bg-surface-container-highest text-on-surface-variant border border-outline-variant/25 text-[11px] font-semibold tracking-tight">
          {_fmtToken(subtype)}
        </span>
      )}
      {tradableShown && (
        <span
          className={cn(
            "px-2 py-1 rounded-full border text-[11px] font-bold uppercase tracking-[0.15em]",
            ac!.tradable
              ? "bg-primary/12 text-primary border-primary/30"
              : "bg-on-surface-variant/12 text-on-surface-variant/70 border-on-surface-variant/20",
          )}
        >
          {ac!.tradable ? "Decision-relevant" : "Observation only"}
        </span>
      )}
      {warnings.map((w) => (
        <span
          key={w}
          className="px-2 py-1 rounded-full bg-error-dim/8 text-error-dim/80 border border-error-dim/20 text-[11px] font-medium"
        >
          {_fmtToken(w)}
        </span>
      ))}
    </div>
  );
}

function ActionabilityDetail({ ac }: { ac?: ActionabilityCheck | null }) {
  if (isActionabilityEmpty(ac)) return null;
  const required = ac!.required_confirmation ?? [];
  const risk = ac!.risk_level;
  return (
    <div className={cn(INNER_CARD, "p-3 space-y-2")}>
      <p className="text-[11px] font-semibold text-on-surface-variant/75">
        Decision framing
      </p>
      {ac!.why_tradable_or_not && (
        <p className="text-[12px] text-on-surface leading-relaxed">
          {ac!.why_tradable_or_not}
        </p>
      )}
      {required.length > 0 && (
        <div>
          <p className="text-[10px] font-medium text-on-surface-variant/60 mb-1">
            Required confirmation
          </p>
          <ul className="space-y-0.5">
            {required.map((r, i) => (
              <li key={i} className="text-[12px] text-on-surface-variant leading-snug">
                · {r}
              </li>
            ))}
          </ul>
        </div>
      )}
      {(ac!.sizing_caveat || ac!.invalidation_trigger || risk) && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-on-surface-variant/80">
          {risk && (
            <span>
              Risk:&nbsp;
              <span className={cn("font-semibold", _RISK_CLASS[risk])}>
                {_fmtToken(risk)}
              </span>
            </span>
          )}
          {ac!.sizing_caveat && (
            <span className="min-w-0 flex-1">
              Sizing: <span className="text-on-surface-variant">{ac!.sizing_caveat}</span>
            </span>
          )}
          {ac!.invalidation_trigger && (
            <span className="min-w-0 flex-1">
              Invalidation:{" "}
              <span className="text-error-dim/80">{ac!.invalidation_trigger}</span>
            </span>
          )}
        </div>
      )}
    </div>
  );
}

function CounterfactualBlock({ cc }: { cc?: CounterfactualCheck | null }) {
  if (isCounterfactualEmpty(cc)) return null;
  const evidence = cc!.evidence_to_watch ?? [];
  return (
    <div className={cn(INNER_CARD, "p-3 space-y-2")}>
      <p className="text-[11px] font-semibold text-on-surface-variant/75">
        Counterfactual
      </p>
      {cc!.what_should_not_happen && (
        <p className="text-[12px] text-on-surface leading-relaxed">
          <span className="text-on-surface-variant/65">If we see&nbsp;</span>
          {cc!.what_should_not_happen}
        </p>
      )}
      {cc!.why_it_would_break_thesis && (
        <p className="text-[12px] text-on-surface-variant/80 italic leading-relaxed">
          {cc!.why_it_would_break_thesis}
        </p>
      )}
      {evidence.length > 0 && (
        <ul className="space-y-0.5">
          {evidence.map((e, i) => (
            <li key={i} className="text-[11px] text-on-surface-variant/75 leading-snug">
              · {e}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function TimingBlock({
  timing,
  breakpoints,
}: {
  timing?: ThesisTiming | null;
  breakpoints?: CriticalBreakpoint[] | null;
}) {
  const bp = breakpoints ?? [];
  if (isTimingEmpty(timing) && bp.length === 0) return null;

  type Cell = { label: string; value: string };
  const cells: Cell[] = [];
  if (timing?.expected_reaction_window)
    cells.push({ label: "Reaction", value: timing.expected_reaction_window });
  if (timing?.follow_through_window)
    cells.push({ label: "Follow-through", value: timing.follow_through_window });
  if (timing?.stale_after)
    cells.push({ label: "Stale after", value: timing.stale_after });

  return (
    <div className={cn(INNER_CARD, "p-3 space-y-2")}>
      <p className="text-[11px] font-semibold text-on-surface-variant/75">
        Timing &amp; Breakpoints
      </p>
      {cells.length > 0 && (
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          {cells.map((c) => (
            <span
              key={c.label}
              className="text-[11px] text-on-surface-variant/80 tabular-nums"
            >
              {c.label}:{" "}
              <span className="text-on-surface font-semibold">{c.value}</span>
            </span>
          ))}
        </div>
      )}
      {timing?.timing_rationale && (
        <p className="text-[11px] text-on-surface-variant/60 italic leading-snug">
          {timing.timing_rationale}
        </p>
      )}
      {bp.length > 0 && (
        <div className="pt-1">
          <p className="text-[10px] font-medium text-on-surface-variant/60 mb-1">
            Critical breakpoints
          </p>
          <ul className="space-y-0.5">
            {bp.map((b, i) => {
              const text =
                b.condition ||
                b.threshold_or_observation ||
                b.observation ||
                b.signal ||
                "";
              if (!text) return null;
              return (
                <li
                  key={i}
                  className="text-[12px] text-on-surface-variant leading-snug"
                >
                  · {text}
                  {b.timing && (
                    <span className="text-on-surface-variant/50 tabular-nums">
                      {" "}({b.timing})
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

function ReasoningBlock({
  confidence,
  validation,
  sources,
}: {
  confidence?: string;
  validation?: string;
  sources?: EvidenceSource[] | null;
}) {
  const conf = (confidence ?? "").trim();
  const val = (validation ?? "").trim();
  const src = sources ?? [];
  if (!conf && !val && src.length === 0) return null;

  return (
    <div className={cn(INNER_CARD, "p-3 space-y-2")}>
      <p className="text-[11px] font-semibold text-on-surface-variant/75">
        Reasoning &amp; Provenance
      </p>
      {conf && (
        <div>
          <p className="text-[10px] font-medium text-on-surface-variant/60 mb-0.5">
            Confidence
          </p>
          <p className="text-[12px] text-on-surface-variant leading-relaxed">
            {conf}
          </p>
        </div>
      )}
      {val && (
        <div>
          <p className="text-[10px] font-medium text-on-surface-variant/60 mb-0.5">
            Validation
          </p>
          <p className="text-[12px] text-on-surface-variant leading-relaxed">
            {val}
          </p>
        </div>
      )}
      {src.length > 0 && (
        <div>
          <p className="text-[10px] font-medium text-on-surface-variant/60 mb-1">
            Evidence sources
          </p>
          <ul className="space-y-0.5">
            {src.map((s, i) => {
              const label = s.field_used || s.label || "(unnamed source)";
              const meta = s.source_type || s.kind;
              const dir = s.supports_or_contradicts;
              return (
                <li
                  key={i}
                  className="text-[11px] text-on-surface-variant/80 leading-snug"
                >
                  · {label}
                  {meta && (
                    <span className="text-on-surface-variant/50"> [{_fmtToken(meta)}]</span>
                  )}
                  {dir && dir !== "neutral" && (
                    <span
                      className={cn(
                        "ml-1.5 text-[10px] font-medium",
                        dir === "supports" ? "text-primary/75" : "text-error-dim/75",
                      )}
                    >
                      {dir}
                    </span>
                  )}
                  {s.limitation && (
                    <span className="text-on-surface-variant/45 italic">
                      {" "}— {s.limitation}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Wrapper — renders nothing when every group is empty.
// ---------------------------------------------------------------------------

export function EnginePhaseSummary({
  analysis,
}: {
  analysis?: AnalysisDetail | null;
}) {
  if (!analysis || !hasAnyEnginePhaseContent(analysis)) return null;

  return (
    <details className={cn(SECTION_CARD, "group")}>
      <summary
        className={cn(
          "flex cursor-pointer list-none items-center gap-3 px-5 py-3.5",
          "rounded-lg select-none",
          "hover:bg-white/[0.015] transition-colors",
        )}
      >
        <span
          aria-hidden
          className={cn(
            "inline-flex h-4 w-4 items-center justify-center rounded-sm",
            "text-on-surface-variant/55 transition-transform",
            "group-open:rotate-90",
          )}
        >
          ›
        </span>
        <div className="flex flex-col leading-tight">
          <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-on-surface/85">
            Engine reference
          </span>
          <span className="text-[11px] text-on-surface-variant/60">
            Frozen-phase fields — how the engine grades and gates this study
          </span>
        </div>
        <span className="ml-auto text-[10px] uppercase tracking-[0.2em] text-on-surface-variant/45">
          Frozen at analysis
        </span>
      </summary>
      <div className="px-5 pb-5 pt-1 space-y-3 border-t border-border/30">
        <DisciplineStrip analysis={analysis} />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <ActionabilityDetail ac={analysis.actionability_check} />
          <CounterfactualBlock cc={analysis.counterfactual_check} />
          <TimingBlock
            timing={analysis.thesis_timing}
            breakpoints={analysis.critical_breakpoints}
          />
          <ReasoningBlock
            confidence={analysis.confidence_rationale}
            validation={analysis.validation_rationale}
            sources={analysis.evidence_sources}
          />
        </div>
      </div>
    </details>
  );
}
