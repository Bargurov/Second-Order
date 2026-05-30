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
} from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";
import { buildClusterContext } from "@/lib/cluster-context";
import { UncertaintySection } from "@/components/ui/stress-strip";
import { BenchmarkSnapshotsStrip } from "@/components/ui/benchmark-snapshots-strip";
import { TrackedEvidenceCard } from "@/components/ui/tracked-evidence-card";
import { deriveContextDegradedNotice } from "@/components/ui/degraded-data-notice";
import { DegradedBanner } from "@/components/ui/degraded-banner";
import { MetricCard } from "@/components/ui/metric-card";
import {
  MoversSectionHead,
  TodayMoverCard,
  WeeklyMoverCard,
  PersistentMoverRow,
} from "@/components/ui/mover-cards";

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
      {/* TODAY */}
      <div className="mb-8">
        <MoversSectionHead
          window="today"
          title="Today"
          sub="Last 24h · fastest signal, event-linked"
          count={todayList.length}
        />
        <p className="mb-3 text-[12px] leading-relaxed text-on-surface-variant/65">
          Event-linked moves; not validated until evidence broadens.
        </p>
        {todayLoading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {[1, 2, 3, 4].map((k) => (
              <Skeleton key={k} className="h-44 rounded-xl bg-surface-container-low" />
            ))}
          </div>
        ) : todayList.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {todayList.slice(0, 8).map((m) => (
              <TodayMoverCard key={m.event_id} mover={m} onAnalyze={onAnalyze} />
            ))}
          </div>
        ) : (
          <div className="rounded-md bg-white/[0.02] px-4 py-3">
            <span className="text-[12px] text-on-surface-variant/65">
              No event-linked moves in the last 24 hours.
            </span>
          </div>
        )}
      </div>

      {/* WEEKLY */}
      <div className="mb-8">
        <MoversSectionHead
          window="weekly"
          title="This week"
          sub="5-day curated review set · thesis-aligned"
          count={weeklyList.length}
        />
        {weeklyLoading ? (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {[1, 2].map((k) => (
              <Skeleton key={k} className="h-48 rounded-xl bg-surface-container-low" />
            ))}
          </div>
        ) : weeklyList.length > 0 ? (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {weeklyList.slice(0, 6).map((m) => (
              <WeeklyMoverCard key={m.event_id} mover={m} onAnalyze={onAnalyze} />
            ))}
          </div>
        ) : (
          <div className="rounded-md bg-white/[0.02] px-4 py-3">
            <span className="text-[12px] text-on-surface-variant/65">
              No 5-day confirmed movers yet.
            </span>
          </div>
        )}
      </div>

      {/* PERSISTENT — Still Moving Markets, gated to high-impact conviction
          by the backend.  Empty means no qualified rows; do not backfill
          with medium-impact or low-information filler. */}
      <div className="mb-4">
        <MoversSectionHead
          window="persistent"
          title="Still moving markets"
          sub="High-impact effects beyond the initial reaction window"
          count={persistentList.length}
        />
        {persistentLoading ? (
          <div className="flex flex-col gap-2">
            {[1, 2, 3].map((k) => (
              <Skeleton key={k} className="h-24 rounded-lg bg-surface-container-low" />
            ))}
          </div>
        ) : persistentList.length > 0 ? (
          <div className="flex flex-col gap-2">
            {persistentList.map((m) => (
              <PersistentMoverRow key={m.event_id} mover={m} onAnalyze={onAnalyze} />
            ))}
          </div>
        ) : (
          <div className="rounded-md bg-white/[0.02] px-4 py-3">
            <span className="text-[12px] text-on-surface-variant/65">
              No high-impact persistent movers qualify.
            </span>
          </div>
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
    <details className={cn("group rounded-md bg-white/[0.016] px-3 py-2 ring-1 ring-white/[0.035]", className)}>
      <summary className="flex cursor-pointer list-none items-center gap-2 marker:hidden">
        <ChevronDown className="h-3.5 w-3.5 text-on-surface-variant/45 transition-transform group-open:rotate-180" />
        <span className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-on-surface-variant/60">
          How to read this
        </span>
      </summary>
      <div className="mt-2 space-y-1.5 border-t border-white/[0.035] pt-2 text-[11px] leading-snug text-on-surface-variant/60">
        {meaning && (
          <p>
            <span className="font-medium text-on-surface-variant/75">Meaning: </span>
            {meaning}
          </p>
        )}
        {whatChangesIt && (
          <p>
            <span className="font-medium text-on-surface-variant/75">What changes it: </span>
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

const _AXIS_LABELS: Record<string, string> = {
  hot: "Inflation hot",
  cool: "Inflation cool",
  hawkish: "Policy hawkish",
  dovish: "Policy dovish",
  dollar_strong: "USD strong",
  dollar_weak: "USD weak",
  watch: "Growth watch",
  stressed: "Growth stressed",
  // Breadth-expansion axes (credit / curve_shape / inflation_path).
  // Names are full phrases so the chip strip at line ~574 reads
  // unambiguously when shown without the axis-name prefix.
  risk_on: "Credit risk-on",
  risk_off: "Credit risk-off",
  duration_stress: "Duration stress",
  front_loaded: "Curve front-loaded",
  term_premium: "Curve term-premium",
  parallel: "Curve parallel",
  hawkish_constraint: "Path hawkish-constraint",
  dovish_space: "Path dovish-space",
};

// ---------------------------------------------------------------------------
// Regime read — axis vocabulary + the compact RegimeVectorCard used in
// Section 1.  Older companion cards (CreditRegime / Highlights /
// SectorRotation / UncertaintyConcentration / MacroSystem /
// RegimeInterpretationSection) were removed in Slice 2; this card is the
// canonical surface now.
// ---------------------------------------------------------------------------

type RegimeAxis = {
  key: string;
  label: string;
  value: string;
  intensity: number;
};

type RegimeAxisKey =
  | "inflation"
  | "policy_stance"
  | "fx"
  | "growth_stress"
  | "credit"
  | "curve_shape"
  | "inflation_path";

function _axisLabel(axis: RegimeAxisKey): string {
  if (axis === "policy_stance") return "Policy";
  if (axis === "growth_stress") return "Growth";
  if (axis === "curve_shape") return "Curve";
  if (axis === "inflation_path") return "Path";
  if (axis === "fx") return "FX";
  return axis.charAt(0).toUpperCase() + axis.slice(1);
}

function _axisValue(value: string | undefined): string {
  if (!value || value === "unknown") return "Unknown";
  return _AXIS_LABELS[value] ?? value.replace(/_/g, " ");
}

function _axisIntensity(value: string | undefined): number {
  if (!value || value === "unknown" || value === "neutral") return 0.25;
  // Strong directional reads on each axis (incl. breadth-expansion).
  if (["hot", "hawkish", "dollar_strong", "stressed",
       "risk_off", "front_loaded", "hawkish_constraint"].includes(value)) return 0.78;
  // Softer or opposite-direction reads.
  if (["cool", "dovish", "dollar_weak", "watch",
       "risk_on", "term_premium", "dovish_space",
       "duration_stress"].includes(value)) return 0.58;
  // ``parallel`` and any other recognised-but-undirectional read.
  return 0.42;
}

function _regimeAxes(regimeVec: RegimeVector | null): RegimeAxis[] {
  // Mirrors the 7-axis order in regime_vector.REGIME_AXES so the dial
  // segments line up with how the backend talks about the regime.
  const axes: readonly RegimeAxisKey[] = [
    "inflation", "policy_stance", "fx", "growth_stress",
    "credit", "curve_shape", "inflation_path",
  ];
  return axes.map((axis) => {
    const value = regimeVec?.[axis] ?? "unknown";
    return {
      key: axis,
      label: _axisLabel(axis),
      value: _axisValue(value),
      intensity: _axisIntensity(value),
    };
  });
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
  if (!regimeVec?.available) {
    return (
      <div className="rounded-lg bg-surface-container-low px-5 py-4">
        <div className="mb-3.5 font-headline text-[12.5px] font-semibold uppercase tracking-[0.08em] text-on-surface-variant">
          Regime vector
        </div>
        <div className="rounded-md bg-white/[0.02] px-4 py-6 text-center">
          <p className="font-headline text-[15px] font-semibold text-on-surface/80">
            Unavailable
          </p>
          <p className="mt-1 text-[12px] leading-relaxed text-on-surface-variant/65">
            Regime vector data is unavailable for this market snapshot.
          </p>
        </div>
      </div>
    );
  }

  const axes = _regimeAxes(regimeVec);
  const compoundLabel = regimeVec.compound?.label ?? "";
  // ``label === "none"`` means the compound classifier did not lock a
  // regime — confidence is N/A, not zero.  Showing "0%" here misreads
  // as low-quality data; show "—" with an "unlocked" sublabel so the
  // dial is unambiguous.  The perimeter arcs are also forced to the
  // neutral fallback in that branch — without it, the colored ring
  // reads as a locked-regime signal even though the center says
  // "Unlocked".  Axis values stay visible in the dl on the right.
  const isLocked = !!compoundLabel && compoundLabel !== "none";
  const confidence = regimeVec.compound?.confidence;
  const confPct = isLocked && typeof confidence === "number"
    ? Math.round(confidence * 100)
    : null;
  // Backend always supplies a rationale — for locked regimes it's the
  // rule's prose ("Hot inflation + tight Fed with growth cracking");
  // for the unlocked branch it's the reason the classifier didn't lock
  // ("Best candidate `reflation` below 0.60 confidence floor" or
  // "No compound regime rule matched the vector").  Backticks come
  // straight from regime_compound.py and would render literally — strip
  // them.  The "no rule matched" string is replaced with plain-English
  // copy that doesn't read like a bug report.
  const rawRationale = (regimeVec.compound?.rationale ?? "")
    .replace(/`/g, "")
    .trim();
  // For the unlocked branch, keep the state muted while describing it
  // as a mixed/shifting market read instead of a missing-data failure.
  const compoundRationale = !isLocked
    ? "Signals are mixed/shifting; no combined regime rule matched."
    : rawRationale;

  return (
    <div className="rounded-lg bg-surface-container-low px-5 py-4">
      <div className="mb-3.5 font-headline text-[12.5px] font-semibold uppercase tracking-[0.08em] text-on-surface-variant">
        Regime vector
      </div>
      <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
        <div className="relative h-[124px] w-[124px] shrink-0">
          <svg viewBox="0 0 120 120" width="124" height="124" aria-hidden>
            <circle cx="60" cy="60" r="46" fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth="10" />
            {axes.map((axis, i) => {
              const seg = 360 / axes.length;
              const start = i * seg - 90 + 4;
              const end = (i + 1) * seg - 90 - 4;
              const rad = Math.PI / 180;
              const r = 46;
              const x1 = 60 + r * Math.cos(start * rad);
              const y1 = 60 + r * Math.sin(start * rad);
              const x2 = 60 + r * Math.cos(end * rad);
              const y2 = 60 + r * Math.sin(end * rad);
              const color = !isLocked
                ? "rgba(255,255,255,0.22)"
                : axis.intensity > 0.65
                  ? "rgb(147 209 211)"
                  : axis.intensity > 0.45
                    ? "rgba(147,209,211,0.58)"
                    : "rgba(255,255,255,0.22)";
              return (
                <path
                  key={axis.key}
                  d={`M ${x1} ${y1} A ${r} ${r} 0 0 1 ${x2} ${y2}`}
                  stroke={color}
                  strokeWidth="10"
                  fill="none"
                />
              );
            })}
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
            <div className="text-[11px] uppercase tracking-[0.12em] text-on-surface-variant/60">
              {isLocked ? "Confidence" : "Regime"}
            </div>
            <div className={cn(
              "font-headline tabular-nums text-on-surface",
              isLocked ? "text-[18px] font-bold" : "max-w-[86px] text-[11.5px] font-semibold leading-tight",
            )}>
              {isLocked
                ? (confPct == null ? "—" : `${confPct}%`)
                : "No dominant regime pattern"}
            </div>
          </div>
        </div>
        <div className="min-w-0 flex-1">
          <dl className="grid grid-cols-[auto_1fr] gap-x-5 gap-y-1.5">
            {axes.map((axis) => (
              <div key={axis.key} className="contents">
                <dt className="text-[11.5px] text-on-surface-variant/60">{axis.label}</dt>
                <dd className="m-0 font-mono text-[12px] text-on-surface/85">{axis.value}</dd>
              </div>
            ))}
          </dl>
          <div className="mt-4 border-t border-outline-variant/15 pt-3 text-[12px] leading-relaxed text-on-surface-variant/75">
            {isLocked ? (
              <>Compound: <span className="font-medium text-on-surface">{compoundLabel.replace(/_/g, " ")}</span></>
            ) : (
              <span className="font-medium text-on-surface">No dominant regime pattern</span>
            )}
            {compoundRationale && (
              <div className="mt-1 text-[11.5px] text-on-surface-variant/55">
                {compoundRationale}
              </div>
            )}
            <ContextExplanationDisclosure explanation={explanation} className="mt-3 bg-white/[0.012]" />
          </div>
        </div>
      </div>
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
      <section className="mb-8">
        <Skeleton className="h-20 rounded-xl bg-surface-container-highest" />
      </section>
    );
  }
  if (!data || data.total === 0) return null;

  const { hitRate, hitTone, avgSupport } = computeTrackRecordDisplay(data);

  const hitColor = hitTone === "positive"
    ? "text-primary" : hitTone === "warn" ? "text-error-dim" : "text-on-surface-variant";
  const hitDot = hitTone === "positive"
    ? "bg-primary" : hitTone === "warn" ? "bg-error-dim" : "bg-on-surface-variant/40";

  return (
    <section className="mt-10 mb-8" data-testid="track-record">
      <div className="bg-surface-container-low rounded-lg px-5 py-3 md:px-6">

        {/* Row 1: compact inline metrics — hit rate same weight as peers */}
        <div className="flex items-center gap-5">

          {/* Lead stat: hit rate (or total if no resolved yet) */}
          {hitRate !== null ? (
            <div className="flex items-baseline gap-1.5 shrink-0">
              <span className={cn("w-1.5 h-1.5 rounded-full self-center shrink-0", hitDot)} />
              <span className={cn("text-[18px] font-headline font-extrabold tabular-nums leading-none tracking-tight", hitColor)}>
                {hitRate}%
              </span>
              <span className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-on-surface-variant/55 self-center">
                Hit Rate
              </span>
            </div>
          ) : (
            <div className="flex items-baseline gap-1.5 shrink-0">
              <span className="text-[18px] font-headline font-extrabold tabular-nums leading-none tracking-tight text-on-surface">
                {data.total}
              </span>
              <span className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-on-surface-variant/55 self-center">
                Analyzed
              </span>
            </div>
          )}

          {/* Thin divider */}
          <div className="w-px h-9 bg-outline-variant/15 shrink-0" />

          {/* Secondary breakdown — compact inline metrics */}
          <div className="flex items-center gap-3 md:gap-4 overflow-x-auto min-w-0">
            <MetricCard label="Analyzed" value={data.total} />
            <MetricCard label="Validated" value={data.validated} accent="text-primary" />
            <MetricCard label="Contradicted" value={data.contradicted} accent="text-error-dim" />
            <MetricCard label="Unresolved" value={data.unresolved} accent="text-on-surface-variant/40" />
            {avgSupport !== null && (
              <MetricCard label="Avg Support" value={`${avgSupport}%`} />
            )}
          </div>

          {/* Revisit badge — far right */}
          {data.revisit_scored > 0 && (
            <span className="ml-auto shrink-0 text-[10px] font-semibold text-primary/55 uppercase tracking-[0.1em] hidden md:block">
              {data.revisit_scored} revisit-scored
            </span>
          )}
        </div>
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
  ok:      "bg-primary/15 text-primary",
  warn:    "bg-error-dim/15 text-error-dim",
  error:   "bg-error-dim/20 text-error-dim",
  neutral: "bg-surface-container-highest text-on-surface-variant/50",
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
      <section className="mb-8">
        <Skeleton className="h-5 w-40 bg-surface-container-highest mb-4" />
        <div className="space-y-2">
          {[1, 2, 3].map((k) => <Skeleton key={k} className="h-10 rounded-lg bg-surface-container-highest" />)}
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

  return (
    <section className="mb-8">
      <div className="flex items-center gap-2 mb-3">
        <h2 className="text-[10.5px] font-semibold uppercase tracking-[0.14em] text-on-surface-variant/65">
          Latest Headlines
        </h2>
        <span className={cn(
          "inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.1em] leading-none",
          _FRESHNESS_TONE_CLASS[freshness.tone],
        )}>
          <span className={cn(
            "h-1 w-1 rounded-full",
            freshness.tone === "ok" && "bg-primary",
            freshness.tone === "warn" && "bg-error-dim",
            freshness.tone === "error" && "bg-error-dim",
            freshness.tone === "neutral" && "bg-on-surface-variant/30",
          )} />
          {freshness.label}
        </span>
      </div>
      <div className="space-y-1.5">
        {top.map((c, i) => {
          const isFailed = failedHeadlines?.has(c.headline);
          return (
            <div
              key={i}
              className={cn(
                "group flex items-center gap-3 rounded-lg bg-surface-container-low px-3 py-2 transition-shadow",
                isFailed
                  ? "ring-1 ring-error-dim/25 hover:ring-error-dim/40"
                  : "hover:bg-surface-container-high",
              )}
            >
              <span className={cn(
                "flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold tabular-nums",
                c.source_count >= 3 ? "bg-primary/15 text-primary" : "bg-surface-container-highest text-on-surface-variant/50",
              )}>
                {c.source_count}
              </span>
              <span className="min-w-0 flex-1 text-[12px] font-medium leading-snug text-on-surface line-clamp-1">
                {c.headline}
              </span>
              {isFailed && (
                <span className="shrink-0 flex items-center gap-1 text-[10px] font-semibold text-error-dim/70">
                  <AlertTriangle className="h-2.5 w-2.5" />
                </span>
              )}
              {onAnalyze && (
                <button
                  onClick={() => onAnalyze(c.headline, { context: buildClusterContext(c) })}
                  className={cn(
                    "shrink-0 flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-[0.1em] transition-all",
                    isFailed
                      ? "text-on-surface-variant/50 hover:text-primary hover:bg-primary/10"
                      : "text-on-surface-variant/40 hover:text-primary hover:bg-primary/10 opacity-0 group-hover:opacity-100",
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

function _providerIssueItems(ctx: import("@/lib/api").MarketContext | null | undefined): string[] {
  if (!ctx?.snapshots) return [];
  return ctx.snapshots
    .filter((s) => s.error || s.value == null || s.stale)
    .slice(0, 8)
    .map((s) => {
      const reason = s.error
        ? s.error.replace(/_/g, " ")
        : s.stale
          ? "stale"
          : "missing";
      return `${s.market}: ${reason}`;
    });
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

  // ``providerIssueItems`` feeds the degraded-context banner so a
  // reader sees which provider is misbehaving in plain English.  The
  // deeper engine blocks (finance_playbook, credit_regime,
  // sector_rotation) were rendered by the Section B / Section D
  // surfaces that Slice 2 retired; they are still produced by the
  // /market-context enrichment, just no longer surfaced on this page.
  const providerIssueItems = _providerIssueItems(ctx);

  // Surface a single inline error banner when any of the top-level queries
  // fail.  Without this, a backend that's unreachable on first start would
  // render the page completely blank (every section gracefully hides on
  // empty data) and the user would have no idea something went wrong.
  // Picks the first error so the banner is one line, not three.
  const firstError = ctxError ?? persistentError ?? weeklyError;
  const errorMessage = firstError instanceof Error ? firstError.message : null;

  // True cold-start empty: data loaded successfully on every channel but
  // the archive is empty.  Show a friendly first-run nudge instead of a
  // blank page.  Stress / snapshots can still be empty on a fresh clone,
  // so we gate purely on "all queries finished + no movers anywhere".
  const allLoaded = !ctxLoading && !persistentLoading && !weeklyLoading;
  const isColdStart =
    allLoaded
    && !firstError
    && (!persistent || persistent.length === 0)
    && (!weekly || weekly.length === 0)
    && todaysHighlights.length === 0;

  return (
    // Page-level flow: no nested overflow container, no h-full reliance.
    // The shell scrolls the whole document; this page just stacks its
    // sections.  TodayStrip used to be `position: absolute` inside a
    // fixed-height wrapper — that pattern is gone, the strip is now an
    // inline footer at the natural end of the overview content.
    <div className="space-y-0">
      {/* Inline error banner — only renders when one of the top-level
          queries failed.  Keeps the rest of the page rendering its own
          empty states so partial degradation still works. */}
      {errorMessage && (
        <div
          role="alert"
          className="mb-6 bg-error-container/15 rounded-lg p-4 flex items-start gap-3 ring-1 ring-error-dim/25"
        >
          <AlertTriangle className="h-4 w-4 text-error-dim shrink-0 mt-0.5" />
          <div className="min-w-0">
            <p className="text-[11px] font-bold text-error-dim">Market data unavailable</p>
            <p className="text-[10px] text-on-surface-variant mt-0.5 break-words">{errorMessage}</p>
          </div>
        </div>
      )}

      {/* Cold-start empty state — only when every channel loaded cleanly
          but there is genuinely nothing to show.  A first-run user sees
          a clear nudge instead of a stack of "no X detected" boxes. */}
      {isColdStart && (
        <div className="mb-6 bg-surface-container-low rounded-lg p-6 text-center">
          <p className="text-sm font-headline font-bold text-on-surface/80 mb-1">
            No archive yet
          </p>
          <p className="text-[11px] text-on-surface-variant/70 max-w-md mx-auto leading-relaxed">
            Run an analysis from the Headlines page to start populating Market Overview.
          </p>
        </div>
      )}

      {/* Degraded-context banner — fires when snapshots are stale or provider is down */}
      {ctx && (() => {
        const n = deriveContextDegradedNotice(ctx);
        return n ? (
          <DegradedBanner
            title={n.label}
            detail={n.detail ?? undefined}
            items={providerIssueItems}
            severity={n.severity}
            className="mb-4"
          />
        ) : null;
      })()}

      {/*
        Three-section composition, matched to the viewer's three
        questions: what is the tape doing, which named events are
        moving things, and what is the system's record.  Every section
        degrades gracefully — when a sub-query returns empty or null,
        the affected card renders an empty-state line or hides
        entirely so a cold or partial clone still reads as intentional.
      */}

      {/* ────────────── 1 · MARKET BACKDROP ────────────── */}
      <div className="flex items-baseline justify-between mb-3 mt-2">
        <p className="section-kicker">Snapshot</p>
        <span className="text-[11px] text-on-surface-variant/55">
          1 · Market backdrop
        </span>
      </div>

      {/* Liquid Benchmark Snapshots — equities / rates / FX /
          commodities read at a glance.  Hides cleanly when ``snapshots``
          is null; the degraded banner already explains why. */}
      <BenchmarkSnapshotsStrip snapshots={snapshots} isLoading={ctxLoading} />
      <ContextExplanationDisclosure
        explanation={contextExplanations.snapshots}
        className="-mt-6 mb-6"
      />

      {/* Regime read · Uncertainty & funding — two compact cards
          side by side on wide viewports.  Regime read uses the
          existing ``RegimeVectorCard`` (dial + axes); Uncertainty &
          funding uses the existing ``UncertaintySection`` which
          already composes stress + funding-stress-mode + the
          uncertainty-concentration breadth caveat.  When either side
          has nothing to render its column collapses to its own
          inline empty state — neither hides the other. */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-8">
        <RegimeVectorCard
          regimeVec={regimeVec}
          explanation={contextExplanations.regime_vector}
        />
        <UncertaintySection
          stress={stress}
          isLoading={ctxLoading}
          uncertaintyConcentration={uncertaintyConcentration}
          fundingStressMode={ctx?.funding_stress_mode ?? null}
        />
      </div>
      <ContextExplanationDisclosure
        explanation={contextExplanations.stress}
        className="-mt-4 mb-6"
      />

      {/* ────────────── 2 · EVENT ACTIVITY ────────────── */}
      <div className="flex items-baseline justify-between mb-3 mt-2">
        <p className="section-kicker">Activity</p>
        <span className="text-[11px] text-on-surface-variant/55">
          2 · Event activity
        </span>
      </div>

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
      <div className="flex items-baseline justify-between mb-3 mt-8">
        <p className="section-kicker">Track record</p>
        <span className="text-[11px] text-on-surface-variant/55">
          3 · Track record &amp; evidence
        </span>
      </div>

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
      <div className="pt-4">
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
