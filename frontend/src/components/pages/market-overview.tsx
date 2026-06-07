import { useState, type CSSProperties, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { AlertTriangle, FlaskConical } from "lucide-react";
import {
  api,
  type ContextExplanation,
  type TrackRecord,
  type SavedEvent,
  type TrackRecordBreakdown,
  type TrackRecordBreakdownBucket,
  type NewsCluster,
  type RegimeVector,
  type RefreshMeta,
  type NewsUncertaintyConcentration,
  type StressRegime,
  type FundingStressMode,
} from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";
import { pct } from "@/lib/ticker-utils";
import { buildClusterContext } from "@/lib/cluster-context";
import { BenchmarkSnapshotsStrip } from "@/components/ui/benchmark-snapshots-strip";
import { TrackedEvidenceCard } from "@/components/ui/tracked-evidence-card";
import { EvidenceCoverageCard } from "@/components/ui/evidence-coverage-card";
import { DegradedContextNotice } from "@/components/ui/degraded-data-notice";

// ---------------------------------------------------------------------------
// Design-package palette (Direction C tokens) — scoped to this page via CSS
// custom properties set on the root, inherited by the snapshot strip and
// mover cards.  Colours and surfaces are the zip's exact values; the page is
// styled to the design, not translated into the app's teal theme.
//
// Typography: the design is serif (Instrument Serif display + Newsreader
// body), but those webfonts are not loaded by the shell and ``index.html`` is
// outside this task's touch-list.  ``--so-display`` / ``--so-serif`` therefore
// point at the loaded Manrope / Inter so the default render uses real loaded
// fonts (not a system-serif fallback).  To switch to the true design serifs,
// load them in ``index.html`` and repoint these two vars — no other change.
// ---------------------------------------------------------------------------

const SO_VARS = {
  // Charcoal / graphite card surfaces — neutral, not blue-black/navy.
  "--so-bg-1": "#121212", // page card surface
  "--so-bg-2": "#181818", // raised / hover surface
  "--so-ink-0": "#efeadb",
  "--so-ink-1": "#c6c1b3",
  "--so-ink-2": "#908b7f",
  "--so-ink-3": "#5e5a52",
  "--so-ink-4": "#383631",
  "--so-rule": "rgba(232,227,209,0.10)",
  "--so-rule-hi": "rgba(232,227,209,0.18)",
  "--so-citrine": "#d4b343",
  "--so-jade": "#6e9c87",
  "--so-jade-ink": "#98c2ad",
  "--so-rust": "#c97064",
  "--so-rust-ink": "#e0978c",
  "--so-amber": "#c89759",
  "--so-slate": "#7a8694",
  "--so-bd-rust": "rgba(201,112,100,0.40)",
  "--so-bd-amber": "rgba(200,151,89,0.40)",
  "--so-bd-jade": "rgba(110,156,135,0.45)",
  // Loaded fonts (see note above); repoint to the design serifs once they
  // are loaded in index.html.
  "--so-display": "'Manrope','Inter',sans-serif",
  "--so-serif": "'Inter','Manrope',sans-serif",
} as CSSProperties;

// The former MoversChapter (today / weekly / persistent rolling-mover windows)
// was retired in P5B: Section 2 is now "The archive", which reads off the
// frozen research corpus instead of empty live windows.  The mover-card
// components remain in ``mover-cards.tsx`` for other surfaces.

function _contextExplanationText(value?: ContextExplanation["meaning"]): string {
  if (!value) return "";
  if (Array.isArray(value)) {
    return value
      .map((line) => line.trim())
      .filter(Boolean)
      .join(" ");
  }
  return value.trim();
}

// ---------------------------------------------------------------------------
// Plain-language guidance (P6B).  Replaces the old click-to-expand "How to
// read this" accordion with always-visible inline guidance, and translates a
// few non-obvious market-backdrop labels at the point of use — no big
// accordion, no Googling core labels.
// ---------------------------------------------------------------------------

export const HOWTO_MARKET_BACKDROP =
  "How to read: the market regime the archive is interpreted against — context, not a directional call.";
export const HOWTO_ARCHIVE =
  "How to read: the frozen research corpus and its most recent analyzed cases — a record of past work, not current activity.";
export const HOWTO_OUTCOME_LEDGER =
  "How to read: descriptive archive reads, not a verdict; support is measured over resolved cases only, and unresolved cases stay visible.";
export const HOWTO_EVIDENCE =
  "How to read: what the evidence supports, kept separate from what the project explicitly does not claim.";

// Plain meanings for non-obvious backdrop labels (regime axes, funding/stress
// modes).  Substring-keyed so "Credit · duration stress" resolves the same as
// "duration stress".
const _PLAIN_MEANING: ReadonlyArray<readonly [string, string]> = [
  ["duration stress", "pressure from credit conditions and interest-rate duration — markets more sensitive to financing costs and discount-rate moves."],
  ["duration shock", "a sharp move in interest-rate duration — bond-price and discount-rate pressure."],
  ["credit widening", "credit spreads widening — the market repricing borrowing risk higher."],
  ["dollar shortage", "tight dollar funding — a scramble for US-dollar liquidity."],
  ["liquidity squeeze", "funding liquidity drying up across markets."],
  ["geopolitical", "stress driven by geopolitical events rather than financial plumbing."],
  ["systemic", "broad, cross-market stress — not contained to a single channel."],
];

// Returns a plain-language meaning for a jargon label, or null when the label
// is already plain / unknown.
export function plainMeaning(label: string | null | undefined): string | null {
  if (!label) return null;
  const norm = label.toLowerCase();
  for (const [key, text] of _PLAIN_MEANING) {
    if (norm.includes(key)) return text;
  }
  return null;
}

// Always-visible inline "Plain meaning" line — replaces the old accordion.
export function ContextExplanationInline({
  explanation,
  className,
}: {
  explanation?: ContextExplanation | null;
  className?: string;
}) {
  const meaning = _contextExplanationText(explanation?.meaning);
  if (!meaning) return null;
  return (
    <p
      className={cn(
        "mt-3 max-w-[64ch] border-t border-dashed border-[color:var(--so-rule)] pt-2.5 font-[family-name:var(--so-serif)] text-[12px] italic leading-relaxed text-[var(--so-ink-3)]",
        className,
      )}
    >
      <span className="font-mono text-[10px] not-italic uppercase tracking-[0.12em] text-[var(--so-ink-2)]">
        Plain meaning:
      </span>{" "}
      {meaning}
    </p>
  );
}

// Compact plain-meaning line for a single jargon label, rendered at the point
// of use; renders nothing when the label is already plain.
function PlainMeaningLine({ label, className }: { label: string; className?: string }) {
  const meaning = plainMeaning(label);
  if (!meaning) return null;
  return (
    <p
      className={cn(
        "font-[family-name:var(--so-serif)] text-[11.5px] italic leading-relaxed text-[var(--so-ink-3)]",
        className,
      )}
    >
      <span className="font-mono text-[9px] not-italic uppercase tracking-[0.12em] text-[var(--so-ink-2)]">
        Plain meaning:
      </span>{" "}
      {meaning}
    </p>
  );
}

// ---------------------------------------------------------------------------
// Trending Themes — derive dominant themes from recent clusters
// ---------------------------------------------------------------------------

export interface ThemeEntry {
  label: string;
  category: "action" | "sector";
  clusterCount: number;
  sourceWeight: number;
  regimeAligned: boolean;
}

const _THEME_ALIGNMENT_RULES: Array<{
  pattern: RegExp;
  check: (v: RegimeVector) => boolean;
}> = [
  {
    pattern: /tariff|trade|sanction|embargo/i,
    check: (v) =>
      v.fx === "dollar_strong" || v.fx === "dollar_weak" ||
      v.growth_stress === "stressed" || v.growth_stress === "watch",
  },
  {
    pattern: /rate|fed|monetary|hike|cut|pivot/i,
    check: (v) =>
      v.policy_stance === "hawkish" || v.policy_stance === "dovish" ||
      v.inflation === "hot" || v.inflation === "cool",
  },
  {
    pattern: /oil|energy|gas|commodit/i,
    check: (v) => v.inflation === "hot",
  },
  {
    pattern: /defense|military|war|conflict|geopolit/i,
    check: (v) => v.growth_stress === "stressed" || v.growth_stress === "watch",
  },
  {
    pattern: /dollar|currency|exchange|forex/i,
    check: (v) => v.fx === "dollar_strong" || v.fx === "dollar_weak",
  },
];

export function deriveThemes(
  clusters: NewsCluster[],
  regimeVec: RegimeVector | null,
): ThemeEntry[] {
  const counts = new Map<
    string,
    { label: string; category: "action" | "sector"; clusterCount: number; sourceWeight: number }
  >();

  for (const cluster of clusters) {
    if (cluster.low_signal) continue;
    const cons = cluster.consensus as Record<string, unknown> | null | undefined;
    if (!cons) continue;

    const pairs: Array<[unknown, "action" | "sector"]> = [
      [cons.action, "action"],
      [cons.sector, "sector"],
    ];

    for (const [raw, category] of pairs) {
      if (!raw || typeof raw !== "string") continue;
      const label = raw.trim().toLowerCase();
      if (!label || label === "unknown" || label === "none" || label === "n/a") continue;
      const key = `${category}:${label}`;
      const existing = counts.get(key);
      if (existing) {
        existing.clusterCount += 1;
        existing.sourceWeight += cluster.source_count ?? 0;
      } else {
        counts.set(key, { label, category, clusterCount: 1, sourceWeight: cluster.source_count ?? 0 });
      }
    }
  }

  const themes: ThemeEntry[] = [];
  for (const entry of counts.values()) {
    if (entry.clusterCount < 2 && entry.sourceWeight < 4) continue;
    const aligned =
      !!(regimeVec?.available) &&
      _THEME_ALIGNMENT_RULES.some(({ pattern, check }) => pattern.test(entry.label) && check(regimeVec!));
    themes.push({ ...entry, regimeAligned: aligned });
  }

  themes.sort((a, b) => {
    if (a.regimeAligned !== b.regimeAligned) return a.regimeAligned ? -1 : 1;
    return (b.clusterCount * 2 + b.sourceWeight) - (a.clusterCount * 2 + a.sourceWeight);
  });

  return themes.slice(0, 7);
}

// ---------------------------------------------------------------------------
// Market Regime — compact one-line summary of macro backdrop
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Regime read — text-forward consolidation of the four legacy regime
// surfaces (regime strip + vector + macro system + interpretation) into one
// card, per the Slice 02 design package.  No dial: a compound headline, a
// confidence read, a one-line rationale, chips for the off-neutral axes
// only, and a count for the neutral remainder.  Axis vocabulary mirrors
// regime_vector.REGIME_AXES so the chips line up with how the backend talks
// about the regime.
// ---------------------------------------------------------------------------

type RegimeAxisKey =
  | "inflation"
  | "policy_stance"
  | "fx"
  | "growth_stress"
  | "credit"
  | "curve_shape"
  | "inflation_path";

// Tone is a factual read, never a market-direction verdict: only the
// unambiguous stress states read coral, an unsettled "watch" reads
// neutral/slate, and every other off-neutral axis is a quiet teal-keyed
// "active" chip.  Directional reads (hot / hawkish / USD strong) are NOT
// graded good-or-bad — the page reports the read, it does not rate it.
type RegimeAxisTone = "active" | "watch" | "stress";

// "neutral" is a real backend reading (the axis is settled); a missing or
// "unknown" value means there is NO reading.  The two are kept distinct so
// the card never asserts an unread axis is neutral — the backend normally
// degrades to "neutral", but a genuinely absent axis must read as unread.
type RegimeAxisStatus = "active" | "neutral" | "unknown";

type RegimeAxis = {
  key: string;
  label: string;
  state: string;
  status: RegimeAxisStatus;
  tone: RegimeAxisTone;
};

function _axisLabel(axis: RegimeAxisKey): string {
  if (axis === "policy_stance") return "Policy";
  if (axis === "growth_stress") return "Growth";
  if (axis === "curve_shape") return "Curve";
  if (axis === "inflation_path") return "Path";
  if (axis === "fx") return "FX";
  return axis.charAt(0).toUpperCase() + axis.slice(1);
}

// Concise state words for the off-neutral axis chips.  The directional
// phrases read unambiguously without the axis-name prefix, which the chip
// carries as a separate key.
const _AXIS_STATE_WORDS: Record<string, string> = {
  hot: "hot",
  cool: "cool",
  hawkish: "hawkish",
  dovish: "dovish",
  dollar_strong: "USD strong",
  dollar_weak: "USD weak",
  stressed: "stressed",
  watch: "watch",
  risk_on: "risk-on",
  risk_off: "risk-off",
  front_loaded: "front-loaded",
  term_premium: "term premium",
  parallel: "parallel",
  hawkish_constraint: "constraint",
  dovish_space: "space",
};

function _axisShortState(value: string): string {
  return _AXIS_STATE_WORDS[value] ?? value.replace(/_/g, " ");
}

function _axisChipTone(value: string): RegimeAxisTone {
  if (value === "stressed" || value === "risk_off" || value === "duration_stress") {
    return "stress";
  }
  if (value === "watch") return "watch";
  return "active";
}

function _axisStatus(value: string): RegimeAxisStatus {
  if (value === "neutral") return "neutral";
  if (value === "unknown" || value === "") return "unknown";
  return "active";
}

function _regimeAxes(regimeVec: RegimeVector | null): RegimeAxis[] {
  const axes: readonly RegimeAxisKey[] = [
    "inflation", "policy_stance", "fx", "growth_stress",
    "credit", "curve_shape", "inflation_path",
  ];
  return axes.map((axis) => {
    const value = regimeVec?.[axis] ?? "unknown";
    return {
      key: axis,
      label: _axisLabel(axis),
      state: _axisShortState(value),
      status: _axisStatus(value),
      tone: _axisChipTone(value),
    };
  });
}

// Design axis tones: a factual stress read is rust, an unsettled watch is
// amber, every other off-neutral read carries neutral chrome (the axis has a
// reading, but the page does not grade it good-or-bad).  The axis-name key is
// always dim (ink-3); only the state word takes the tone colour.
const _AXIS_CHIP_BORDER: Record<RegimeAxisTone, string> = {
  active: "border-[color:var(--so-rule-hi)]",
  watch: "border-[color:var(--so-bd-amber)]",
  stress: "border-[color:var(--so-bd-rust)]",
};
const _AXIS_CHIP_STATE: Record<RegimeAxisTone, string> = {
  active: "text-[var(--so-ink-2)]",
  watch: "text-[var(--so-amber)]",
  stress: "text-[var(--so-rust-ink)]",
};

function AxisChip({ axis }: { axis: RegimeAxis }) {
  return (
    <span
      className={cn(
        "inline-flex items-baseline gap-1.5 rounded-[2px] border px-2 py-[3px] font-mono text-[10.5px] tracking-[0.04em]",
        _AXIS_CHIP_BORDER[axis.tone],
      )}
    >
      <span className="text-[9px] uppercase tracking-[0.12em] text-[var(--so-ink-3)]">
        {axis.label}
      </span>
      <span className={_AXIS_CHIP_STATE[axis.tone]}>{axis.state}</span>
    </span>
  );
}

function _humanizeCompound(label: string): string {
  const s = label.replace(/_/g, " ").trim();
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

// Regime read — P8D compact band.  Full-width; the identity (kicker · headline
// · confidence) sits on one header row with the off-neutral axis chips pushed
// right, so the band fills its width instead of reading as a wide empty card.
// All prior data/copy is preserved, just laid out horizontally and tighter.
// Exported for render tests.
export function RegimeVectorCard({
  regimeVec,
  explanation,
}: {
  regimeVec:
    | (RegimeVector & {
        compound?: { label: string; confidence: number; rationale: string };
        transition?: { state: string; rationale: string };
      })
    | null;
  explanation?: ContextExplanation | null;
}) {
  const kicker = (
    <span className="font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-[var(--so-ink-3)]">
      Regime read
    </span>
  );

  if (!regimeVec?.available) {
    return (
      <div className="rounded-[4px] border border-[color:var(--so-rule)] bg-[var(--so-bg-1)] px-[18px] py-3.5">
        {kicker}
        <p className="mt-1.5 font-[family-name:var(--so-serif)] text-[13px] italic leading-relaxed text-[var(--so-ink-3)]">
          Regime read is unavailable for this market snapshot.
        </p>
      </div>
    );
  }

  const axes = _regimeAxes(regimeVec);
  const offNeutral = axes.filter((a) => a.status === "active");
  const neutral = axes.filter((a) => a.status === "neutral");
  const unread = axes.filter((a) => a.status === "unknown");

  const compoundLabel = regimeVec.compound?.label ?? "";
  // ``label === "none"`` means the compound classifier did not lock a
  // regime — confidence is N/A, not zero.  Show "—" rather than "0%" so a
  // mixed read never misreads as low-quality data.
  const isLocked = !!compoundLabel && compoundLabel !== "none";
  const confidence = regimeVec.compound?.confidence;
  const confPct = isLocked && typeof confidence === "number"
    ? Math.round(confidence * 100)
    : null;
  // Backend always supplies a rationale — for locked regimes it's the
  // rule's prose; for the unlocked branch it's why the classifier didn't
  // lock.  Backticks come straight from regime_compound.py and would
  // render literally — strip them; replace the unlocked branch with
  // plain-English copy that doesn't read like a bug report.
  const rawRationale = (regimeVec.compound?.rationale ?? "")
    .replace(/`/g, "")
    .trim();
  const compoundRationale = !isLocked
    ? "Signals are mixed/shifting; no combined regime rule matched."
    : rawRationale;

  return (
    <div className="rounded-[4px] border border-[color:var(--so-rule)] bg-[var(--so-bg-1)] px-[18px] py-3.5">
      {/* Header band: kicker · headline · confidence (left), off-neutral chips
          (right) — fills the full width. */}
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          {kicker}
          <h3 className="font-[family-name:var(--so-display)] text-[16px] font-normal leading-tight tracking-tight text-[var(--so-ink-0)]">
            {isLocked ? _humanizeCompound(compoundLabel) : "No dominant regime pattern"}
          </h3>
          <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-[var(--so-ink-3)]">
            Confidence{" "}
            <span className="tabular-nums text-[var(--so-amber)]">
              {isLocked ? (confPct == null ? "—" : `${confPct}%`) : "—"}
            </span>
          </span>
        </div>
        {offNeutral.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {offNeutral.map((a) => (
              <AxisChip key={a.key} axis={a} />
            ))}
          </div>
        )}
      </div>

      {compoundRationale && (
        <p className="mt-2 font-[family-name:var(--so-serif)] text-[12.5px] leading-[1.5] text-[var(--so-ink-2)]">
          {compoundRationale}
        </p>
      )}

      {(neutral.length > 0 || unread.length > 0) && (
        <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-0.5 font-mono text-[10px] tracking-[0.03em] text-[var(--so-ink-3)]">
          {neutral.length > 0 && (
            <span>
              {neutral.length} {neutral.length === 1 ? "axis" : "axes"} neutral · {neutral.map((a) => a.label).join(" · ")}
            </span>
          )}
          {unread.length > 0 && (
            <span className="text-[var(--so-ink-4)]">
              {unread.length} without a current read · {unread.map((a) => a.label).join(" · ")}
            </span>
          )}
        </div>
      )}

      {(() => {
        const jargonAxis = offNeutral.find((a) => plainMeaning(`${a.label} ${a.state}`));
        return jargonAxis ? (
          <PlainMeaningLine label={`${jargonAxis.label} ${jargonAxis.state}`} className="mt-2" />
        ) : null;
      })()}
      <ContextExplanationInline explanation={explanation} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Uncertainty & funding — four compact zones (State · Drivers · Horizon ·
// Interpretation), per the Slice 02 design package.  Surfaces the funding /
// stress / credit decomposition /market-context already computes, driver-first
// (the observable move leads; severity is a small tag), and adds horizon
// discipline so a short/medium-horizon event read is never confused with a
// permanent asset forecast.  Replaces the heavy full-width stress-strip.
// Design palette: quiet/normal reads jade, an unsettled watch reads amber,
// genuine stress reads rust — a state read, never a directional verdict.
// ---------------------------------------------------------------------------

type StressData = StressRegime & { available?: boolean };
type UncTone = "pos" | "watch" | "stress";

const _UNC_TONE_CLASS: Record<UncTone, string> = {
  pos: "text-[var(--so-jade-ink)]",
  watch: "text-[var(--so-amber)]",
  stress: "text-[var(--so-rust-ink)]",
};

function _titleCase(s: string): string {
  const t = s.replace(/_/g, " ").trim();
  return t ? t.charAt(0).toUpperCase() + t.slice(1) : t;
}

type UncRowData = { label: string; note: string; tone: UncTone };

// Real stress regimes from market_check.compute_stress_regime: "Calm",
// "Calm with Undercurrent", "Geopolitical Stress", "Systemic Stress".  The
// "Degraded" / "Unavailable" / "Unknown" states all carry available === false
// and are filtered out above.  Concise value labels keep the design's
// single-word value slot; the full read lives in the note.
const _STRESS_LABEL: Record<string, string> = {
  "calm": "Calm",
  "calm with undercurrent": "Undercurrent",
  "geopolitical stress": "Geopolitical",
  "systemic stress": "Systemic",
};

function _stressRow(stress: StressData | null): UncRowData | null {
  if (!stress || stress.available === false || !stress.regime) return null;
  const r = stress.regime.toLowerCase();
  const tone: UncTone =
    r.includes("systemic") || r.includes("geopolitical") || r.includes("stress") ? "stress"
    : r.includes("undercurrent") || r.includes("watch") || r.includes("elevated") ? "watch"
    : "pos";
  return {
    label: _STRESS_LABEL[r] ?? _titleCase(stress.regime),
    note: (stress.summary ?? "").trim(),
    tone,
  };
}

const _FUNDING_MODE_LABEL: Record<FundingStressMode["primary_mode"], string> = {
  none: "Normal",
  duration_shock: "Duration shock",
  credit_widening: "Credit widening",
  dollar_shortage: "Dollar shortage",
  liquidity_squeeze: "Liquidity squeeze",
};

function _fundingRow(funding: FundingStressMode | null): UncRowData | null {
  if (!funding || funding.available === false) return null;
  const firing = funding.primary_mode !== "none" && funding.composite_severity !== "none";
  if (!firing) {
    return {
      label: "Normal",
      note: (funding.rationale ?? "No active funding-stress mode").trim(),
      tone: "pos",
    };
  }
  const tone: UncTone =
    funding.composite_severity === "acute" || funding.composite_severity === "elevated"
      ? "stress"
      : "watch";
  return {
    label: _FUNDING_MODE_LABEL[funding.primary_mode] ?? _titleCase(funding.primary_mode),
    note: (funding.rationale ?? "").trim(),
    tone,
  };
}

// ---- P8B decomposition selectors (pure, driver-first; exported for tests) ----

// Minimal structural shape of MarketContext["credit_regime"] — declared
// locally so lib/api.ts stays untouched; the parent passes the real block.
type CreditRegimeBlock = {
  available?: boolean;
  regime?: string;
  regime_label?: string;
  rationale?: string;
  hy_ig_differential_5d?: number | null;
};

export interface FiringFundingMode {
  mode: string;
  label: string;
  severity: string;
  drivers: string[];
}

const _FUNDING_SEVERITY_RANK: Record<string, number> = {
  acute: 3,
  elevated: 2,
  mild: 1,
  none: 0,
};

// Funding modes that fired, most-severe first, drivers carried verbatim.
// Returns [] when the block is absent / unavailable or nothing fired — never
// fabricates a mode or a driver.
export function selectFiringFundingModes(
  funding: FundingStressMode | null,
): FiringFundingMode[] {
  if (!funding || funding.available === false) return [];
  const modes = funding.modes;
  if (!modes || typeof modes !== "object") return [];
  const out: FiringFundingMode[] = [];
  for (const [mode, m] of Object.entries(modes)) {
    if (!m || m.fired !== true) continue;
    const drivers = Array.isArray(m.drivers)
      ? m.drivers.filter((d): d is string => typeof d === "string" && d.trim() !== "")
      : [];
    out.push({
      mode,
      label: _FUNDING_MODE_LABEL[mode as FundingStressMode["primary_mode"]] ?? _titleCase(mode),
      severity: typeof m.severity === "string" ? m.severity : "",
      drivers,
    });
  }
  out.sort(
    (a, b) => (_FUNDING_SEVERITY_RANK[b.severity] ?? 0) - (_FUNDING_SEVERITY_RANK[a.severity] ?? 0),
  );
  return out;
}

export interface StressSignalMarker {
  key: string;
  label: string;
}

// Stress component flags, in canonical order — the underlying booleans behind
// the one-word regime label.
const _STRESS_SIGNAL_LABEL: ReadonlyArray<readonly [string, string]> = [
  ["vix_elevated", "VIX elevated"],
  ["term_inversion", "Curve inverted"],
  ["credit_widening", "Credit widening"],
  ["safe_haven_bid", "Safe-haven bid"],
  ["breadth_deterioration", "Breadth weak"],
];

// Firing stress component flags only; [] when the signals block is absent.
export function selectFiringStressSignals(
  stress: StressData | null,
): StressSignalMarker[] {
  const signals = stress?.signals as Record<string, unknown> | undefined;
  if (!signals || typeof signals !== "object") return [];
  return _STRESS_SIGNAL_LABEL.filter(([k]) => signals[k] === true).map(([key, label]) => ({
    key,
    label,
  }));
}

export interface CreditConfirmation {
  label: string;
  diff: number | null;
}

// Credit-regime confirmation read; null when unavailable or unlabeled.
export function selectCreditConfirmation(
  cr: CreditRegimeBlock | null | undefined,
): CreditConfirmation | null {
  if (!cr || cr.available === false) return null;
  const label = (cr.regime_label ?? "").trim();
  if (!label) return null;
  return {
    label,
    diff:
      typeof cr.hy_ig_differential_5d === "number" && Number.isFinite(cr.hy_ig_differential_5d)
        ? cr.hy_ig_differential_5d
        : null,
  };
}

// ---- Horizon discipline — static, descriptive copy (no forecast claim) ----

export const HORIZON_DISCIPLINE_NOTE =
  "Second-order reads are short- and medium-horizon event claims, not permanent asset forecasts.";
export const HORIZON_DISCIPLINE_PLAIN =
  "A headline can move oil, rates, credit, or equities for days or weeks without changing the long-run trend.";

export interface HorizonRow {
  k: string;
  label: string;
  note: string;
}
export const HORIZON_ROWS: ReadonlyArray<HorizonRow> = [
  { k: "1d", label: "reaction", note: "first repricing" },
  { k: "5d", label: "window", note: "short-term confirmation or fade" },
  { k: "20d", label: "persistence", note: "whether the channel keeps mattering" },
  { k: "Secular", label: "baseline", note: "outside this event claim" },
];

export const INTERPRETATION_WHAT_CHANGES_LABEL = "What would change this read";

// ---------------------------------------------------------------------------
// Explainable terms (P8E) — page-local term-level explanations.  A viewer
// clicks a jargon term (a subtle button) and a stable in-card panel shows a
// short research-note read.  No whole-card expansion, no modal, no "How to
// read this" accordion.  Copy is descriptive and horizon-disciplined; it never
// implies an event shock is a permanent asset forecast.
// ---------------------------------------------------------------------------

export interface TermExplanation {
  title: string;
  plainMeaning: string;
  whyItMatters: string;
  whatWouldChange?: string;
  horizonCaveat?: string;
}

export const EXPLANATION_DEFAULT = "Select a term to see the plain-language read.";

const _HORIZON_CAVEAT =
  "Second-order reads are short- and medium-horizon event claims, not permanent asset forecasts.";

const _TERM_EXPLANATIONS: Record<string, TermExplanation> = {
  funding_severity: {
    title: "Funding severity",
    plainMeaning:
      "How tight funding conditions are right now — a composite read from Normal to Acute across dollar liquidity, credit spreads, volatility, and financing costs.",
    whyItMatters:
      "Event reactions can be amplified when markets are also repricing dollar liquidity, credit spreads, volatility, or financing costs.",
    whatWouldChange:
      "Dollar pressure eases, credit spreads tighten, volatility normalizes, or stress components stop corroborating.",
  },
  dollar_shortage: {
    title: "Dollar shortage",
    plainMeaning: "Dollar demand is firming relative to available liquidity.",
    whyItMatters: "USD-sensitive reactions can persist when the dollar funding channel confirms the event shock.",
    whatWouldChange: "DXY pressure fades or dollar-liquidity stress stops appearing in the funding drivers.",
  },
  credit_widening: {
    title: "Credit widening",
    plainMeaning: "Credit spreads are widening — the market is repricing borrowing risk higher.",
    whyItMatters: "Funding-sensitive reactions can persist when credit-risk appetite is weakening alongside the event.",
    whatWouldChange: "Credit spreads tighten, or high-yield stabilizes relative to investment grade.",
  },
  liquidity_squeeze: {
    title: "Liquidity squeeze",
    plainMeaning: "Funding liquidity is drying up across markets.",
    whyItMatters: "Reactions can be amplified when liquidity is scarce and positions are harder to finance.",
    whatWouldChange: "Volatility normalizes and funding conditions ease.",
  },
  duration_shock: {
    title: "Duration shock",
    plainMeaning: "A sharp move in interest-rate duration — bond-price and discount-rate pressure.",
    whyItMatters: "Rate-sensitive reactions can persist when the duration channel confirms the event shock.",
    whatWouldChange: "Long-end yields stabilize and the duration move fades.",
  },
  vix_elevated: {
    title: "VIX elevated",
    plainMeaning: "Equity-market volatility is running above its recent average.",
    whyItMatters:
      "A single event reaction is harder to read cleanly when broad volatility is elevated; the confidence band around any one move is wider.",
    whatWouldChange: "VIX falls back toward its recent average.",
  },
  hy_ig: {
    title: "HY−IG",
    plainMeaning: "High-yield bonds compared with investment-grade bonds.",
    whyItMatters:
      "A widening gap suggests weaker credit-risk appetite, which can make funding-sensitive event effects more persistent.",
    whatWouldChange: "High-yield stabilizes relative to investment grade.",
  },
  horizon_1d: {
    title: "1d reaction",
    plainMeaning: "The first day's repricing after the event.",
    whyItMatters: "The initial move shows how the market first read the headline, before any confirmation or fade.",
    horizonCaveat: _HORIZON_CAVEAT,
  },
  horizon_5d: {
    title: "5d window",
    plainMeaning: "The reaction over the first week of trading.",
    whyItMatters: "Five days shows whether the initial move was confirmed or faded — the short-term read.",
    horizonCaveat: _HORIZON_CAVEAT,
  },
  horizon_20d: {
    title: "20d persistence",
    plainMeaning: "Whether the reaction still holds about a month out.",
    whyItMatters: "Persistence at twenty days shows whether the channel kept mattering or the move reversed.",
    horizonCaveat: _HORIZON_CAVEAT,
  },
  horizon_secular: {
    title: "Secular baseline",
    plainMeaning: "The long-run direction of an asset is outside this event claim.",
    whyItMatters:
      "A headline can move oil, rates, credit, or equities for days or weeks without changing the long-run trend.",
    horizonCaveat: _HORIZON_CAVEAT,
  },
};

// Pure lookup — the plain-language read shown in the panel when a term is
// selected; null for no / unknown term (the panel then shows the default
// prompt).  Exported for tests.
export function getTermExplanation(term: string | null | undefined): TermExplanation | null {
  if (!term) return null;
  return _TERM_EXPLANATIONS[term] ?? null;
}

// A subtle, calm term button — the only affordance is a hover/active tint;
// never a whole-card target.  Callers pass the visual classes for the term
// they wrap (chip, label, or row).
function ExplainableTerm({
  term,
  active,
  onSelect,
  className,
  children,
}: {
  term: string;
  active: boolean;
  onSelect: (term: string) => void;
  className?: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      data-term={term}
      aria-pressed={active}
      onClick={() => onSelect(term)}
      className={cn(
        "rounded-[2px] text-left transition-colors hover:bg-white/[0.04]",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[color:var(--so-rule-hi)]",
        active && "bg-white/[0.06]",
        className,
      )}
    >
      {children}
    </button>
  );
}

function ExplLine({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <dt className="font-mono text-[9.5px] uppercase tracking-[0.12em] text-[var(--so-ink-2)]">{k}</dt>
      <dd className="m-0 mt-0.5 max-w-[68ch] font-[family-name:var(--so-serif)] text-[12.5px] leading-[1.5] text-[var(--so-ink-2)]">
        {v}
      </dd>
    </div>
  );
}

// Stable in-card explanation panel — a quiet research note, not a chatbot.  A
// min-height keeps the card from jumping as the selection changes.  Exported
// for tests.
export function ExplanationPanel({ explanation }: { explanation: TermExplanation | null }) {
  if (!explanation) {
    return (
      <div className="mt-3.5 min-h-[96px] border-t border-[color:var(--so-rule)] pt-3">
        <p className="font-[family-name:var(--so-serif)] text-[12.5px] italic leading-relaxed text-[var(--so-ink-3)]">
          {EXPLANATION_DEFAULT}
        </p>
      </div>
    );
  }
  return (
    <div className="mt-3.5 min-h-[96px] border-t border-[color:var(--so-rule)] pt-3">
      <div className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--so-citrine)]">
        {explanation.title}
      </div>
      <dl className="m-0 space-y-1.5">
        <ExplLine k="Plain meaning" v={explanation.plainMeaning} />
        <ExplLine k="Why it matters" v={explanation.whyItMatters} />
        {explanation.whatWouldChange && <ExplLine k="What would change this read" v={explanation.whatWouldChange} />}
        {explanation.horizonCaveat && <ExplLine k="Horizon caveat" v={explanation.horizonCaveat} />}
      </dl>
    </div>
  );
}

// Driver row — driver-first, severity as a small tag, clickable for its
// term-level explanation.  Never a hero stat.
function FundingModeRow({
  m,
  active,
  onSelect,
}: {
  m: FiringFundingMode;
  active: boolean;
  onSelect: (term: string) => void;
}) {
  return (
    <ExplainableTerm
      term={m.mode}
      active={active}
      onSelect={onSelect}
      className="flex w-full flex-wrap items-baseline gap-x-2.5 gap-y-0.5 px-1"
    >
      <span className="font-mono text-[12px] tabular-nums text-[var(--so-ink-1)]">
        {m.drivers.length > 0 ? m.drivers.join(" · ") : m.label}
      </span>
      <span className="font-mono text-[9.5px] uppercase tracking-[0.1em] text-[var(--so-ink-3)]">
        {m.label}
        {m.severity ? ` · ${m.severity}` : ""}
      </span>
    </ExplainableTerm>
  );
}

// State item — a quiet labelled read (no hero styling).  Clickable (a term
// button) when ``onSelect`` is supplied; otherwise a plain labelled read.
function StateItem({
  k,
  value,
  tone,
  term,
  active,
  onSelect,
}: {
  k: string;
  value: string;
  tone: UncTone;
  term?: string;
  active?: boolean;
  onSelect?: (term: string) => void;
}) {
  const body = (
    <>
      <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--so-ink-3)]">{k}</span>
      <span className={cn("font-[family-name:var(--so-display)] text-[15px] tracking-tight", _UNC_TONE_CLASS[tone])}>
        {value}
      </span>
    </>
  );
  if (term && onSelect) {
    return (
      <ExplainableTerm term={term} active={!!active} onSelect={onSelect} className="flex items-baseline gap-2 px-1">
        {body}
      </ExplainableTerm>
    );
  }
  return (
    <div data-term={term} className="flex items-baseline gap-2">
      {body}
    </div>
  );
}

const _ZONE_LABEL =
  "mb-2 font-mono text-[9.5px] uppercase tracking-[0.16em] text-[var(--so-ink-3)]";
// Grid-cell wrapper for a zone — a top hairline + padding; vertical spacing
// between rows is handled by the grid gap, not a margin.
const _ZONE_CELL = "border-t border-[color:var(--so-rule)] pt-3";
const _INTERP_P =
  "max-w-[64ch] font-[family-name:var(--so-serif)] text-[12px] italic leading-relaxed text-[var(--so-ink-3)]";
const _INTERP_KEY = "font-mono text-[10px] not-italic uppercase tracking-[0.12em] text-[var(--so-ink-2)]";

// Uncertainty & funding — four compact zones (State · Drivers · Horizon ·
// Interpretation).  Surfaces the decomposition /market-context already
// computes, driver-first (the observable move leads; severity is a small tag),
// contained to the Section-1 card footprint.  Exported for render tests.
export function UncertaintyCard({
  stress,
  funding,
  creditRegime,
  explanation,
}: {
  stress: StressData | null;
  funding: FundingStressMode | null;
  creditRegime?: CreditRegimeBlock | null;
  explanation?: ContextExplanation | null;
}) {
  // Selected explainable term — drives the in-card explanation panel.  Declared
  // before any early return to satisfy the rules of hooks.
  const [selectedTerm, setSelectedTerm] = useState<string | null>(null);

  const s = _stressRow(stress);
  const f = _fundingRow(funding);
  // Hide the whole card only when both stress and funding are absent.
  if (!s && !f) return null;

  // ZONE 1 — State (quiet labels): stress regime + composite funding severity.
  const fundingSeverity =
    funding && funding.available !== false
      ? _titleCase(funding.composite_severity === "none" ? "Normal" : funding.composite_severity)
      : null;

  // ZONE 2 — Drivers (driver-first): firing funding modes, stress flags, credit.
  const firingModes = selectFiringFundingModes(funding);
  const stressSignals = selectFiringStressSignals(stress);
  const credit = selectCreditConfirmation(creditRegime);
  const leadMode = firingModes[0];
  const hasDrivers = firingModes.length > 0 || stressSignals.length > 0 || !!credit;

  // ZONE 4 — Interpretation: keep meaning, add what-would-change.
  const meaning = _contextExplanationText(explanation?.meaning);
  const whatChanges = _contextExplanationText(explanation?.what_changes_it);

  return (
    <div className="rounded-[4px] border border-[color:var(--so-rule)] bg-[var(--so-bg-1)] px-[18px] py-4">
      <div className="mb-3 font-mono text-[11px] font-medium uppercase tracking-[0.14em] text-[var(--so-ink-2)]">
        Uncertainty &amp; funding
      </div>

      {/* Four zones in a responsive 2-up grid — a full-width module on the
          page; stacks to one column on mobile.  A 4-across layout is
          deliberately avoided: the Interpretation paragraphs would be cramped
          at quarter width, so 2×2 is the widest the content reads cleanly at.
          ``data-term`` hooks on the leaf terms keep them targetable by a later
          explanation layer without wiring any popover here. */}
      <div className="grid grid-cols-1 gap-x-6 gap-y-3.5 sm:grid-cols-2">
        {/* ZONE 1 — STATE (quiet labels) */}
        <div className={_ZONE_CELL}>
          <div className={_ZONE_LABEL}>State</div>
          <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1.5">
            {s && <StateItem k="Stress" value={s.label} tone={s.tone} term="stress_regime" />}
            {fundingSeverity && (
              <StateItem
                k="Funding"
                value={fundingSeverity}
                tone={f?.tone ?? "pos"}
                term="funding_severity"
                active={selectedTerm === "funding_severity"}
                onSelect={setSelectedTerm}
              />
            )}
          </div>
        </div>

        {/* ZONE 2 — DRIVERS (driver-first) */}
        <div className={_ZONE_CELL}>
          <div className={_ZONE_LABEL}>Drivers</div>
          {hasDrivers ? (
            <>
              {firingModes.length > 0 && (
                <div className="space-y-1.5">
                  {firingModes.map((m) => (
                    <FundingModeRow
                      key={m.mode}
                      m={m}
                      active={selectedTerm === m.mode}
                      onSelect={setSelectedTerm}
                    />
                  ))}
                </div>
              )}
              {leadMode && plainMeaning(leadMode.label) && (
                <PlainMeaningLine label={leadMode.label} className="mt-1.5" />
              )}
              {stressSignals.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {stressSignals.map((sig) => (
                    <ExplainableTerm
                      key={sig.key}
                      term={sig.key}
                      active={selectedTerm === sig.key}
                      onSelect={setSelectedTerm}
                      className="border border-[color:var(--so-rule-hi)] px-1.5 py-[2px] font-mono text-[9.5px] tracking-[0.04em] text-[var(--so-ink-2)]"
                    >
                      {sig.label}
                    </ExplainableTerm>
                  ))}
                </div>
              )}
              {credit && (
                <div className="mt-2 flex flex-wrap items-baseline gap-x-2.5">
                  <span className="font-[family-name:var(--so-serif)] text-[12px] text-[var(--so-ink-2)]">
                    {credit.label}
                  </span>
                  {credit.diff != null && (
                    <ExplainableTerm
                      term="hy_ig"
                      active={selectedTerm === "hy_ig"}
                      onSelect={setSelectedTerm}
                      className="px-1 font-mono text-[11px] tabular-nums text-[var(--so-ink-3)]"
                    >
                      HY−IG {credit.diff >= 0 ? "+" : ""}
                      {credit.diff.toFixed(2)}/5d
                    </ExplainableTerm>
                  )}
                </div>
              )}
            </>
          ) : (
            <p className="font-[family-name:var(--so-serif)] text-[12px] italic leading-relaxed text-[var(--so-ink-3)]">
              No funding-stress mode is firing.
            </p>
          )}
        </div>

        {/* ZONE 3 — HORIZON DISCIPLINE (static, descriptive) */}
        <div className={_ZONE_CELL}>
          <div className={_ZONE_LABEL}>Horizon</div>
          <div className="space-y-1">
            {HORIZON_ROWS.map((h) => {
              const term = `horizon_${h.k.toLowerCase()}`;
              return (
                <ExplainableTerm
                  key={h.k}
                  term={term}
                  active={selectedTerm === term}
                  onSelect={setSelectedTerm}
                  className="flex w-full items-baseline gap-2.5 px-1"
                >
                  <span className="w-[60px] shrink-0 font-mono text-[10px] uppercase tracking-[0.08em] text-[var(--so-ink-2)]">
                    {h.k}
                  </span>
                  <span className="min-w-0 font-[family-name:var(--so-serif)] text-[12px]">
                    <span className="text-[var(--so-ink-1)]">{h.label}</span>
                    <span className="text-[var(--so-ink-3)]"> — {h.note}</span>
                  </span>
                </ExplainableTerm>
              );
            })}
          </div>
          <p className="mt-2 font-[family-name:var(--so-serif)] text-[11.5px] italic leading-relaxed text-[var(--so-ink-3)]">
            {HORIZON_DISCIPLINE_NOTE}
          </p>
          <p className="mt-1 font-[family-name:var(--so-serif)] text-[11.5px] italic leading-relaxed text-[var(--so-ink-3)]">
            <span className="font-mono text-[9px] not-italic uppercase tracking-[0.12em] text-[var(--so-ink-2)]">
              Plain meaning:
            </span>{" "}
            {HORIZON_DISCIPLINE_PLAIN}
          </p>
        </div>

        {/* ZONE 4 — INTERPRETATION */}
        <div className={_ZONE_CELL}>
          <div className={_ZONE_LABEL}>Interpretation</div>
          {meaning && (
            <p className={_INTERP_P}>
              <span className={_INTERP_KEY}>Plain meaning:</span> {meaning}
            </p>
          )}
          {whatChanges && (
            <p className={cn(_INTERP_P, meaning && "mt-2")}>
              <span className={_INTERP_KEY}>{INTERPRETATION_WHAT_CHANGES_LABEL}:</span> {whatChanges}
            </p>
          )}
          {!meaning && !whatChanges && (
            <p className="font-[family-name:var(--so-serif)] text-[12px] italic leading-relaxed text-[var(--so-ink-3)]">
              No interpretation available for this snapshot.
            </p>
          )}
        </div>
      </div>

      {/* Explanation panel — a stable in-card research note that updates when a
          term above is selected.  No whole-card expansion, no modal, no
          accordion; the panel reserves a min-height so the card barely jumps. */}
      <ExplanationPanel explanation={getTermExplanation(selectedTerm)} />
    </div>
  );
}

type UncertaintyDisplayEntry = {
  key: string;
  value: string;
  barPct: number;
  rawScore: number;
};

type UncertaintyConcentrationView = {
  entries: UncertaintyDisplayEntry[];
  valueLabel: string;
  emptyCopy: string;
  footer: string;
};

export function buildUncertaintyConcentrationView(
  data: NewsUncertaintyConcentration | null,
): UncertaintyConcentrationView {
  const available = data?.available === true;
  const scope = data?.uncertainty_scope ?? "global";
  const rows = available
    ? (data?.sector_uncertainty ?? [])
        .map((row) => ({ ...row, score: Number(row.score || 0) }))
        .filter((row) => Number.isFinite(row.score) && row.score > 0)
    : [];
  const canShowBars = available && rows.length > 0 && (scope === "sector" || scope === "mixed");
  const totalScore = rows.reduce((acc, row) => acc + row.score, 0);
  const entries = canShowBars && totalScore > 0
    ? rows.slice(0, 5).map((row) => {
        const share = (row.score / totalScore) * 100;
        return {
          key: row.sector,
          value: `${Math.round(share)}%`,
          barPct: Math.max(0, Math.min(100, share)),
          rawScore: row.score,
        };
      })
    : [];

  const emptyCopy = !available
    ? "Sector concentration is unavailable for this snapshot."
    : rows.length > 0
      ? "Sector scores exist, but no sector clears the concentration threshold."
      : "No sector-level uncertainty rows are present in this snapshot.";

  const footer = !available
    ? "The news concentration engine did not return a usable block."
    : entries.length > 0 && scope === "sector"
      ? `${data?.lead_sector ?? "A sector"} leads this read; values are normalized shares of weighted news-uncertainty scores.`
      : entries.length > 0 && scope === "mixed"
        ? "Real sector-level signal is present, but it is spread across sectors; values are normalized shares, not raw scores or ranks."
        : rows.length > 0
          ? "Sector scores are below the concentration threshold, so no bars are shown as a concentrated read."
          : "No sector concentration was detected in the current news snapshot.";

  return {
    entries,
    valueLabel: "weighted score share",
    emptyCopy,
    footer,
  };
}

/**
 * Compute display values for the track-record strip.  Exported for tests.
 *
 * ``avgSupport`` (mean per-event fraction of directional tickers that support
 * the thesis) is the honest lead metric.  ``anySupporting`` is the OR-rule
 * count of events with >=1 supporting ticker — descriptive context only, NOT a
 * validation verdict, since one supporting ticker can outweigh several
 * contradicting ones.  ``anySupportingRate`` keeps the OR-rule rate available
 * but it is deliberately no longer the headline.
 */
export function computeTrackRecordDisplay(data: TrackRecord) {
  const resolved = data.validated + data.contradicted;
  const avgSupport = data.avg_support_ratio !== null
    ? Math.round(data.avg_support_ratio * 100)
    : null;
  const anySupporting = data.validated;
  const anySupportingRate = resolved > 0
    ? Math.round((data.validated / resolved) * 100)
    : null;
  return { resolved, avgSupport, anySupporting, anySupportingRate };
}

// Public-facing non-claim notes for the split lower sections.  Exported so
// the honesty contract is pinned by a unit test (no banned overclaim words).
export const OUTCOME_LEDGER_NOTE =
  "Saved outcomes are descriptive archive reads, not a live trading record.";
export const EVIDENCE_LAYER_NOTE =
  "Evidence pools remain separated by phase and denominator; closed FDR pools are not recomputed here.";

export function TrackRecordStrip({ data, isLoading }: { data?: TrackRecord; isLoading: boolean }) {
  if (isLoading) {
    return (
      <section className="mb-6">
        <Skeleton className="h-24 rounded-lg bg-surface-container-highest" />
      </section>
    );
  }
  // Cold-start hides the card entirely — no stub.  Track record appears once
  // at least one resolved event lands.
  if (!data || data.total === 0) return null;

  const { avgSupport } = computeTrackRecordDisplay(data);

  // Lead with the honest support-strength metric (avg support ratio); the
  // any-supporting / contradicted / unresolved counts follow as descriptive
  // context.  The binary OR-rule "hit rate" is deliberately NOT the headline —
  // one supporting ticker can outweigh several contradicting ones, so an
  // any-supporting count is evidence, not a validation verdict.
  const cells: Array<{ k: string; v: string | number; cls: string }> = [
    { k: "Avg support", v: avgSupport == null ? "—" : `${avgSupport}%`, cls: "text-[var(--so-citrine)]" },
    { k: "Any-supporting", v: data.validated, cls: "text-[var(--so-ink-1)]" },
    { k: "Contradicted", v: data.contradicted, cls: "text-[var(--so-rust-ink)]" },
    { k: "Unresolved", v: data.unresolved, cls: "text-[var(--so-amber)]" },
  ];

  return (
    <section className="mb-4" data-testid="track-record">
      {/* Compact KPI grid — section header now labels it, so the inner
          "Saved-event outcomes" caption is dropped and the numbers are
          sized to read as a tight ledger, not a hero stat. */}
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-[4px] bg-[color:var(--so-rule)] sm:grid-cols-4">
        {cells.map((c) => (
          <div key={c.k} className="bg-[var(--so-bg-1)] px-3.5 py-3">
            <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--so-ink-3)]">
              {c.k}
            </div>
            <div
              className={cn(
                "mt-1.5 font-[family-name:var(--so-display)] text-[22px] font-normal leading-none tracking-tight tabular-nums",
                c.cls,
              )}
            >
              {c.v}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1 font-mono text-[10px] uppercase tracking-[0.1em] text-[var(--so-ink-3)]">
        <span>{data.total} analyzed</span>
        {data.revisit_scored > 0 && <span>{data.revisit_scored} revisit-scored</span>}
        <span>Descriptive evidence, not a verdict</span>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// News freshness chip — pure derivation, exported for tests
// ---------------------------------------------------------------------------

export interface NewsFreshnessState {
  label: string;
  tone: "ok" | "warn" | "error" | "neutral";
}

export function deriveNewsFreshness(meta?: RefreshMeta | null): NewsFreshnessState {
  if (!meta) return { label: "No data", tone: "neutral" };

  if (meta.status === "error")
    return { label: "Feed error", tone: "error" };
  if (meta.status === "throttled")
    return { label: "Throttled", tone: "neutral" };
  if (meta.freshness === "stale")
    return { label: "Stale", tone: "warn" };
  if (meta.status === "degraded" || meta.freshness === "degraded")
    return { label: "Degraded", tone: "warn" };
  if (meta.status === "recent")
    return { label: "Cached", tone: "ok" };

  // status ok + freshness fresh (or missing)
  return { label: "Live", tone: "ok" };
}

const _FRESHNESS_TONE_CLASS: Record<NewsFreshnessState["tone"], string> = {
  ok:      "text-[var(--so-jade-ink)]",
  warn:    "text-[var(--so-amber)]",
  error:   "text-[var(--so-rust-ink)]",
  neutral: "text-[var(--so-ink-3)]",
};
const _FRESHNESS_DOT_CLASS: Record<NewsFreshnessState["tone"], string> = {
  ok:      "bg-[var(--so-jade)]",
  warn:    "bg-[var(--so-amber)]",
  error:   "bg-[var(--so-rust)]",
  neutral: "bg-[var(--so-ink-3)]",
};

// ---------------------------------------------------------------------------
// Latest Headlines — compact cluster strip with analyze action
// ---------------------------------------------------------------------------

function LatestHeadlinesStrip({
  clusters,
  isLoading,
  onAnalyze,
  refreshMeta,
  failedHeadlines,
}: {
  clusters: NewsCluster[];
  isLoading: boolean;
  onAnalyze?: (headline: string, opts?: { eventId?: number; context?: string }) => void;
  refreshMeta?: RefreshMeta | null;
  failedHeadlines?: Set<string>;
}) {
  if (isLoading) {
    return (
      <section className="mt-[26px] border-t border-[color:var(--so-rule)] pt-5 opacity-[0.82]">
        <Skeleton className="mb-3 h-3.5 w-40 bg-[var(--so-bg-2)]" />
        <div className="space-y-2">
          {[1, 2, 3].map((k) => <Skeleton key={k} className="h-7 rounded bg-[var(--so-bg-1)]" />)}
        </div>
      </section>
    );
  }
  if (!clusters || clusters.length === 0) return null;

  // Show top 5 non-low-signal clusters — failed headlines stay visible
  // with an inline indicator (not hidden).
  const top = clusters.filter((c) => !c.low_signal).slice(0, 5);
  if (top.length === 0) return null;

  const freshness = deriveNewsFreshness(refreshMeta);

  // The design's `.mo-heads`: a reduced-prominence footer (≈0.82 opacity),
  // a mono label, and hairline rows of mono source-count + serif headline —
  // it never competes with the three numbered sections above.
  return (
    <section className="mt-[26px] border-t border-[color:var(--so-rule)] pt-5 opacity-[0.82]">
      <div className="mb-2 flex items-center gap-2.5">
        <h2 className="font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-[var(--so-ink-3)]">
          Latest headlines
        </h2>
        <span className={cn(
          "inline-flex items-center gap-1.5 font-mono text-[9px] uppercase tracking-[0.1em] leading-none",
          _FRESHNESS_TONE_CLASS[freshness.tone],
        )}>
          <span className={cn("h-1 w-1 rounded-full", _FRESHNESS_DOT_CLASS[freshness.tone])} />
          {freshness.label}
        </span>
      </div>
      <div className="divide-y divide-[color:var(--so-rule)]">
        {top.map((c, i) => {
          const isFailed = failedHeadlines?.has(c.headline);
          return (
            <div key={i} className="group flex items-baseline gap-3 py-[7px]">
              <span className={cn(
                "w-5 shrink-0 text-right font-mono text-[10.5px] tabular-nums",
                c.source_count >= 3 ? "text-[var(--so-citrine)]" : "text-[var(--so-ink-3)]",
              )}>
                {c.source_count}
              </span>
              <span className={cn(
                "min-w-0 flex-1 font-[family-name:var(--so-serif)] text-[13px] leading-[1.45] line-clamp-1",
                isFailed ? "text-[var(--so-ink-2)]" : "text-[var(--so-ink-1)]",
              )}>
                {c.headline}
              </span>
              {isFailed && (
                <AlertTriangle className="h-2.5 w-2.5 shrink-0 text-[var(--so-rust)]" />
              )}
              {onAnalyze && (
                <button
                  onClick={() => onAnalyze(c.headline, { context: buildClusterContext(c) })}
                  className={cn(
                    "shrink-0 inline-flex items-center gap-1 font-mono text-[9.5px] uppercase tracking-[0.1em] transition-colors",
                    isFailed
                      ? "text-[var(--so-ink-3)] hover:text-[var(--so-citrine)]"
                      : "text-[var(--so-ink-4)] opacity-0 hover:text-[var(--so-citrine)] group-hover:opacity-100",
                  )}
                >
                  <FlaskConical className="h-3 w-3" />
                  {isFailed ? "Retry" : "Analyze"}
                </button>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Section head — hairline top rule, teal mono kicker on the left, numbered
// display subhead on the right.  Shared chrome that carries the three
// viewer-facing section breaks (no background-coloured dividers).
// ---------------------------------------------------------------------------

function SectionHead({
  kicker,
  n,
  title,
  className,
}: {
  kicker: string;
  n: string;
  title: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "mb-5 flex items-baseline gap-4 border-t border-[color:var(--so-rule-hi)] pt-3 pb-1",
        className,
      )}
    >
      <span className="shrink-0 font-mono text-[10.5px] font-medium uppercase tracking-[0.18em] text-[var(--so-citrine)]">
        {kicker}
      </span>
      <h2 className="ml-auto font-[family-name:var(--so-display)] text-[19px] font-normal tracking-tight text-[var(--so-ink-0)]">
        <span className="italic text-[var(--so-citrine)]">{n} ·</span> {title}
      </h2>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Frozen-archive front door (P5B) — helpers, copy, and panels.  The archive is
// a fixed research corpus, not a live feed, so Section 2 reads off the archive
// itself rather than rolling mover windows.
// ---------------------------------------------------------------------------

// Stages that carry no scored thesis (curated stubs / promoted observations).
const _NON_THESIS_STAGES = new Set(["curated_intake", "curated_observation"]);

export const ARCHIVE_SECTION_TITLE = "The archive";
export const ARCHIVE_FRAMING_NOTE =
  "The most recent analyses in the frozen research archive, dated by event and " +
  "read off realized market reactions — a record of past work, not a feed of current activity.";
export const ARCHIVE_CASES_LABEL = "Latest analyzed cases";

export const OUTCOME_BREAKDOWN_DIMENSION = "by_quality_tier" as const;
export const OUTCOME_BREAKDOWN_NOTE =
  "Outcomes by evidence-quality tier — descriptive; any-supporting rate is over resolved events only.";

export const EVIDENCE_LIMITS_TITLE = "Evidence & limits";
export const EVIDENCE_ESTABLISHES_LABEL = "What the evidence establishes";
export const EVIDENCE_NONCLAIMS_LABEL = "What it does not claim";
export const EVIDENCE_NONCLAIMS: readonly string[] = [
  "Descriptive research on dated past events — not a trading or trade-recommendation tool.",
  "Outcome counts are archive reads, not a record of trading performance.",
  "Phase 1 and Phase 2 stay separate FDR pools; nothing is pooled across them.",
  "Regulation evidence was read on a copy and never promoted into a live denominator.",
];

export interface ArchiveCase {
  id: number;
  headline: string;
  eventDate: string | null;
  ticker: string | null;
  statusLabel: string;
  isObservation: boolean;
  /** One-line engine mechanism read; null when the row carries none. */
  mechanismSummary: string | null;
  /** validation_status_v2 ticker tallies; null when the block omits them
   *  (a real 0 is kept — it is information, not absence). */
  supporting: number | null;
  contradicting: number | null;
  /** Lead market ticker's realized 5-day return, in percent units; null when
   *  the list payload carries no return for it.  reaction_profile_v1 is a
   *  detail-route block (GET /events/{id}) and is intentionally not read on
   *  this list surface. */
  reactionReturn5d: number | null;
}

function _leadTicker(mt: SavedEvent["market_tickers"]): string | null {
  if (!Array.isArray(mt) || mt.length === 0) return null;
  const first = mt[0] as { symbol?: string } | undefined;
  return first?.symbol ?? null;
}

function _statusLabel(v2: SavedEvent["validation_status_v2"]): string {
  if (v2 && typeof v2 === "object" && typeof (v2 as { status?: string }).status === "string") {
    return (v2 as { status: string }).status;
  }
  return "—";
}

// Trimmed one-line mechanism read, or null — never an invented summary.
function _mechanismSummary(s: SavedEvent["mechanism_summary"]): string | null {
  const t = (s ?? "").trim();
  return t || null;
}

// Supporting / contradicting ticker tallies off the validation_status_v2
// block.  Each side is null when the block omits it; a real 0 is preserved.
function _supportCounts(
  v2: SavedEvent["validation_status_v2"],
): { supporting: number | null; contradicting: number | null } {
  const counts = v2?.counts;
  return {
    supporting: typeof counts?.supporting === "number" ? counts.supporting : null,
    contradicting: typeof counts?.contradicting === "number" ? counts.contradicting : null,
  };
}

// Reaction read for the displayed lead ticker (market_tickers[0]) — the same
// ticker _leadTicker surfaces, so the return always matches the shown symbol.
// The /events LIST payload does not carry reaction_profile_v1 (it is hydrated
// only on the GET /events/{id} detail route), so the list reaction comes off
// the stored market_tickers return; null when that ticker has no 5-day return.
function _leadReactionReturn5d(mt: SavedEvent["market_tickers"]): number | null {
  if (!Array.isArray(mt) || mt.length === 0) return null;
  const r = (mt[0] as { return_5d?: number | null } | undefined)?.return_5d;
  return typeof r === "number" && Number.isFinite(r) ? r : null;
}

// Evidence subline text: "N supporting · M contradicting".  Returns null —
// so the caller omits the line — when there is no directional evidence to
// show (both tallies absent or zero); a data-less unresolved case already
// reads as such from its status, and repeating "0 supporting · 0
// contradicting" on every such card is noise, not substance.  When at least
// one side is non-zero, both present counts render (a real 0 paired with a
// non-zero other side is the meaningful supported/contradicted read).  Pure —
// unit-tested without rendering.
export function formatSupportCounts(
  supporting: number | null | undefined,
  contradicting: number | null | undefined,
): string | null {
  const sup = typeof supporting === "number" ? supporting : 0;
  const con = typeof contradicting === "number" ? contradicting : 0;
  if (sup === 0 && con === 0) return null;
  const parts: string[] = [];
  if (typeof supporting === "number") parts.push(`${supporting} supporting`);
  if (typeof contradicting === "number") parts.push(`${contradicting} contradicting`);
  return parts.length > 0 ? parts.join(" · ") : null;
}

// "Latest analyzed cases": analysis-stage events first (each sorted by
// event_date desc), then any curated observations (flagged), capped at limit.
// /events has no sort param, so the ordering happens here — never insertion order.
export function pickLatestAnalyzedCases(items: SavedEvent[], limit: number): ArchiveCase[] {
  const byDateDesc = (a: SavedEvent, b: SavedEvent) =>
    (b.event_date ?? "").localeCompare(a.event_date ?? "");
  const analysis = items.filter((e) => !_NON_THESIS_STAGES.has(e.stage)).sort(byDateDesc);
  const observations = items.filter((e) => _NON_THESIS_STAGES.has(e.stage)).sort(byDateDesc);
  return [...analysis, ...observations].slice(0, Math.max(0, limit)).map((e) => {
    const { supporting, contradicting } = _supportCounts(e.validation_status_v2);
    return {
      id: e.id,
      headline: e.headline,
      eventDate: e.event_date ?? null,
      ticker: _leadTicker(e.market_tickers),
      statusLabel: _statusLabel(e.validation_status_v2),
      isObservation: _NON_THESIS_STAGES.has(e.stage),
      mechanismSummary: _mechanismSummary(e.mechanism_summary),
      supporting,
      contradicting,
      reactionReturn5d: _leadReactionReturn5d(e.market_tickers),
    };
  });
}

// quality_tier is present in the live /breakdown payload but not yet declared on
// the TrackRecordBreakdown TS type; read it through a narrow cast so lib/api.ts
// stays untouched.  family / subtype / tradable / compound / policy are
// degenerate on this archive and deliberately never read here.
interface _QualityTierBucket extends TrackRecordBreakdownBucket {
  tier?: string;
}
export function qualityTierBuckets(bd: TrackRecordBreakdown | undefined): _QualityTierBucket[] {
  const ext = bd as
    | (TrackRecordBreakdown & { by_quality_tier?: _QualityTierBucket[] })
    | undefined;
  const list = ext?.by_quality_tier;
  return Array.isArray(list) ? list.filter((b) => (b.total ?? 0) > 0) : [];
}

// ---- presentational panels (Direction-C --so-* language) ----

function ArchiveCasesPanel({
  cases,
  total,
  trackRecord,
  onAnalyze,
}: {
  cases: ArchiveCase[];
  total: number | null;
  trackRecord?: TrackRecord;
  onAnalyze?: (headline: string, opts?: { eventId?: number }) => void;
}) {
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-baseline gap-x-4 gap-y-1 font-mono text-[10px] uppercase tracking-[0.1em] text-[var(--so-ink-3)]">
        {total != null && (
          <span>
            <span className="tabular-nums text-[var(--so-ink-1)]">{total}</span> events in the active archive
          </span>
        )}
        {trackRecord && (
          <span>
            <span className="tabular-nums text-[var(--so-jade-ink)]">{trackRecord.validated}</span> any-supporting ·{" "}
            <span className="tabular-nums text-[var(--so-rust-ink)]">{trackRecord.contradicted}</span> contradicted ·{" "}
            <span className="tabular-nums">{trackRecord.unresolved}</span> unresolved
          </span>
        )}
      </div>
      <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--so-ink-2)]">
        {ARCHIVE_CASES_LABEL}
      </div>
      {cases.length > 0 ? (
        <div className="divide-y divide-[color:var(--so-rule)] overflow-hidden rounded-[4px] border border-[color:var(--so-rule)]">
          {cases.map((c) => {
            const counts = formatSupportCounts(c.supporting, c.contradicting);
            const reactionTone =
              c.reactionReturn5d == null
                ? ""
                : c.reactionReturn5d > 0
                  ? "text-[var(--so-jade-ink)]"
                  : c.reactionReturn5d < 0
                    ? "text-[var(--so-rust-ink)]"
                    : "text-[var(--so-ink-2)]";
            const hasMeta = c.reactionReturn5d != null || counts != null;
            return (
              <button
                key={c.id}
                type="button"
                onClick={() => onAnalyze?.(c.headline, { eventId: c.id })}
                className="group grid w-full grid-cols-[64px_1fr] items-start gap-x-3 px-4 py-2.5 text-left transition-colors hover:bg-[var(--so-bg-2)]"
              >
                <span className="pt-px font-mono text-[11px] tabular-nums text-[var(--so-ink-3)]">
                  {c.eventDate ?? "—"}
                </span>
                <span className="min-w-0">
                  {/* Row 1 — headline + lead ticker, with the validation status
                      (or "observation" flag) pinned right; unchanged density. */}
                  <span className="flex items-baseline gap-2">
                    <span className="min-w-0 flex-1 truncate font-[family-name:var(--so-serif)] text-[12.5px] text-[var(--so-ink-1)]">
                      {c.ticker && <span className="font-mono text-[var(--so-ink-2)]">{c.ticker} </span>}
                      {c.headline}
                    </span>
                    <span className="shrink-0 font-mono text-[9px] uppercase tracking-[0.1em] text-[var(--so-ink-3)]">
                      {c.isObservation ? "observation" : c.statusLabel}
                    </span>
                  </span>
                  {/* Mechanism read — one clamped line, omitted when absent so a
                      curated stub never shows an invented thesis. */}
                  {c.mechanismSummary && (
                    <span className="mt-1 block truncate font-[family-name:var(--so-serif)] text-[11.5px] italic leading-snug text-[var(--so-ink-2)]">
                      {c.mechanismSummary}
                    </span>
                  )}
                  {/* Meta — realized 5-day reaction of the lead ticker (coloured
                      by sign, a factual move not a verdict) and the evidence
                      tally; each part renders only when present. */}
                  {hasMeta && (
                    <span className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-0.5 font-mono text-[10px] tracking-[0.04em] text-[var(--so-ink-3)]">
                      {c.reactionReturn5d != null && (
                        <span className="tabular-nums">
                          <span className="text-[var(--so-ink-4)]">5d </span>
                          <span className={reactionTone}>{pct(c.reactionReturn5d)}</span>
                        </span>
                      )}
                      {counts && <span className="tabular-nums">{counts}</span>}
                    </span>
                  )}
                </span>
              </button>
            );
          })}
        </div>
      ) : (
        <div className="rounded-[4px] border border-dashed border-[color:var(--so-rule)] px-4 py-3 font-[family-name:var(--so-serif)] text-[13px] italic text-[var(--so-ink-3)]">
          No analyzed cases in the archive.
        </div>
      )}
      <p className="mt-2.5 font-[family-name:var(--so-serif)] text-[12px] italic leading-relaxed text-[var(--so-ink-3)]">
        {ARCHIVE_FRAMING_NOTE}
      </p>
    </div>
  );
}

function QualityTierBreakdown({
  breakdown,
  isLoading,
}: {
  breakdown?: TrackRecordBreakdown;
  isLoading: boolean;
}) {
  if (isLoading) return null;
  const buckets = qualityTierBuckets(breakdown);
  if (buckets.length === 0) return null;
  return (
    <div className="mt-3.5">
      <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--so-ink-3)]">
        Outcomes by evidence-quality tier
      </div>
      <div className="grid grid-cols-1 gap-px overflow-hidden rounded-[4px] bg-[color:var(--so-rule)] sm:grid-cols-2">
        {buckets.map((b, i) => (
          <div key={b.tier ?? i} className="bg-[var(--so-bg-1)] px-3.5 py-2.5">
            <div className="flex items-baseline justify-between">
              <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-[var(--so-ink-2)]">
                {b.tier ? _titleCase(b.tier) : "tier"}
              </span>
              <span className="font-mono text-[11px] tabular-nums text-[var(--so-citrine)]">{b.total}</span>
            </div>
            <div className="mt-1.5 flex items-baseline gap-3 font-mono text-[11px] tabular-nums">
              <span className="text-[var(--so-jade-ink)]">{b.validated} any-sup</span>
              <span className="text-[var(--so-rust-ink)]">{b.contradicted} con</span>
              <span className="ml-auto text-[var(--so-ink-3)]">
                {b.hit_rate != null ? `${Math.round(b.hit_rate * 100)}% any-sup` : "—"}
              </span>
            </div>
          </div>
        ))}
      </div>
      <p className="mt-2 font-[family-name:var(--so-serif)] text-[11.5px] italic leading-relaxed text-[var(--so-ink-3)]">
        {OUTCOME_BREAKDOWN_NOTE}
      </p>
    </div>
  );
}

function EvidenceNonClaims() {
  return (
    <div className="mt-3 rounded-[4px] border border-dashed border-[color:var(--so-rule)] bg-[var(--so-bg-1)] px-4 py-3">
      <div className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-[var(--so-ink-2)]">
        {EVIDENCE_NONCLAIMS_LABEL}
      </div>
      <ul className="space-y-1">
        {EVIDENCE_NONCLAIMS.map((c) => (
          <li
            key={c}
            className="font-[family-name:var(--so-serif)] text-[12px] italic leading-snug text-[var(--so-ink-3)]"
          >
            <span className="text-[var(--so-citrine)]">·</span> {c}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Headline-analysis intake (P6) — the always-available "start here" entry.
// Routes any free-text headline into the existing onAnalyze flow; the
// LatestHeadlinesStrip footer remains the real-news browse affordance.
// ---------------------------------------------------------------------------

export const INTAKE_TITLE = "Start an analysis";
export const INTAKE_PLACEHOLDER = "Paste a market-relevant headline…";
export const INTAKE_BUTTON = "Analyze headline";
export const INTAKE_BROWSE_LINK = "Browse Headlines inbox";
export const INTAKE_ORIENTATION =
  "Paste a headline, run the mechanism read, then compare it against the archive and evidence limits below.";

// Returns true and calls onAnalyze(trimmed) for non-blank input; ignores
// empty / whitespace-only input.  Pure, so the submit guard is unit-tested
// without rendering.
export function intakeSubmit(
  raw: string,
  onAnalyze?: (headline: string) => void,
): boolean {
  const trimmed = raw.trim();
  if (!trimmed) return false;
  onAnalyze?.(trimmed);
  return true;
}

export function HeadlineIntake({
  onAnalyze,
  onOpenHeadlines,
}: {
  onAnalyze?: (headline: string, opts?: { eventId?: number; context?: string }) => void;
  onOpenHeadlines?: () => void;
}) {
  const [value, setValue] = useState("");
  const submit = () => {
    if (intakeSubmit(value, (h) => onAnalyze?.(h))) setValue("");
  };
  return (
    <div className="rounded-[4px] border border-[color:var(--so-rule)] bg-[var(--so-bg-1)] px-4 py-3.5">
      <div className="mb-2 font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-[var(--so-citrine)]">
        {INTAKE_TITLE}
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        className="flex flex-col gap-2 sm:flex-row sm:items-center"
      >
        <input
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={INTAKE_PLACEHOLDER}
          aria-label={INTAKE_TITLE}
          className="min-w-0 flex-1 rounded-[3px] border border-[color:var(--so-rule)] bg-[var(--so-bg-2)] px-3 py-2 font-[family-name:var(--so-serif)] text-[13px] text-[var(--so-ink-1)] placeholder:text-[var(--so-ink-3)] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[color:var(--so-rule-hi)]"
        />
        <button
          type="submit"
          disabled={!value.trim()}
          className="shrink-0 rounded-[3px] border border-[color:var(--so-rule-hi)] px-3.5 py-2 font-mono text-[11px] uppercase tracking-[0.1em] text-[var(--so-citrine)] transition-colors hover:bg-[var(--so-bg-2)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {INTAKE_BUTTON}
        </button>
      </form>
      <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <p className="min-w-0 font-[family-name:var(--so-serif)] text-[11.5px] italic leading-relaxed text-[var(--so-ink-3)]">
          {INTAKE_ORIENTATION}
        </p>
        {onOpenHeadlines && (
          <button
            type="button"
            onClick={onOpenHeadlines}
            className="ml-auto shrink-0 font-mono text-[10px] uppercase tracking-[0.1em] text-[var(--so-ink-2)] transition-colors hover:text-[var(--so-citrine)]"
          >
            {INTAKE_BROWSE_LINK} <span className="text-[var(--so-citrine)]">→</span>
          </button>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function MarketOverview({ onAnalyze, failedHeadlines, onOpenHeadlines }: {
  onAnalyze?: (headline: string, opts?: { eventId?: number; context?: string }) => void;
  failedHeadlines?: Set<string>;
  onOpenHeadlines?: () => void;
}) {
  // Single normalized market context fetch — replaces the previous separate
  // /snapshots, /stress, and /movers/today queries.  Stress + benchmarks +
  // today's highlights all come from one request, with consistent freshness.
  const { data: ctx, isLoading: ctxLoading, error: ctxError } = useQuery({
    queryKey: qk.marketContext(),
    queryFn: () => api.marketContext(10),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  // The frozen research archive itself — the active-listing page feeds both the
  // at-a-glance count and the "latest analyzed cases" list (sorted client-side
  // by event_date; /events has no sort param).
  const { data: archive, isLoading: archiveLoading, error: archiveError } = useQuery({
    queryKey: ["market-overview-archive-events", 50] as const,
    queryFn: () => api.events({ limit: 50 }),
    staleTime: 300_000,
  });

  // Outcome breakdown — only the verified-populated by_quality_tier slice is
  // read (see qualityTierBuckets); the family/subtype/tradable slices are
  // degenerate on this archive and intentionally unused.
  const { data: breakdown, isLoading: breakdownLoading } = useQuery({
    queryKey: ["market-overview-track-record-breakdown"] as const,
    queryFn: () => api.trackRecordBreakdown(),
    staleTime: 300_000,
  });

  const { data: trackRecord, isLoading: trackLoading } = useQuery({
    queryKey: qk.trackRecord(),
    queryFn: () => api.trackRecord(),
    staleTime: 300_000,
  });

  // Recent-headlines footer query — kept while LatestHeadlinesStrip
  // still sits at the bottom of the page; moves with that strip when
  // the next slice rehomes it onto the Headlines / Inbox surface.
  const { data: newsData, isLoading: newsLoading } = useQuery({
    queryKey: qk.newsPaginated(30),
    queryFn: () => api.news(30),
    staleTime: 300_000,
  });

  // Tracked Phase 1 + Phase 2 evidence layer.  Read-only call to the
  // tracked-only ``GET /evidence/summary`` route; renders nothing on
  // first paint and slots in beneath the existing TrackRecord strip
  // once the envelope arrives.  Long staleTime — the underlying
  // artifacts only change on a tracked commit.
  const { data: trackedEvidence, isLoading: trackedEvidenceLoading } = useQuery({
    queryKey: qk.trackedEvidenceSummary(),
    queryFn: () => api.trackedEvidenceSummary(),
    staleTime: 1_800_000,
  });

  // Distribute the unified context to child components.
  const stress = ctx?.stress ?? null;
  const regimeVec = ctx?.regime_vector ?? null;
  const snapshots = ctx?.snapshots ?? null;
  const contextExplanations = ctx?.context_explanations ?? {};
  const archiveTotal = archive?.total ?? null;
  const latestCases = pickLatestAnalyzedCases(archive?.items ?? [], 5);

  // Surface a single inline error banner when any of the top-level queries
  // fail.  Without this, a backend that's unreachable on first start would
  // render the page completely blank (every section gracefully hides on
  // empty data) and the user would have no idea something went wrong.
  // Picks the first error so the banner is one line, not three.
  const firstError = ctxError ?? archiveError;
  const errorMessage = firstError instanceof Error ? firstError.message : null;

  // True cold-start empty: every archive-derived channel finished loading
  // and there is genuinely nothing to show.  Any populated surface — movers,
  // track record, or tracked evidence — suppresses the "No archive yet"
  // nudge; if a channel is still loading we treat it as "might have data" and
  // hide the nudge rather than risk a false cold-start message.
  const allLoaded =
    !ctxLoading && !archiveLoading && !breakdownLoading
    && !trackLoading && !trackedEvidenceLoading;
  const hasTrackRecord = !!trackRecord && trackRecord.total > 0;
  const hasTrackedEvidence =
    !!trackedEvidence
    && ((trackedEvidence.summary?.phase1_count ?? 0) > 0
      || (trackedEvidence.summary?.phase2_count ?? 0) > 0);
  const isColdStart =
    allLoaded
    && !firstError
    && (archive?.total ?? 0) === 0
    && latestCases.length === 0
    && !hasTrackRecord
    && !hasTrackedEvidence;

  return (
    // Page-level flow: no nested overflow container, no h-full reliance.
    // The shell scrolls the whole document; this page just stacks its
    // sections.  ``SO_VARS`` scopes the design-package palette to this page
    // (inherited by the snapshot strip and mover cards) so the page is
    // styled to the zip rather than the app's teal/sans theme.
    <div className="space-y-0 text-[var(--so-ink-1)]" style={SO_VARS}>
      {/* Inline error banner — only renders when one of the top-level
          queries failed.  Keeps the rest of the page rendering its own
          empty states so partial degradation still works. */}
      {errorMessage && (
        <div
          role="alert"
          className="mb-4 flex items-center gap-3.5 rounded-[4px] border border-[color:var(--so-bd-rust)] bg-[rgba(201,112,100,0.05)] px-3.5 py-2.5"
        >
          <span className="shrink-0 rounded-[2px] border border-[color:var(--so-rust)] px-[7px] py-0.5 font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-[var(--so-rust-ink)]">
            Error
          </span>
          <span className="min-w-0 font-[family-name:var(--so-serif)] text-[13px] italic text-[var(--so-ink-2)]">
            Market data unavailable — <span className="break-words not-italic font-mono text-[11.5px] text-[var(--so-ink-1)]">{errorMessage}</span>
          </span>
        </div>
      )}

      {/* Cold-start empty state — only when every channel loaded cleanly
          but there is genuinely nothing to show.  A first-run user sees
          the design's centred cold-start panel, not a stack of empty boxes. */}
      {isColdStart && (
        <div className="mb-6 grid min-h-[280px] place-items-center rounded-[4px] border border-[color:var(--so-rule)] bg-[var(--so-bg-1)] p-10 text-center">
          <div className="max-w-[460px]">
            <div className="mb-3.5 font-mono text-[10.5px] uppercase tracking-[0.18em] text-[var(--so-citrine)]">
              — Cold start
            </div>
            <h3 className="font-[family-name:var(--so-display)] text-[30px] font-normal leading-[1.22] tracking-tight text-[var(--so-ink-0)]">
              No archive <em className="italic text-[var(--so-citrine)]">yet.</em>
            </h3>
            <p className="mt-3.5 font-[family-name:var(--so-serif)] text-[14.5px] leading-[1.55] text-[var(--so-ink-2)]">
              Run an analysis from the Headlines page to start populating Market Overview.
            </p>
          </div>
        </div>
      )}

      {/* Degraded-context notice — a single compact line (24px) when
          snapshots are stale or a provider is down.  Per-cell "· stale"
          tags in the snapshot row carry the detail; this never expands into
          a large block above Section 1. */}
      <DegradedContextNotice ctx={ctx} className="mb-4" />

      {/*
        Three-section composition, matched to the viewer's three
        questions: what is the tape doing, which named events are
        moving things, and what is the system's record.  Every section
        degrades gracefully — when a sub-query returns empty or null,
        the affected card renders an empty-state line or hides
        entirely so a cold or partial clone still reads as intentional.
      */}

      {/* ────────────── 1 · MARKET BACKDROP ────────────── */}
      <SectionHead kicker="Snapshot" n="1" title="Market backdrop" className="mt-1" />
      <p className="mt-1.5 font-[family-name:var(--so-serif)] text-[12px] italic leading-relaxed text-[var(--so-ink-3)]">
        {HOWTO_MARKET_BACKDROP}
      </p>

      {/* Liquid Benchmark Snapshots — a single hairline-gridded mono row.
          Hides cleanly when ``snapshots`` is null; the degraded banner
          already explains why.  ``mt-4`` lifts the row off the how-to-read
          line so it reads as its own band, not part of the header. */}
      <div className="mt-4">
        <BenchmarkSnapshotsStrip snapshots={snapshots} isLoading={ctxLoading} />
      </div>

      {/* P8D: Regime read (compact band) stacked above a full-width Uncertainty
          & Funding module.  The old 2-up [1.25fr_1fr] inverted content weight —
          the sparse Regime card took the wide column while the now four-zone
          Uncertainty module was crammed into the narrow one.  Stacking gives
          Uncertainty the full page width (its zones lay out 2×2 internally) and
          lets Regime read as a thin band.  Spacing uses padding + a nested
          space-y because the page root's ``space-y-0`` overrides ``mt-*`` on
          direct children (see the intake note below); ``space-y-4`` here
          applies to this wrapper's own children, so it is not overridden. */}
      <div className="pt-6 space-y-4">
        <RegimeVectorCard
          regimeVec={regimeVec}
          explanation={contextExplanations.regime_vector}
        />
        <UncertaintyCard
          stress={stress}
          funding={ctx?.funding_stress_mode ?? null}
          creditRegime={ctx?.credit_regime ?? null}
          explanation={contextExplanations.stress}
        />
      </div>

      {/* Headline-analysis intake — the always-available "start here" path.
          The LatestHeadlinesStrip footer remains the real-news browse
          affordance; this never empties and never reads as a live feed.
          Separation from the backdrop two-card row is PADDING, not margin:
          the page root's ``space-y-0`` sets ``margin-top: 0`` on every
          non-first child at a higher specificity than ``mt-*``, so a top
          margin renders as no gap (this is why the earlier ``mt-14`` did
          nothing).  ``pt-16`` gives real dark-space breathing room so the
          intake reads as a separate entry point below the backdrop. */}
      <div className="pt-16">
        <HeadlineIntake onAnalyze={onAnalyze} onOpenHeadlines={onOpenHeadlines} />
      </div>

      {/* ────────────── 2 · THE ARCHIVE ────────────── */}
      <SectionHead kicker="Archive" n="2" title={ARCHIVE_SECTION_TITLE} className="mt-14" />
      <p className="mt-1.5 mb-2.5 font-[family-name:var(--so-serif)] text-[12px] italic leading-relaxed text-[var(--so-ink-3)]">
        {HOWTO_ARCHIVE}
      </p>

      {/* The frozen research corpus, not a live feed: an at-a-glance count +
          the most recent analyzed cases (sorted by event_date, never insertion
          order; curated rows are flagged as observations, not theses). */}
      <ArchiveCasesPanel
        cases={latestCases}
        total={archiveTotal}
        trackRecord={trackRecord}
        onAnalyze={onAnalyze}
      />

      {/* ────────────── 3 · OUTCOME LEDGER ────────────── */}
      <SectionHead kicker="Outcome" n="3" title="Outcome ledger" className="mt-11" />
      <p className="mt-1.5 mb-2.5 font-[family-name:var(--so-serif)] text-[12px] italic leading-relaxed text-[var(--so-ink-3)]">
        {HOWTO_OUTCOME_LEDGER}
      </p>

      {/* Saved-event outcomes — compact KPI strip.  Hides on cold-start
          (no resolved events yet); the note keeps the section honestly
          labelled either way. */}
      <TrackRecordStrip data={trackRecord} isLoading={trackLoading} />
      <QualityTierBreakdown breakdown={breakdown} isLoading={breakdownLoading} />
      <p className="mt-2.5 font-[family-name:var(--so-serif)] text-[12px] italic leading-relaxed text-[var(--so-ink-3)]">
        {OUTCOME_LEDGER_NOTE}
      </p>

      {/* ────────────── 4 · EVIDENCE & LIMITS ────────────── */}
      <SectionHead kicker="Evidence" n="4" title={EVIDENCE_LIMITS_TITLE} className="mt-11" />
      <p className="mt-1.5 mb-2.5 font-[family-name:var(--so-serif)] text-[12px] italic leading-relaxed text-[var(--so-ink-3)]">
        {HOWTO_EVIDENCE}
      </p>
      <div className="mt-2.5 mb-1 font-mono text-[10px] uppercase tracking-[0.12em] text-[var(--so-ink-2)]">
        {EVIDENCE_ESTABLISHES_LABEL}
      </div>

      {/* Tracked evidence layer — Phase 1 + Phase 2 evidence read
          straight from the tracked ``GET /evidence/summary`` route.  The
          card renders Phase 1 and Phase 2 as separate columns, the
          deferred-lessons count, and the methodology / phase-history
          references, and surfaces the envelope's ``fdr_scope_note``
          verbatim so the FDR-scope disclaimer never drifts between the
          backend and the UI. */}
      {/* Denominator visibility (R4C) — screened track-record coverage beside
          the closed FDR pools, kept as two separate bands so a reader sees how
          few events reach the rigorous pool without reading the gates as one
          funnel.  Composes data already fetched above; no new request. */}
      <div className="pt-1">
        <EvidenceCoverageCard
          trackRecord={trackRecord}
          evidence={trackedEvidence}
          isLoading={trackLoading || trackedEvidenceLoading}
        />
      </div>
      <div className="pt-2.5">
        <TrackedEvidenceCard
          data={trackedEvidence}
          isLoading={trackedEvidenceLoading}
        />
      </div>
      <p className="mt-2.5 font-[family-name:var(--so-serif)] text-[12px] italic leading-relaxed text-[var(--so-ink-3)]">
        {EVIDENCE_LAYER_NOTE}
      </p>
      <EvidenceNonClaims />

      {/* Recent headlines — kept as a quiet footer per the Slice 2
          design package; the next slice moves this surface onto the
          Headlines / Inbox page.  Not part of the three numbered
          sections above. */}
      <LatestHeadlinesStrip
        clusters={newsData?.clusters ?? []}
        isLoading={newsLoading}
        onAnalyze={onAnalyze}
        refreshMeta={newsData?.refresh_meta}
        failedHeadlines={failedHeadlines}
      />
    </div>
  );
}
