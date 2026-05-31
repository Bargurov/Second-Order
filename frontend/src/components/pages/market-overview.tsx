import type { CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { AlertTriangle, FlaskConical, ChevronDown } from "lucide-react";
import {
  api,
  type ContextExplanation,
  type MarketMover,
  type TrackRecord,
  type NewsCluster,
  type RegimeVector,
  type RefreshMeta,
  type NewsUncertaintyConcentration,
  type StressRegime,
  type FundingStressMode,
} from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";
import { buildClusterContext } from "@/lib/cluster-context";
import { BenchmarkSnapshotsStrip } from "@/components/ui/benchmark-snapshots-strip";
import { TrackedEvidenceCard } from "@/components/ui/tracked-evidence-card";
import { DegradedContextNotice } from "@/components/ui/degraded-data-notice";
import {
  MoversSectionHead,
  MoverEmptyLine,
  TodayMoverCard,
  WeeklyMoverCard,
  PersistentMoverRow,
} from "@/components/ui/mover-cards";

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

// ---------------------------------------------------------------------------
// Movers chapter — three visually-distinct windows.  Card components live in
// ``mover-cards.tsx``; this page composes them with section heads that match
// the design package.
// ---------------------------------------------------------------------------

function MoversChapter({
  today,
  weekly,
  persistent,
  todayLoading,
  weeklyLoading,
  persistentLoading,
  onAnalyze,
}: {
  today: MarketMover[] | undefined;
  weekly: MarketMover[] | undefined;
  persistent: MarketMover[] | undefined;
  todayLoading: boolean;
  weeklyLoading: boolean;
  persistentLoading: boolean;
  onAnalyze?: (headline: string, opts?: { eventId?: number; context?: string }) => void;
}) {
  const todayList = today ?? [];
  const weeklyList = weekly ?? [];
  // Backend already gates /movers/persistent to high-impact conviction items.
  // (``is_high_conviction_persistent``).  No extra filter on this surface —
  // showing the response verbatim is the contract.
  const persistentList = persistent ?? [];

  return (
    <section>
      {/* TODAY — 4-up clean mono cards; caption sits below the grid. */}
      <div className="mb-7">
        <MoversSectionHead
          title="Today"
          sub="last 24h · event-linked"
          count={todayList.length}
        />
        {todayLoading ? (
          <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
            {[1, 2, 3, 4].map((k) => (
              <Skeleton key={k} className="h-28 rounded-[4px] bg-surface-container-low" />
            ))}
          </div>
        ) : todayList.length > 0 ? (
          <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
            {todayList.slice(0, 8).map((m) => (
              <TodayMoverCard key={m.event_id} mover={m} onAnalyze={onAnalyze} />
            ))}
          </div>
        ) : (
          <MoverEmptyLine>No event-linked moves in the last 24 hours.</MoverEmptyLine>
        )}
        <p className="mt-2.5 font-[family-name:var(--so-serif)] text-[12px] italic leading-relaxed text-[var(--so-ink-3)]">
          Event-linked moves; not validated until evidence broadens.
        </p>
      </div>

      {/* WEEKLY — 2-up cards. */}
      <div className="mb-7">
        <MoversSectionHead
          title="This week"
          sub="5-day curated review set"
          count={weeklyList.length}
        />
        {weeklyLoading ? (
          <div className="grid grid-cols-1 gap-2.5 lg:grid-cols-2">
            {[1, 2].map((k) => (
              <Skeleton key={k} className="h-32 rounded-[4px] bg-surface-container-low" />
            ))}
          </div>
        ) : weeklyList.length > 0 ? (
          <div className="grid grid-cols-1 gap-2.5 lg:grid-cols-2">
            {weeklyList.slice(0, 6).map((m) => (
              <WeeklyMoverCard key={m.event_id} mover={m} onAnalyze={onAnalyze} />
            ))}
          </div>
        ) : (
          <MoverEmptyLine>No 5-day confirmed movers yet.</MoverEmptyLine>
        )}
      </div>

      {/* PERSISTENT — Still Moving Markets, gated to high-impact conviction
          by the backend.  Empty means no qualified rows; do not backfill
          with medium-impact or low-information filler.  Rendered as hairline
          rows inside a single bordered container, per the design package. */}
      <div className="mb-4">
        <MoversSectionHead
          title="Still moving markets"
          sub="high-impact effects beyond the initial reaction"
          count={persistentList.length}
        />
        {persistentLoading ? (
          <div className="overflow-hidden rounded-[4px] border border-[color:var(--so-rule)]">
            {[1, 2, 3].map((k) => (
              <Skeleton key={k} className="h-[58px] rounded-none bg-[var(--so-bg-1)]" />
            ))}
          </div>
        ) : persistentList.length > 0 ? (
          <div className="divide-y divide-[color:var(--so-rule)] overflow-hidden rounded-[4px] border border-[color:var(--so-rule)]">
            {persistentList.map((m) => (
              <PersistentMoverRow key={m.event_id} mover={m} onAnalyze={onAnalyze} />
            ))}
          </div>
        ) : (
          <MoverEmptyLine>No high-impact persistent movers qualify.</MoverEmptyLine>
        )}
      </div>
    </section>
  );
}

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

function ContextExplanationDisclosure({
  explanation,
  className,
}: {
  explanation?: ContextExplanation | null;
  className?: string;
}) {
  const meaning = _contextExplanationText(explanation?.meaning);
  const whatChangesIt = _contextExplanationText(explanation?.what_changes_it);
  if (!meaning && !whatChangesIt) return null;

  return (
    <details className={cn("group mt-3.5 border-t border-dashed border-[color:var(--so-rule-hi)] pt-2.5", className)}>
      <summary className="flex cursor-pointer list-none items-center gap-2 marker:hidden">
        <ChevronDown className="h-3 w-3 text-[var(--so-citrine)] transition-transform group-open:rotate-180" />
        <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-[var(--so-ink-3)] group-hover:text-[var(--so-ink-1)]">
          How to read this
        </span>
      </summary>
      <div className="mt-2.5 max-w-[56ch] space-y-1.5 font-[family-name:var(--so-serif)] text-[12.5px] leading-relaxed text-[var(--so-ink-2)]">
        {meaning && (
          <p>
            <span className="text-[var(--so-ink-1)]">Meaning: </span>
            {meaning}
          </p>
        )}
        {whatChangesIt && (
          <p>
            <span className="text-[var(--so-ink-1)]">What changes it: </span>
            {whatChangesIt}
          </p>
        )}
      </div>
    </details>
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

function RegimeVectorCard({
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
  const title = (
    <div className="mb-3.5 font-mono text-[11px] font-medium uppercase tracking-[0.14em] text-[var(--so-ink-2)]">
      Regime read
    </div>
  );

  if (!regimeVec?.available) {
    return (
      <div className="rounded-[4px] border border-[color:var(--so-rule)] bg-[var(--so-bg-1)] px-[18px] py-4">
        {title}
        <p className="font-[family-name:var(--so-serif)] text-[13px] italic leading-relaxed text-[var(--so-ink-3)]">
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
    <div className="rounded-[4px] border border-[color:var(--so-rule)] bg-[var(--so-bg-1)] px-[18px] py-4">
      {title}
      <h3 className="font-[family-name:var(--so-display)] text-[20px] font-normal leading-[1.28] tracking-tight text-[var(--so-ink-0)] max-w-[30ch]">
        {isLocked ? _humanizeCompound(compoundLabel) : "No dominant regime pattern"}
      </h3>
      <div className="mt-2.5 flex items-baseline gap-2 font-mono text-[10.5px] uppercase tracking-[0.12em] text-[var(--so-ink-3)]">
        <span>Confidence</span>
        <span className="tabular-nums text-[var(--so-amber)]">
          {isLocked ? (confPct == null ? "—" : `${confPct}%`) : "—"}
        </span>
      </div>
      {compoundRationale && (
        <p className="mt-3 font-[family-name:var(--so-serif)] text-[13px] leading-[1.55] text-[var(--so-ink-2)] max-w-[60ch]">
          {compoundRationale}
        </p>
      )}
      {offNeutral.length > 0 && (
        <div className="mt-3.5 flex flex-wrap gap-1.5">
          {offNeutral.map((a) => (
            <AxisChip key={a.key} axis={a} />
          ))}
        </div>
      )}
      {neutral.length > 0 && (
        <div className="mt-2.5 font-mono text-[10px] tracking-[0.03em] text-[var(--so-ink-3)]">
          {neutral.length} {neutral.length === 1 ? "axis" : "axes"} neutral · {neutral.map((a) => a.label).join(" · ")}
        </div>
      )}
      {unread.length > 0 && (
        <div className="mt-1 font-mono text-[10px] tracking-[0.03em] text-[var(--so-ink-4)]">
          {unread.length} {unread.length === 1 ? "axis" : "axes"} without a current read · {unread.map((a) => a.label).join(" · ")}
        </div>
      )}
      <ContextExplanationDisclosure explanation={explanation} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Uncertainty & funding — compact three-row card (Stress · Funding ·
// Concentration), per the Slice 02 design package.  Replaces the heavy
// full-width stress-strip on this page; reads real stress / funding /
// concentration data.  Design palette: quiet/normal reads jade, the
// concentration breadth-caveat and an unsettled watch read amber, genuine
// stress reads rust — a state read, never a directional verdict.
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

function UncRow({ k, label, note, tone }: { k: string } & UncRowData) {
  return (
    <div className="grid grid-cols-[92px_1fr] items-baseline gap-3 py-2.5">
      <dt className="font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--so-ink-3)]">
        {k}
      </dt>
      <dd className="m-0 flex min-w-0 items-baseline gap-2">
        <span className={cn("shrink-0 font-[family-name:var(--so-display)] text-[17px] tracking-tight", _UNC_TONE_CLASS[tone])}>
          {label}
        </span>
        {note && (
          <span className="truncate font-[family-name:var(--so-serif)] text-[12px] italic text-[var(--so-ink-3)]">
            {note}
          </span>
        )}
      </dd>
    </div>
  );
}

function UncertaintyCard({
  stress,
  funding,
  concentration,
  explanation,
}: {
  stress: StressData | null;
  funding: FundingStressMode | null;
  concentration: NewsUncertaintyConcentration | null;
  explanation?: ContextExplanation | null;
}) {
  const s = _stressRow(stress);
  const f = _fundingRow(funding);
  // Hide the whole card only when both stress and funding are absent; a
  // missing concentration block just omits its own row.
  if (!s && !f) return null;

  const concView = buildUncertaintyConcentrationView(concentration);
  const conc = concView.entries.length > 0 ? concView.entries[0]! : null;

  return (
    <div className="rounded-[4px] border border-[color:var(--so-rule)] bg-[var(--so-bg-1)] px-[18px] py-4">
      <div className="mb-2 font-mono text-[11px] font-medium uppercase tracking-[0.14em] text-[var(--so-ink-2)]">
        Uncertainty &amp; funding
      </div>
      <dl className="m-0 divide-y divide-[color:var(--so-rule)]">
        {s && <UncRow k="Stress" label={s.label} note={s.note} tone={s.tone} />}
        {f && <UncRow k="Funding" label={f.label} note={f.note} tone={f.tone} />}
        {conc && (
          <UncRow
            k="Concentration"
            label={conc.value}
            note={`${_titleCase(conc.key)} leads`}
            tone="watch"
          />
        )}
      </dl>
      <ContextExplanationDisclosure explanation={explanation} />
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

/** Compute display values for the track record strip.  Exported for tests. */
export function computeTrackRecordDisplay(data: TrackRecord) {
  const resolved = data.validated + data.contradicted;
  const hitRate = resolved > 0
    ? Math.round((data.validated / resolved) * 100)
    : null;
  const hitTone: "positive" | "neutral" | "warn" =
    hitRate === null ? "neutral" : hitRate >= 60 ? "positive" : hitRate >= 40 ? "neutral" : "warn";
  const avgSupport = data.avg_support_ratio !== null
    ? Math.round(data.avg_support_ratio * 100)
    : null;
  return { resolved, hitRate, hitTone, avgSupport };
}

function TrackRecordStrip({ data, isLoading }: { data?: TrackRecord; isLoading: boolean }) {
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

  const { hitRate, avgSupport } = computeTrackRecordDisplay(data);

  // Four hairline-gridded cells, design palette per the package:
  // validated (jade) / contradicted (rust) / unresolved (amber) / hit rate
  // (jade).  A quiet mono footer carries analyzed + avg support.
  const cells: Array<{ k: string; v: string | number; cls: string }> = [
    { k: "Validated", v: data.validated, cls: "text-[var(--so-jade-ink)]" },
    { k: "Contradicted", v: data.contradicted, cls: "text-[var(--so-rust-ink)]" },
    { k: "Unresolved", v: data.unresolved, cls: "text-[var(--so-amber)]" },
    { k: "Hit rate", v: hitRate == null ? "—" : `${hitRate}%`, cls: "text-[var(--so-jade-ink)]" },
  ];

  return (
    <section className="mb-5" data-testid="track-record">
      <div className="mb-2.5 font-mono text-[11px] font-medium uppercase tracking-[0.14em] text-[var(--so-ink-2)]">
        Saved-event outcomes
      </div>
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-[4px] bg-[color:var(--so-rule)] sm:grid-cols-4">
        {cells.map((c) => (
          <div key={c.k} className="bg-[var(--so-bg-1)] px-4 py-3.5">
            <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--so-ink-3)]">
              {c.k}
            </div>
            <div
              className={cn(
                "mt-2 font-[family-name:var(--so-display)] text-[30px] font-normal leading-none tracking-tight tabular-nums",
                c.cls,
              )}
            >
              {c.v}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-2.5 flex flex-wrap items-baseline gap-x-4 gap-y-1 font-mono text-[10px] uppercase tracking-[0.1em] text-[var(--so-ink-3)]">
        <span>{data.total} analyzed</span>
        {avgSupport !== null && <span>avg support {avgSupport}%</span>}
        {data.revisit_scored > 0 && <span>{data.revisit_scored} revisit-scored</span>}
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
// Main page
// ---------------------------------------------------------------------------

export function MarketOverview({ onAnalyze, failedHeadlines }: {
  onAnalyze?: (headline: string, opts?: { eventId?: number; context?: string }) => void;
  failedHeadlines?: Set<string>;
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

  // Persistent movers stays on its own endpoint — different selection algorithm
  // than today's highlights, so it cannot share /market-context.
  const { data: persistent, isLoading: persistentLoading, error: persistentError } = useQuery({
    queryKey: qk.moversPersistent(),
    queryFn: () => api.moversPersistent(),
    staleTime: 1_800_000,
  });

  const { data: weekly, isLoading: weeklyLoading, error: weeklyError } = useQuery({
    queryKey: qk.moversWeekly(),
    queryFn: () => api.moversWeekly(),
    staleTime: 1_800_000,
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
  const uncertaintyConcentration = ctx?.uncertainty_concentration ?? null;
  const contextExplanations = ctx?.context_explanations ?? {};
  const todaysHighlights = ctx?.highlights ?? [];

  // Surface a single inline error banner when any of the top-level queries
  // fail.  Without this, a backend that's unreachable on first start would
  // render the page completely blank (every section gracefully hides on
  // empty data) and the user would have no idea something went wrong.
  // Picks the first error so the banner is one line, not three.
  const firstError = ctxError ?? persistentError ?? weeklyError;
  const errorMessage = firstError instanceof Error ? firstError.message : null;

  // True cold-start empty: every archive-derived channel finished loading
  // and there is genuinely nothing to show.  Any populated surface — movers,
  // track record, or tracked evidence — suppresses the "No archive yet"
  // nudge; if a channel is still loading we treat it as "might have data" and
  // hide the nudge rather than risk a false cold-start message.
  const allLoaded =
    !ctxLoading && !persistentLoading && !weeklyLoading
    && !trackLoading && !trackedEvidenceLoading;
  const hasTrackRecord = !!trackRecord && trackRecord.total > 0;
  const hasTrackedEvidence =
    !!trackedEvidence
    && ((trackedEvidence.summary?.phase1_count ?? 0) > 0
      || (trackedEvidence.summary?.phase2_count ?? 0) > 0);
  const isColdStart =
    allLoaded
    && !firstError
    && (!persistent || persistent.length === 0)
    && (!weekly || weekly.length === 0)
    && todaysHighlights.length === 0
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

      {/* Liquid Benchmark Snapshots — a single hairline-gridded mono row.
          Hides cleanly when ``snapshots`` is null; the degraded banner
          already explains why. */}
      <BenchmarkSnapshotsStrip snapshots={snapshots} isLoading={ctxLoading} />

      {/* Regime read + Uncertainty & funding as one 2-up composition
          (1.25fr / 1fr) — two compact cards, each carrying its own "How to
          read this" disclosure.  Stacks on narrow viewports.  The compact
          UncertaintyCard reads real stress / funding / concentration data;
          it replaces the heavy full-width stress-strip on this page. */}
      <div className="mt-3.5 grid grid-cols-1 gap-3.5 lg:grid-cols-[1.25fr_1fr]">
        <RegimeVectorCard
          regimeVec={regimeVec}
          explanation={contextExplanations.regime_vector}
        />
        <UncertaintyCard
          stress={stress}
          funding={ctx?.funding_stress_mode ?? null}
          concentration={uncertaintyConcentration}
          explanation={contextExplanations.stress}
        />
      </div>

      {/* ────────────── 2 · EVENT ACTIVITY ────────────── */}
      <SectionHead kicker="Activity" n="2" title="Event activity" className="mt-14" />

      {/* Three stacked sub-windows: Today (4-up cards) → This week
          (2-up editorial cards) → Still moving (horizontal rows).
          Backend already gates persistent to high-impact conviction
          items, so empty there is correct, not a bug.  Operator
          scaffolding — registry candidates, candidate queue, backfill
          preview — has been removed from this surface per Slice 2;
          those concerns belong on an operator workbench page. */}
      <MoversChapter
        today={todaysHighlights}
        weekly={weekly}
        persistent={persistent}
        todayLoading={ctxLoading}
        weeklyLoading={weeklyLoading}
        persistentLoading={persistentLoading}
        onAnalyze={onAnalyze}
      />

      {/* ────────────── 3 · TRACK RECORD & EVIDENCE ────────────── */}
      <SectionHead kicker="Track record" n="3" title="Track record & evidence" className="mt-11" />

      {/* Saved-event outcomes — single track-record strip.  The
          earlier ``DiagnosticsTrackRecordStrip`` overlapped this
          surface; removed in Slice 2 so readers see one canonical
          source. */}
      <TrackRecordStrip data={trackRecord} isLoading={trackLoading} />

      {/* Tracked evidence layer — Phase 1 + Phase 2 evidence read
          straight from the tracked ``GET /evidence/summary`` route.
          The card renders Phase 1 and Phase 2 as separate columns and
          surfaces the envelope's ``fdr_scope_note`` verbatim so the
          FDR-scope disclaimer never drifts between the backend and
          the UI. */}
      <div className="pt-2">
        <TrackedEvidenceCard
          data={trackedEvidence}
          isLoading={trackedEvidenceLoading}
        />
      </div>

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
