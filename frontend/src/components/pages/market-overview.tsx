import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { AlertTriangle, FlaskConical, Scale, ChevronDown } from "lucide-react";
import { api, type BackfillCandidateResponse, type BackfillPreviewResponse, type ContextExplanation, type MarketMover, type TrackRecord, type NewsCluster, type RegimeVector, type RefreshMeta, type PlaybookEntry, type PolicyItem, type FinancePlaybook, type FundingStressMode, type NewsUncertaintyConcentration, type ReactionProfileStats, type RegistryCandidateQueueResponse, type RegistryDiagnostics, type SectorRotation, type ValidationStatusStats } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";
import { buildClusterContext } from "@/lib/cluster-context";
import { UncertaintySection } from "@/components/ui/stress-strip";
import { SystemHealthPanel } from "@/components/ui/system-health-panel";
import { BenchmarkSnapshotsStrip } from "@/components/ui/benchmark-snapshots-strip";
import { deriveContextDegradedNotice } from "@/components/ui/degraded-data-notice";
import { DegradedBanner } from "@/components/ui/degraded-banner";
import { MetricCard } from "@/components/ui/metric-card";
import {
  MoversChapterHead,
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
  registryDiagnostics,
  candidateQueue,
  backfillPreview,
  todayLoading,
  weeklyLoading,
  persistentLoading,
  onAnalyze,
}: {
  today: MarketMover[] | undefined;
  weekly: MarketMover[] | undefined;
  persistent: MarketMover[] | undefined;
  registryDiagnostics?: RegistryDiagnostics;
  candidateQueue?: RegistryCandidateQueueResponse;
  backfillPreview?: BackfillPreviewResponse;
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
      <MoversChapterHead />
      <RegistryCandidatesNotice diagnostics={registryDiagnostics} />
      <CandidateQueuePanel queue={candidateQueue} />
      <BackfillPreviewNotice preview={backfillPreview} />

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

type BackfillPreviewCandidate = BackfillPreviewResponse["items"][number];

function _previewReasonLabel(reason?: string | null): string {
  if (!reason) return "Ready for review";
  const labels: Record<string, string> = {
    already_market_checked: "Already checked against market data",
    already_analyzed: "Already analyzed",
    low_signal: "Thin market evidence",
    llm_budget_exhausted: "Outside this preview budget",
    llm_unavailable: "Analysis provider unavailable",
    no_api_key: "Analysis provider unavailable",
    no_headline: "Missing headline",
    outside_recency_window: "Outside the recent-news window",
    not_market_relevant: "Not market-linked enough",
    irrelevant: "Not market-linked enough",
  };
  return labels[reason] ?? reason.replace(/_/g, " ");
}

function _candidateReason(candidate: BackfillPreviewCandidate): string {
  return candidate.skip_reason_label || _previewReasonLabel(candidate.skip_reason);
}

function _previewDecisionLabel(candidate: BackfillPreviewCandidate): string {
  if (candidate.already_analyzed) return "Already in archive";
  if (candidate.would_call_llm) return "Ready for analysis";
  if (candidate.skip_reason) return "Not selected";
  return "Review candidate";
}

function CandidateQueuePanel({ queue }: { queue?: RegistryCandidateQueueResponse }) {
  if (!queue) return null;

  const items = (queue.items ?? [])
    .filter((candidate) => candidate.headline?.trim())
    .slice(0, 5);
  const counts = queue.counts ?? {};
  const source = queue.news_source ? `Source: ${queue.news_source}` : "Zero-cost registry queue";

  return (
    <details className="group mb-5 -mt-3 rounded-md bg-white/[0.016] px-3.5 py-2.5 ring-1 ring-white/[0.035]">
      <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2 marker:hidden">
        <ChevronDown className="h-3.5 w-3.5 text-on-surface-variant/45 transition-transform group-open:rotate-180" />
        <span className="text-[11px] font-semibold text-on-surface-variant/75">
          Candidate Queue
        </span>
        <span className="rounded-full bg-white/[0.045] px-2 py-0.5 text-[10.5px] font-medium text-on-surface-variant/60">
          Zero-cost scan
        </span>
        <span className="ml-auto text-[11px] tabular-nums text-on-surface-variant/45">
          {counts.eligible ?? 0} eligible
        </span>
      </summary>

      <div className="mt-2.5 border-t border-white/[0.035] pt-2.5">
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10.5px] font-medium text-primary/75">
            Eligible {counts.eligible ?? 0}
          </span>
          <span className="rounded-full bg-white/[0.035] px-2 py-0.5 text-[10.5px] font-medium text-on-surface-variant/50">
            Skipped {counts.skipped ?? 0}
          </span>
          <span className="rounded-full bg-white/[0.035] px-2 py-0.5 text-[10.5px] font-medium text-on-surface-variant/50">
            Already analyzed {counts.already_analyzed ?? 0}
          </span>
          <span className="rounded-full bg-white/[0.035] px-2 py-0.5 text-[10.5px] font-medium text-on-surface-variant/50">
            Expired low-impact {counts.expired_low_impact ?? 0}
          </span>
          <span className="ml-auto text-[10.5px] text-on-surface-variant/40">
            {source}
          </span>
        </div>

        {items.length > 0 ? (
          <ul className="space-y-1.5">
            {items.map((candidate) => (
              <li
                key={`${candidate.headline}-${candidate.published_at ?? ""}`}
                className="flex flex-wrap items-center gap-1.5 text-[11px] leading-snug text-on-surface-variant/60"
              >
                <span className="min-w-0 flex-1 truncate">{candidate.headline}</span>
                {candidate.source_count != null ? (
                  <span className="shrink-0 rounded-full bg-white/[0.03] px-2 py-0.5 text-[10.5px] tabular-nums text-on-surface-variant/45">
                    {candidate.source_count} src
                  </span>
                ) : null}
                <span className="shrink-0 rounded-full bg-white/[0.03] px-2 py-0.5 text-[10.5px] font-medium text-on-surface-variant/50">
                  {candidate.skip_reason_label || "Eligible for analysis"}
                </span>
                {candidate.registry_state ? (
                  <span className="shrink-0 rounded-full bg-white/[0.025] px-2 py-0.5 text-[10.5px] text-on-surface-variant/38">
                    {candidate.registry_state.replace(/_/g, " ")}
                  </span>
                ) : null}
                {candidate.rank_explanation ? (
                  <span className="basis-full pl-0 text-[10.5px] leading-snug text-on-surface-variant/45 sm:pl-1">
                    {candidate.rank_explanation}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[11px] text-on-surface-variant/55">
            No candidate headlines in the current queue.
          </p>
        )}
      </div>
    </details>
  );
}

function _candidateKey(candidate: BackfillPreviewCandidate): string {
  return `${candidate.headline}-${candidate.published_at ?? ""}`;
}

function _candidateResultText(result: BackfillCandidateResponse): string {
  const status = result.analyzed
    ? "Analyzed"
    : result.status === "skipped"
      ? "Skipped"
      : result.status === "degraded"
        ? "Degraded"
        : result.status || "Completed";
  const reason = result.reason ? ` · ${_previewReasonLabel(result.reason)}` : "";
  const calls = ` · ${result.llm_calls} API call${result.llm_calls === 1 ? "" : "s"}`;
  const event = result.event_id != null ? ` · event #${result.event_id}` : "";
  return `${status}${reason}${calls}${event}`;
}

function _candidateResultTone(result: BackfillCandidateResponse): string {
  if (result.analyzed) return "text-primary/80";
  if (result.status === "skipped") return "text-on-surface-variant/55";
  if (result.status === "degraded") return "text-error-dim/80";
  return "text-on-surface-variant/65";
}

function BackfillPreviewNotice({ preview }: { preview?: BackfillPreviewResponse }) {
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, BackfillCandidateResponse>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});

  if (!preview) return null;

  const candidates = (preview.items ?? [])
    .filter((candidate) => candidate.headline?.trim())
    .slice(0, 3);
  const wouldCall = preview.counts?.would_call_llm ?? candidates.filter((candidate) => candidate.would_call_llm).length;
  const sinceHours = preview.filters?.since_hours ?? 72;
  const forceReanalyze = preview.filters?.force_reanalyze ?? false;
  const includeLowSignal = preview.filters?.include_low_signal ?? false;

  const analyzeCandidate = async (candidate: BackfillPreviewCandidate) => {
    const key = _candidateKey(candidate);
    const confirmed = window.confirm(
      "Analyze this one candidate now? This can spend one Claude/API call. The zero-cost preview itself will remain read-only.",
    );
    if (!confirmed) return;

    setPendingKey(key);
    setErrors((prev) => ({ ...prev, [key]: "" }));
    try {
      const result = await api.backfillCandidate({
        headline: candidate.headline,
        sinceHours,
        forceReanalyze,
        includeLowSignal,
      });
      setResults((prev) => ({ ...prev, [key]: result }));
    } catch (err) {
      setErrors((prev) => ({
        ...prev,
        [key]: err instanceof Error ? err.message : "Candidate analysis failed.",
      }));
    } finally {
      setPendingKey((current) => (current === key ? null : current));
    }
  };

  return (
    <details className="group mb-5 -mt-3 rounded-md bg-white/[0.016] px-3.5 py-2.5 ring-1 ring-white/[0.035]">
      <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2 marker:hidden">
        <ChevronDown className="h-3.5 w-3.5 text-on-surface-variant/45 transition-transform group-open:rotate-180" />
        <span className="text-[11px] font-semibold text-on-surface-variant/75">
          Preview candidates
        </span>
        <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10.5px] font-medium text-primary/80">
          Preview only — no Claude/API spend
        </span>
        <span className="ml-auto text-[11px] tabular-nums text-on-surface-variant/45">
          {wouldCall} ready for analysis
        </span>
      </summary>

      {candidates.length > 0 ? (
        <div className="mt-2.5 border-t border-white/[0.035] pt-2.5">
          <p className="mb-2 text-[11px] leading-snug text-on-surface-variant/55">
            Headlines found by the zero-cost scan. They are not analyzed or validated until evidence broadens.
            Manual analysis is separate and asks before spending one Claude/API call for one headline.
          </p>
          <ul className="space-y-1.5">
            {candidates.map((candidate) => {
              const key = _candidateKey(candidate);
              const result = results[key];
              const error = errors[key];
              const isPending = pendingKey === key;
              const isBusy = pendingKey !== null;

              return (
                <li
                  key={key}
                  className="flex flex-wrap items-center gap-1.5 text-[11px] leading-snug text-on-surface-variant/60"
                >
                  <span className="min-w-0 flex-1 truncate">{candidate.headline}</span>
                  <span className={cn(
                    "shrink-0 rounded-full px-2 py-0.5 text-[10.5px] font-medium",
                    candidate.would_call_llm
                      ? "bg-primary/10 text-primary/80"
                      : "bg-white/[0.04] text-on-surface-variant/55",
                  )}>
                    {_previewDecisionLabel(candidate)}
                  </span>
                  <span className="shrink-0 rounded-full bg-white/[0.03] px-2 py-0.5 text-[10.5px] font-medium text-on-surface-variant/45">
                    {_candidateReason(candidate)}
                  </span>
                  <button
                    type="button"
                    disabled={isBusy}
                    onClick={() => void analyzeCandidate(candidate)}
                    className={cn(
                      "shrink-0 rounded-full border border-primary/20 px-2 py-0.5 text-[10.5px] font-semibold text-primary/80 transition-colors hover:bg-primary/10",
                      isBusy && "cursor-not-allowed opacity-45 hover:bg-transparent",
                    )}
                  >
                    {isPending ? "Analyzing..." : "Analyze candidate"}
                  </button>
                  {candidate.rank_explanation ? (
                    <span className="basis-full pl-0 text-[10.5px] leading-snug text-on-surface-variant/45 sm:pl-1">
                      {candidate.rank_explanation}
                    </span>
                  ) : null}
                  {result ? (
                    <span className={cn("basis-full pl-0 text-[10.5px] leading-snug sm:pl-1", _candidateResultTone(result))}>
                      {_candidateResultText(result)}
                    </span>
                  ) : null}
                  {error ? (
                    <span className="basis-full pl-0 text-[10.5px] leading-snug text-error-dim/80 sm:pl-1">
                      {error}
                    </span>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </div>
      ) : (
        <p className="mt-2 border-t border-white/[0.035] pt-2.5 text-[11px] text-on-surface-variant/55">
          No candidate headlines in the current zero-cost scan.
        </p>
      )}
    </details>
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

function RegistryCandidatesNotice({ diagnostics }: { diagnostics?: RegistryDiagnostics }) {
  if (!diagnostics) return null;

  const candidates = diagnostics.eligible_unanalyzed_candidates ?? [];
  const topCandidates = candidates
    .filter((candidate) => candidate.headline?.trim())
    .slice(0, 3);

  return (
    <div className="mb-5 -mt-2 rounded-md bg-white/[0.018] px-3.5 py-2.5 ring-1 ring-white/[0.04]">
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center rounded-full bg-white/[0.045] px-2.5 py-1 text-[11px] font-semibold text-on-surface-variant/75">
          Unanalyzed candidates: {candidates.length}
        </span>
        <span className="text-[11px] leading-relaxed text-on-surface-variant/55">
          Zero-cost registry scan. These titles have not run analysis yet.
        </span>
      </div>

      {topCandidates.length > 0 && (
        <div className="mt-2 border-t border-white/[0.035] pt-2">
          <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-on-surface-variant/40">
            Top waiting titles
          </div>
          <ul className="space-y-1.5">
            {topCandidates.map((candidate) => (
              <li
                key={`${candidate.cluster_id ?? candidate.headline}-${candidate.first_seen_at ?? ""}`}
                className="flex items-baseline gap-2 text-[11px] leading-snug text-on-surface-variant/60"
              >
                <span className="min-w-0 flex-1 truncate">{candidate.headline}</span>
                {candidate.source_count != null && (
                  <span className="shrink-0 tabular-nums text-on-surface-variant/40">
                    {candidate.source_count} src
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
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

export function TrendingThemesPanel({
  clusters,
  regimeVec,
  isLoading,
}: {
  clusters: NewsCluster[];
  regimeVec: RegimeVector | null;
  isLoading: boolean;
}) {
  if (isLoading) return null;
  const themes = deriveThemes(clusters, regimeVec);
  if (themes.length === 0) return null;

  return (
    <section className="mb-6">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-on-surface-variant/55 mr-1">
          Trending Themes
        </span>
        {themes.map((t) => (
          <span
            key={`${t.category}:${t.label}`}
            className={cn(
              "inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-[0.1em]",
              t.regimeAligned
                ? "bg-primary/15 text-primary"
                : "bg-surface-container-highest text-on-surface-variant/60",
            )}
          >
            {t.label}
          </span>
        ))}
      </div>
    </section>
  );
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

function _axisChipClass(axis: string, value: string): string {
  if (axis === "inflation" && value === "hot") return "text-error-dim bg-error-dim/10";
  if (axis === "inflation" && value === "cool") return "text-primary bg-primary/10";
  if (axis === "policy_stance" && value === "hawkish") return "text-error-dim bg-error-dim/10";
  if (axis === "policy_stance" && value === "dovish") return "text-primary bg-primary/10";
  if (axis === "growth_stress" && value === "stressed") return "text-error-dim bg-error-dim/10";
  if (axis === "growth_stress" && value === "watch") return "text-[#facc15] bg-[#facc15]/10";
  return "text-on-surface-variant/60 bg-surface-container-highest";
}

// ---------------------------------------------------------------------------
// Macro System Panel — compact synthesis over regime / funding / rotation
// ---------------------------------------------------------------------------
//
// Surfaces the deeper finance engine (compound regime + transition,
// funding-liquidity mode, sector-rotation read, finance-playbook
// headline) in one institutional block.  Gracefully hides when no
// engine inputs are available.  Design constraints from DESIGN.md:
// section surface #13131a, raised chips #242533, accent teal, coral
// for stress, tabular numeric, 8px max radius, no yellow flood.

function _severityTone(severity?: string): string {
  switch (severity) {
    case "acute":    return "text-error-dim bg-error-dim/15 border-error-dim/30";
    case "elevated": return "text-error-dim/90 bg-error-dim/10 border-error-dim/20";
    case "mild":     return "text-[#93d1d3] bg-[#93d1d3]/10 border-[#93d1d3]/25";
    default:         return "text-on-surface-variant/70 bg-surface-container-highest border-white/5";
  }
}

function _tiltTone(tilt?: string): string {
  if (tilt === "risk_off") return "text-error-dim bg-error-dim/10 border-error-dim/25";
  if (tilt === "risk_on")  return "text-[#93d1d3] bg-[#93d1d3]/10 border-[#93d1d3]/25";
  if (tilt === "mixed")    return "text-on-surface-variant/80 bg-surface-container-highest border-white/10";
  return "text-on-surface-variant/60 bg-surface-container-highest border-white/5";
}

function _transitionTone(state?: string): string {
  if (state === "flipping") return "text-error-dim";
  if (state === "shifting") return "text-[#93d1d3]";
  if (state === "stable")   return "text-on-surface-variant/70";
  return "text-on-surface-variant/40";
}

export function MacroSystemPanel({
  playbook,
  funding,
  rotation,
  regimeVec,
  isLoading,
}: {
  playbook: FinancePlaybook | null;
  funding: FundingStressMode | null;
  rotation: SectorRotation | null;
  regimeVec: (RegimeVector & {
    compound?: { label: string; confidence: number; rationale: string };
    transition?: { state: string; rationale: string };
  }) | null;
  isLoading: boolean;
}) {
  if (isLoading) {
    return (
      <section className="mb-6">
        <Skeleton className="h-32 rounded-lg bg-surface-container-highest" />
      </section>
    );
  }

  // Hide the panel entirely when we have NOTHING to render.  A page with
  // only the legacy strips is still more honest than a half-empty
  // institutional card.
  const hasPlaybook = playbook?.available && playbook.headline;
  const hasFunding  = funding?.available  && (funding.composite_severity ?? "none") !== "none";
  const hasRotation = rotation?.available && rotation.sectors?.length;
  const hasCompound = regimeVec?.compound && regimeVec.compound.label && regimeVec.compound.label !== "none";
  if (!hasPlaybook && !hasFunding && !hasRotation && !hasCompound) return null;

  const compound = regimeVec?.compound;
  const transition = regimeVec?.transition;
  const topWinners = rotation?.winners?.direct?.slice(0, 3) ?? [];
  const topLosers  = rotation?.losers?.direct?.slice(0, 3) ?? [];

  return (
    <section className="mb-8">
      <div className="flex items-center gap-2 mb-3">
        <h2 className="text-xs font-headline font-bold uppercase tracking-[0.18em] text-on-surface-variant/70">
          Macro System
        </h2>
        {playbook?.sources_used && playbook.sources_used.length > 0 && (
          <span className="text-[10px] font-num tabular-nums text-on-surface-variant/55 uppercase tracking-[0.1em]">
            · {playbook.sources_used.length} source(s)
          </span>
        )}
      </div>

      <div className="bg-[#13131a] rounded-lg p-5">
        {/* Playbook headline — the one-line synthesis the desk quotes */}
        {hasPlaybook && (
          <div className="mb-4">
            <p className="text-base font-headline font-semibold text-on-surface leading-snug">
              {playbook!.headline}
            </p>
          </div>
        )}

        {/* Chip row — regime / funding / rotation at a glance */}
        <div className="flex flex-wrap items-center gap-2 mb-4">
          {hasCompound && (
            <div className="flex items-center gap-2 rounded px-2.5 py-1.5 bg-[#242533] border border-[#93d1d3]/15">
              <span className="text-[10px] font-semibold uppercase tracking-[0.1em] text-on-surface-variant/50">
                Regime
              </span>
              <span className="text-[12px] font-semibold text-on-surface">
                {compound!.label.replace(/_/g, " ")}
              </span>
              <span className="text-[10px] font-num tabular-nums text-[#93d1d3]/70">
                {(compound!.confidence).toFixed(2)}
              </span>
              {transition && transition.state !== "unavailable" && (
                <span className={cn(
                  "text-[10px] font-semibold uppercase tracking-wider",
                  _transitionTone(transition.state),
                )}>
                  · {transition.state}
                </span>
              )}
            </div>
          )}

          {hasFunding && (
            <div className={cn(
              "flex items-center gap-2 rounded px-2.5 py-1.5 border",
              _severityTone(funding!.composite_severity),
            )}>
              <span className="text-[10px] font-semibold uppercase tracking-[0.1em] opacity-70">
                Funding
              </span>
              <span className="text-[12px] font-semibold">
                {funding!.primary_mode.replace(/_/g, " ")}
              </span>
              <span className="text-[10px] font-semibold uppercase tracking-wider opacity-80">
                {funding!.composite_severity}
              </span>
            </div>
          )}

          {rotation?.available && (
            <div className={cn(
              "flex items-center gap-2 rounded px-2.5 py-1.5 border",
              _tiltTone(rotation.broad_market_tilt),
            )}>
              <span className="text-[10px] font-semibold uppercase tracking-[0.1em] opacity-70">
                Tape
              </span>
              <span className="text-[11px] font-semibold uppercase tracking-wider">
                {rotation.broad_market_tilt.replace(/_/g, " ")}
              </span>
            </div>
          )}
        </div>

        {/* Sector-rotation winners / losers */}
        {hasRotation && (topWinners.length > 0 || topLosers.length > 0) && (
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <div className="text-[10.5px] font-semibold uppercase tracking-[0.14em] text-[#93d1d3]/70 mb-1.5">
                Rotation winners
              </div>
              <div className="flex flex-wrap gap-1.5">
                {topWinners.map((sym) => (
                  <span key={sym}
                    className="text-[11px] font-num tabular-nums font-semibold px-2 py-0.5 rounded bg-[#242533] border border-[#93d1d3]/20 text-[#93d1d3]"
                  >
                    {sym}
                  </span>
                ))}
                {topWinners.length === 0 && (
                  <span className="text-[10px] text-on-surface-variant/40">—</span>
                )}
              </div>
            </div>
            <div>
              <div className="text-[10.5px] font-semibold uppercase tracking-[0.14em] text-error-dim/70 mb-1.5">
                Rotation losers
              </div>
              <div className="flex flex-wrap gap-1.5">
                {topLosers.map((sym) => (
                  <span key={sym}
                    className="text-[11px] font-num tabular-nums font-semibold px-2 py-0.5 rounded bg-[#242533] border border-error-dim/20 text-error-dim"
                  >
                    {sym}
                  </span>
                ))}
                {topLosers.length === 0 && (
                  <span className="text-[10px] text-on-surface-variant/40">—</span>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Coherence flags — explicit cross-block contradictions */}
        {playbook?.coherence_flags && playbook.coherence_flags.length > 0 && (
          <div className="pt-3 border-t border-white/5">
            <div className="text-[10.5px] font-semibold uppercase tracking-[0.14em] text-[#ee7d77]/75 mb-1.5">
              Coherence flags
            </div>
            <ul className="space-y-1">
              {playbook.coherence_flags.slice(0, 3).map((flag, i) => (
                <li key={i} className="text-[11px] text-on-surface-variant/80 leading-snug">
                  · {flag}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* What would change the read — concrete falsifiers */}
        {playbook?.what_would_change_the_read && playbook.what_would_change_the_read.length > 0 && (
          <div className="pt-3 mt-3 border-t border-white/5">
            <div className="text-[10.5px] font-semibold uppercase tracking-[0.14em] text-on-surface-variant/60 mb-1.5">
              What would change the read
            </div>
            <ul className="space-y-1">
              {playbook.what_would_change_the_read.slice(0, 3).map((watch, i) => (
                <li key={i} className="text-[11px] text-on-surface-variant/70 leading-snug">
                  · {watch}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}

export function RegimeStrip({
  rates,
  regimeVec,
  isLoading,
  explanation,
}: {
  rates: (import("@/lib/api").RatesContext & { available?: boolean }) | null;
  regimeVec: import("@/lib/api").RegimeVector | null;
  isLoading: boolean;
  explanation?: ContextExplanation | null;
}) {
  if (isLoading) return null;

  const hasRates = rates && rates.available !== false && rates.regime && rates.regime !== "Unknown";
  const hasVec = regimeVec && regimeVec.available;

  if (!hasRates && !hasVec) return null;

  const axes = hasVec
    ? (["inflation", "policy_stance", "fx", "growth_stress"] as const)
        .map((k) => ({ key: k, value: regimeVec[k] as string }))
        .filter((a) => a.value && a.value !== "neutral")
    : [];

  if (!hasRates && axes.length === 0) return null;

  return (
    <section className="mb-6">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-on-surface-variant/55 mr-1">
          Macro Regime
        </span>
        {hasRates && (
          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-[0.1em] bg-white/[0.04] text-on-surface-variant/80">
            {rates.regime}
          </span>
        )}
        {axes.map((a) => (
          <span
            key={a.key}
            className={cn(
              "inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-[0.1em]",
              _axisChipClass(a.key, a.value),
            )}
          >
            {_AXIS_LABELS[a.value] ?? a.value.replace(/_/g, " ")}
          </span>
        ))}
      </div>
      <ContextExplanationDisclosure explanation={explanation} className="mt-2 max-w-3xl" />
    </section>
  );
}

// ---------------------------------------------------------------------------
// Regime Playbook — compact panel of past high-quality validated events
// shown when the market is in an elevated stress regime.
// ---------------------------------------------------------------------------

function _pbValidationClass(outcome: PlaybookEntry["validation_outcome"]): string {
  if (outcome === "validated")   return "text-[#6ec6a5]";
  if (outcome === "contradicted") return "text-[#ee7d77]";
  return "text-on-surface-variant/40";
}

export function RegimePlaybook({
  regime,
  onAnalyze,
}: {
  regime: string;
  onAnalyze?: (headline: string, opts?: { eventId?: number }) => void;
}) {
  const { data, isLoading } = useQuery({
    queryKey: qk.regimePlaybook(regime),
    queryFn: () => api.regimePlaybook(regime, 4),
    staleTime: 300_000,
    enabled: regime !== "Calm" && !!regime,
  });

  if (isLoading) return null;
  if (!data || data.length === 0) return null;

  return (
    <section className="mb-8">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-on-surface-variant/55">
          Regime Playbook
        </span>
        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-[0.1em] bg-white/[0.04] text-on-surface-variant/80">
          {regime}
        </span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {data.map((entry) => (
          <button
            key={entry.id}
            onClick={() => onAnalyze?.(entry.headline, { eventId: entry.id })}
            className="group text-left bg-surface-container-low rounded-md px-3 py-2.5 hover:bg-surface-container-high transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
          >
            {/* date + stage */}
            <div className="flex items-center justify-between gap-2 mb-1">
              <span className="font-mono text-[10px] text-on-surface-variant/50">
                {entry.event_date ?? "—"}
              </span>
              <div className="flex items-center gap-1.5">
                {entry.stage && (
                  <span className="metric-chip">{entry.stage}</span>
                )}
                {entry.persistence && (
                  <span className="metric-chip">{entry.persistence}</span>
                )}
              </div>
            </div>
            {/* headline */}
            <p className="text-[11px] font-semibold leading-snug line-clamp-2 group-hover:text-primary/80 transition-colors mb-1.5">
              {entry.headline}
            </p>
            {/* bottom row: validation + lead ticker */}
            <div className="flex items-center justify-between gap-2">
              <span className={cn(
                "text-[10px] font-medium",
                _pbValidationClass(entry.validation_outcome),
              )}>
                {entry.validation_outcome === "validated"
                  ? `Validated${entry.support_ratio !== null ? ` · ${Math.round(entry.support_ratio * 100)}%` : ""}`
                  : entry.validation_outcome === "contradicted"
                  ? "Contradicted"
                  : "Unresolved"}
              </span>
              {entry.lead_ticker?.symbol && (
                <div className="flex items-center gap-1 font-mono text-[10px]">
                  <span className="text-on-surface/70">{entry.lead_ticker.symbol}</span>
                  {entry.lead_ticker.return_5d !== null && (
                    <span className={cn(
                      "tabular-nums",
                      (entry.lead_ticker.return_5d ?? 0) >= 0
                        ? "text-primary/70" : "text-error-dim/70",
                    )}>
                      {(entry.lead_ticker.return_5d ?? 0) >= 0 ? "+" : ""}
                      {(entry.lead_ticker.return_5d ?? 0).toFixed(1)}%
                    </span>
                  )}
                </div>
              )}
            </div>
          </button>
        ))}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Track Record — hero achievement block
// ---------------------------------------------------------------------------

type CreditRegimeBlock = {
  available?: boolean;
  regime?: string;
  regime_label?: string;
  rationale?: string;
  hy_ig_differential_5d?: number | null;
  default_risk_signal?: "widening" | "tightening" | "quiet" | "unavailable";
  duration_signal?: "rising_rates" | "falling_rates" | "quiet" | "unavailable";
};

type CreditSignalChip = { label: string; tone: string };
type DefaultRiskSignal = NonNullable<CreditRegimeBlock["default_risk_signal"]>;
type DurationSignal = NonNullable<CreditRegimeBlock["duration_signal"]>;

const _DEFAULT_RISK_CHIP = {
  widening:    { label: "widening",   tone: "bg-error-dim/15 text-error-dim/90" },
  tightening:  { label: "tightening", tone: "bg-primary/15 text-primary/90" },
  quiet:       { label: "quiet",      tone: "bg-white/[0.04] text-on-surface-variant/70" },
  unavailable: { label: "n/a",        tone: "bg-white/[0.02] text-on-surface-variant/45" },
} satisfies Record<DefaultRiskSignal, CreditSignalChip>;

const _DURATION_CHIP = {
  rising_rates:  { label: "rising rates",  tone: "bg-error-dim/15 text-error-dim/90" },
  falling_rates: { label: "falling rates", tone: "bg-primary/15 text-primary/90" },
  quiet:         { label: "quiet",         tone: "bg-white/[0.04] text-on-surface-variant/70" },
  unavailable:   { label: "n/a",           tone: "bg-white/[0.02] text-on-surface-variant/45" },
} satisfies Record<DurationSignal, CreditSignalChip>;

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

function CreditRegimeCard({ credit }: { credit: CreditRegimeBlock | null }) {
  const unavailable = !credit || credit.available === false || (!credit.regime_label && !credit.regime && !credit.rationale);
  const label = unavailable ? "Unavailable" : credit.regime_label ?? credit.regime ?? "Unavailable";
  const note = unavailable
    ? "Credit-regime enrichment is unavailable for this market snapshot."
    : credit.rationale ?? "No credit-regime rationale is available for this market snapshot.";
  const differential = credit?.hy_ig_differential_5d;

  // Default-risk and duration are orthogonal — surface them as chips so a
  // "rates-driven bond weakness" read isn't mis-parsed as credit-stress
  // widening.  ``regime_label`` alone cannot make that distinction
  // unambiguously, especially under the legacy "Duration widening"
  // wording where "widening" overloaded with credit-spread parlance.
  const defaultRiskKey = credit?.default_risk_signal ?? "unavailable";
  const durationKey    = credit?.duration_signal    ?? "unavailable";
  const defaultRiskChip = _DEFAULT_RISK_CHIP[defaultRiskKey];
  const durationChip    = _DURATION_CHIP[durationKey];

  return (
    <div className="rounded-lg bg-surface-container-low px-5 py-4">
      <div className="mb-3.5 font-headline text-[12.5px] font-semibold uppercase tracking-[0.08em] text-on-surface-variant">
        Credit regime
      </div>
      <div className="mb-2 font-headline text-[18px] font-semibold tracking-tight text-on-surface">
        {label.replace(/_/g, " ")}
      </div>
      {!unavailable && (
        <div className="mb-3 flex flex-wrap items-center gap-1.5 text-[10.5px]">
          <span className="font-mono uppercase tracking-[0.08em] text-on-surface-variant/55">
            Credit-spread
          </span>
          <span className={cn(
            "rounded-full px-2 py-0.5 font-mono uppercase tracking-[0.06em]",
            defaultRiskChip.tone,
          )}>
            {defaultRiskChip.label}
          </span>
          <span className="ml-1.5 font-mono uppercase tracking-[0.08em] text-on-surface-variant/55">
            Duration
          </span>
          <span className={cn(
            "rounded-full px-2 py-0.5 font-mono uppercase tracking-[0.06em]",
            durationChip.tone,
          )}>
            {durationChip.label}
          </span>
        </div>
      )}
      <p className="text-[12px] leading-relaxed text-on-surface-variant/75">{note}</p>
      {!unavailable && differential != null && (
        <div className="mt-3 font-mono text-[11.5px] tabular-nums text-on-surface-variant/60">
          HY-IG 5d differential {differential >= 0 ? "+" : ""}{differential.toFixed(2)}
        </div>
      )}
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

function UncertaintyConcentrationCard({
  data,
  explanation,
}: {
  data: NewsUncertaintyConcentration | null;
  explanation?: ContextExplanation | null;
}) {
  const view = buildUncertaintyConcentrationView(data);

  return (
    <div className="rounded-lg bg-surface-container-low px-5 py-4">
      <div className="mb-3.5 flex items-baseline justify-between gap-3">
        <span className="font-headline text-[12.5px] font-semibold uppercase tracking-[0.08em] text-on-surface-variant">
          Uncertainty concentration
        </span>
        {view.entries.length > 0 && (
          <span className="text-[10.5px] uppercase tracking-[0.08em] text-on-surface-variant/55">
            {view.valueLabel}
          </span>
        )}
      </div>
      {view.entries.length > 0 ? (
        <div className="flex flex-col gap-1.5">
          {view.entries.map((entry) => (
            <div key={entry.key} className="grid grid-cols-[110px_1fr_44px] items-center gap-2.5 text-[12px]">
              <span className="truncate capitalize text-on-surface-variant/80">{entry.key}</span>
              <span className="relative h-1.5 overflow-hidden rounded-full bg-white/[0.04]">
                <span
                  className="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-primary/75 to-error-dim/75"
                  style={{ width: `${entry.barPct}%` }}
                />
              </span>
              <span className="text-right font-mono text-[11.5px] tabular-nums text-on-surface/80">
                {entry.value}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-[12px] leading-relaxed text-on-surface-variant/70">
          {view.emptyCopy}
        </p>
      )}
      <div className="mt-4 border-t border-outline-variant/15 pt-3 text-[11px] leading-relaxed text-on-surface-variant/60">
        {view.footer}
      </div>
      <ContextExplanationDisclosure explanation={explanation} className="mt-3 bg-white/[0.012]" />
    </div>
  );
}

function HighlightsCard({ highlights }: { highlights: MarketMover[] }) {
  const items = highlights.slice(0, 5);
  return (
    <div className="rounded-lg bg-surface-container-low px-5 py-4">
      <div className="mb-3.5 font-headline text-[12.5px] font-semibold uppercase tracking-[0.08em] text-on-surface-variant">
        Highlights <span className="text-[11.5px] normal-case tracking-normal text-on-surface-variant/55">editorial</span>
      </div>
      {items.length > 0 ? (
        <div className="flex flex-col">
          {items.map((item, idx) => {
            const tone = item.support_ratio >= 0.6 ? "bg-primary" : item.support_ratio <= 0.25 ? "bg-error-dim" : "bg-on-surface-variant/45";
            return (
              <div
                key={`${item.event_id}-${idx}`}
                className={cn(
                  "grid grid-cols-[12px_1fr_auto] items-start gap-3 py-2.5",
                  idx < items.length - 1 && "border-b border-outline-variant/15",
                )}
              >
                <span className={cn("mt-2 h-1 w-1 rounded-full", tone)} />
                <span className="min-w-0 text-[12.5px] leading-snug text-on-surface/90 line-clamp-2">
                  {item.headline}
                </span>
                <span className="font-mono text-[11px] uppercase text-on-surface-variant/45">
                  {item.stage}
                </span>
              </div>
            );
          })}
        </div>
      ) : (
        <p className="text-[12px] leading-relaxed text-on-surface-variant/70">
          No market highlights are available yet.
        </p>
      )}
    </div>
  );
}

function SectorRotationCard({ rotation }: { rotation: SectorRotation | null }) {
  const sectors = rotation?.available
    ? rotation.sectors.slice(0, 11).map((s) => ({
        key: s.symbol,
        value: s.net_score,
        dir: s.direction === "winner" ? "up" : s.direction === "loser" ? "dn" : "flat",
      }))
    : [];

  return (
    <div className="rounded-lg bg-surface-container-low px-5 py-4">
      <div className="mb-3.5 font-headline text-[12.5px] font-semibold uppercase tracking-[0.08em] text-on-surface-variant">
        Sector rotation <span className="text-[11.5px] normal-case tracking-normal text-on-surface-variant/55">5-day relative</span>
      </div>
      {sectors.length > 0 ? (
        <>
          <div className="grid grid-cols-6 gap-1 sm:grid-cols-11">
            {sectors.map((sector) => {
              const height = Math.max(8, Math.min(52, Math.abs(sector.value) * 34));
              const color = sector.dir === "up"
                ? "rgba(147,209,211,0.85)"
                : sector.dir === "dn"
                  ? "rgba(238,125,119,0.85)"
                  : "rgba(255,255,255,0.18)";
              return (
                <div key={sector.key} className="flex flex-col items-center gap-1.5 rounded-md bg-white/[0.02] px-1 py-2">
                  <div className="flex h-[52px] w-full items-end justify-center">
                    <span className="w-3.5 rounded-t-sm" style={{ height, background: color }} />
                  </div>
                  <span className="font-mono text-[11px] text-on-surface-variant/60">{sector.key}</span>
                  <span className={cn(
                    "font-mono text-[11px] tabular-nums",
                    sector.dir === "up" ? "text-primary" : sector.dir === "dn" ? "text-error-dim" : "text-on-surface-variant/55",
                  )}>
                    {sector.value >= 0 ? "+" : ""}{sector.value.toFixed(1)}
                  </span>
                </div>
              );
            })}
          </div>
          {rotation?.rationale && (
            <div className="mt-4 border-t border-outline-variant/15 pt-3 text-[11px] leading-relaxed text-on-surface-variant/65">
              {rotation.rationale}
            </div>
          )}
        </>
      ) : (
        <p className="text-[12px] leading-relaxed text-on-surface-variant/70">
          Sector-rotation enrichment is unavailable for this snapshot.
        </p>
      )}
    </div>
  );
}

function RegimeInterpretationSection({
  regimeVec,
  credit,
  uncertainty,
  highlights,
  rotation,
  isLoading,
  regimeVectorExplanation,
  uncertaintyExplanation,
}: {
  regimeVec:
    | (RegimeVector & {
        compound?: { label: string; confidence: number; rationale: string };
        transition?: { state: string; rationale: string };
      })
    | null;
  credit: CreditRegimeBlock | null;
  uncertainty: NewsUncertaintyConcentration | null;
  highlights: MarketMover[];
  rotation: SectorRotation | null;
  isLoading: boolean;
  regimeVectorExplanation?: ContextExplanation | null;
  uncertaintyExplanation?: ContextExplanation | null;
}) {
  if (isLoading) {
    return (
      <section className="mb-8">
        <div className="grid gap-5 lg:grid-cols-[1.3fr_1fr_1fr]">
          <Skeleton className="h-52 rounded-lg bg-surface-container-highest" />
          <Skeleton className="h-52 rounded-lg bg-surface-container-highest" />
          <Skeleton className="h-52 rounded-lg bg-surface-container-highest" />
        </div>
      </section>
    );
  }

  return (
    <section className="mb-8 space-y-5">
      <div className="grid gap-5 lg:grid-cols-[1.3fr_1fr_1fr]">
        <RegimeVectorCard regimeVec={regimeVec} explanation={regimeVectorExplanation} />
        <CreditRegimeCard credit={credit} />
        <UncertaintyConcentrationCard data={uncertainty} explanation={uncertaintyExplanation} />
      </div>
      <div className="grid gap-5 lg:grid-cols-[1fr_1.2fr]">
        <HighlightsCard highlights={highlights} />
        <SectorRotationCard rotation={rotation} />
      </div>
    </section>
  );
}

// Backend ``finance_playbook.py`` always emits a per-line string; when an
// engine block is missing it returns the canonical placeholder shape
// ``"<Label>: — (<reason>)"`` (e.g. ``"Thesis: — (scorecard unavailable)"``).
// Real data lines never contain that exact ``": — ("`` sequence — the
// Thesis line has no colon at all when populated, and every other label
// renders concrete content after the colon.  Treat the placeholder shape
// as "no data" so the panel hides the row instead of showing the
// placeholder verbatim.
function isPlaceholderLine(s: string | null | undefined): boolean {
  return typeof s === "string" && s.includes(": — (");
}

function ActionableReadPanel({
  playbook,
  unavailable,
}: {
  playbook: FinancePlaybook | null;
  unavailable?: boolean;
}) {
  const cleanLine = (s: string | null | undefined) =>
    isPlaceholderLine(s) ? undefined : s;

  const rows = playbook?.available
    ? [
        {
          reg:   "Regime",
          claim: cleanLine(playbook.lines?.regime) ?? playbook.headline,
          meta:  cleanLine(playbook.base_case?.rationale),
        },
        {
          reg:   "Funding",
          claim: cleanLine(playbook.lines?.funding),
          meta:  cleanLine(playbook.lines?.rotation),
        },
        {
          reg:   "Thesis",
          claim: cleanLine(playbook.lines?.thesis),
          meta:  cleanLine(playbook.lines?.analogs),
        },
      ].filter((row) => row.claim)
    : [];

  if (unavailable || rows.length === 0) {
    return (
      <section className="mb-8 rounded-lg bg-surface-container-low px-5 py-4">
        <div className="mb-3.5 font-headline text-[12.5px] font-semibold uppercase tracking-[0.08em] text-on-surface-variant">
          How this regime trades <span className="text-[11.5px] normal-case tracking-normal text-on-surface-variant/55">model-generated, track-record weighted</span>
        </div>
        <div className="rounded-md bg-white/[0.02] px-4 py-3">
          <p className="text-[12px] leading-relaxed text-on-surface-variant/70">
            Actionable read unavailable while market context is degraded.
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="mb-8 rounded-lg bg-surface-container-low px-5 py-4">
      <div className="mb-3.5 font-headline text-[12.5px] font-semibold uppercase tracking-[0.08em] text-on-surface-variant">
        How this regime trades <span className="text-[11.5px] normal-case tracking-normal text-on-surface-variant/55">model-generated, track-record weighted</span>
      </div>
      <div className="flex flex-col gap-1.5">
        {rows.map((row) => (
          <div key={row.reg} className="grid gap-3 rounded-md bg-white/[0.022] px-3.5 py-3 sm:grid-cols-[90px_1fr]">
            <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-on-surface-variant/65">
              {row.reg}
            </span>
            <p className="text-[13px] leading-snug text-on-surface">
              {row.claim}
              {row.meta && (
                <span className="mt-1 block text-[12px] text-on-surface-variant/65">{row.meta}</span>
              )}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
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

function PhaseOneDiagnosticsStrip({
  validation,
  reaction,
  isLoading,
}: {
  validation?: ValidationStatusStats;
  reaction?: ReactionProfileStats;
  isLoading: boolean;
}) {
  if (isLoading) {
    return (
      <section className="mb-4">
        <Skeleton className="h-24 rounded-lg bg-surface-container-low" />
      </section>
    );
  }

  if (!validation && !reaction) return null;

  const validationCounts = validation?.counts_by_status;
  const ready = reaction?.events_with_profile_input_ready ?? 0;
  const total = reaction?.total_events ?? 0;
  const readyPct = total > 0 ? Math.round((ready / total) * 100) : null;

  return (
    <section className="mb-4 rounded-lg bg-surface-container-low px-4 py-3">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-on-surface-variant/65">
            Phase 1 diagnostics
          </p>
          <p className="mt-0.5 text-[11px] text-on-surface-variant/50">
            Zero-cost archive reads for validation status and reaction-profile readiness.
          </p>
        </div>
        <span className="text-[10.5px] tabular-nums text-on-surface-variant/45">
          {validation?.total_events ?? reaction?.total_events ?? 0} events
        </span>
      </div>

      <div className="grid gap-2 md:grid-cols-2">
        {validation && (
          <div className="rounded-md bg-white/[0.02] px-3 py-2">
            <div className="mb-2 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-on-surface-variant/45">
              Validation status
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <MetricCard label="Pending" value={validationCounts?.pending ?? 0} accent="text-[#facc15]/85" />
              <MetricCard label="Validated" value={validationCounts?.validated ?? 0} accent="text-primary" />
              <MetricCard label="Contradicted" value={validationCounts?.contradicted ?? 0} accent="text-error-dim" />
              <MetricCard label="Unresolved" value={validationCounts?.unresolved ?? 0} accent="text-on-surface-variant/50" />
            </div>
          </div>
        )}

        {reaction && (
          <div className="rounded-md bg-white/[0.02] px-3 py-2">
            <div className="mb-2 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-on-surface-variant/45">
              Reaction profiles
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <MetricCard label="Ready" value={reaction.events_with_profile_input_ready} accent="text-primary" />
              <MetricCard label="Unscorable" value={reaction.events_unscorable} accent="text-on-surface-variant/50" />
              <MetricCard label="Tickers" value={reaction.tickers_with_scalar_returns} />
              {readyPct !== null && (
                <MetricCard label="Coverage" value={`${readyPct}%`} />
              )}
            </div>
          </div>
        )}
      </div>
    </section>
  );
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

// ---------------------------------------------------------------------------
// Policy Tracker — compact list (top 3-5 active policies, expandable).
// Replaces the prior chip-cloud treatment.  Each row shows:
//   type · region · short title · status (with timing hint).
// Mirrors the headlines-page PolicyTrackerStrip pattern visually so a
// user moving between Market Context and Headlines reads the same
// vocabulary on both surfaces.  No backend / data-shape change.
// ---------------------------------------------------------------------------

const _MO_POLICY_TYPE_LABEL: Record<string, string> = {
  tariff:          "Tariff",
  sanction:        "Sanction",
  regulation:      "Rule",
  executive_order: "EO",
  rate_decision:   "Rate",
};

/** Per-type accent — drives the left-edge stripe and the type-label tone.
 *  Tariff & sanction share a coral accent (restrictive), rate is teal
 *  (monetary), EO is amber, rule is neutral.  Mirrors the Headlines
 *  surface so the same policy reads identically in both places. */
const _MO_POLICY_TYPE_ACCENT: Record<string, { stripe: string; label: string }> = {
  tariff:          { stripe: "bg-[#ee7d77]/65", label: "text-[#ee7d77]" },
  sanction:        { stripe: "bg-[#ee7d77]/65", label: "text-[#ee7d77]" },
  rate_decision:   { stripe: "bg-[#93d1d3]/65", label: "text-[#93d1d3]" },
  executive_order: { stripe: "bg-[#facc15]/55", label: "text-[#facc15]/85" },
  regulation:      { stripe: "bg-on-surface-variant/35", label: "text-on-surface-variant/75" },
};

const _MO_STATUS_PRIORITY: Record<string, number> = {
  revisit_due:   0,
  active:        1,
  pre_effective: 2,
  announced:     3,
  past:          99,
};

const _MO_STATUS_LABEL: Record<string, string> = {
  revisit_due:   "Revisit due",
  active:        "Active",
  pre_effective: "Pre-effective",
  announced:     "Announced",
  past:          "Past",
};

const _MO_STATUS_TONE: Record<string, string> = {
  revisit_due:   "bg-[#ee7d77]/15 text-[#ee7d77]",
  active:        "bg-[#93d1d3]/15 text-[#93d1d3]",
  pre_effective: "bg-[#facc15]/12 text-[#facc15]",
  announced:     "bg-white/[0.04] text-on-surface-variant",
  past:          "bg-white/[0.02] text-on-surface-variant/55",
};

const _MO_POLICY_DEFAULT_VISIBLE = 4;

function _moStatusLabelFor(item: PolicyItem): string {
  // Same timing-hint vocabulary as Headlines: "Revisit due · 2d" /
  // "Pre-effective · today".  Drops to the bare label for "active"
  // and "past" where the day count carries no urgency.
  const base = _MO_STATUS_LABEL[item.status] ?? item.status;
  if (item.status === "revisit_due") {
    const d = item.days_until_revisit;
    if (d <= 0) return `${base} · today`;
    if (d === 1) return `${base} · 1d`;
    return `${base} · ${d}d`;
  }
  if (item.status === "pre_effective" || item.status === "announced") {
    const d = item.days_until;
    if (d <= 0) return `${base} · today`;
    if (d === 1) return `${base} · 1d`;
    return `${base} · ${d}d`;
  }
  return base;
}

function _moSortPolicyItems(items: PolicyItem[]): PolicyItem[] {
  // Strip past items and sort by status priority then by proximity
  // (days_until_revisit for revisit items, days_until for the rest).
  const live = items.filter((i) => i.status !== "past");
  return live.slice().sort((a, b) => {
    const pa = _MO_STATUS_PRIORITY[a.status] ?? 50;
    const pb = _MO_STATUS_PRIORITY[b.status] ?? 50;
    if (pa !== pb) return pa - pb;
    const aProx = a.status === "revisit_due" ? a.days_until_revisit : a.days_until;
    const bProx = b.status === "revisit_due" ? b.days_until_revisit : b.days_until;
    return aProx - bProx;
  });
}

function PolicyItemRow({ item }: { item: PolicyItem }) {
  const accent = _MO_POLICY_TYPE_ACCENT[item.policy_type]
    ?? { stripe: "bg-on-surface-variant/35", label: "text-on-surface-variant/75" };
  const typeLabel = _MO_POLICY_TYPE_LABEL[item.policy_type] ?? item.policy_type;
  const statusTone = _MO_STATUS_TONE[item.status] ?? "bg-white/[0.04] text-on-surface-variant";

  return (
    <div
      title={item.description}
      className="relative flex items-center gap-2.5 rounded-md bg-white/[0.02] pl-3 pr-2.5 py-2"
    >
      <span aria-hidden className={cn("absolute left-0 top-1.5 bottom-1.5 w-[2px] rounded-r-sm", accent.stripe)} />
      <span className={cn("text-[11px] font-semibold uppercase tracking-[0.1em] shrink-0", accent.label)}>
        {typeLabel}
      </span>
      <span className="text-[11px] font-mono tabular-nums uppercase text-on-surface-variant/55 shrink-0">
        {item.jurisdiction}
      </span>
      <span className="text-[12.5px] font-medium text-on-surface min-w-0 flex-1 truncate">
        {item.name}
      </span>
      <span className={cn(
        "shrink-0 inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-[0.08em]",
        statusTone,
      )}>
        {_moStatusLabelFor(item)}
      </span>
    </div>
  );
}

export function PolicyContextStrip({ items }: { items: PolicyItem[] }) {
  const sorted = _moSortPolicyItems(items);
  const [expanded, setExpanded] = useState(false);
  if (sorted.length === 0) return null;

  const visible = expanded ? sorted : sorted.slice(0, _MO_POLICY_DEFAULT_VISIBLE);
  const hidden  = expanded ? [] : sorted.slice(_MO_POLICY_DEFAULT_VISIBLE);

  return (
    <section data-testid="policy-tracker" className="mb-4 rounded-lg bg-card px-3 py-3">
      <div className="mb-2 flex items-baseline gap-2">
        <Scale className="h-3 w-3 text-on-surface-variant/55" />
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-on-surface-variant/65">
          Policy Tracker
        </h3>
        <span className="font-mono text-[11px] tabular-nums text-on-surface-variant/45">
          {sorted.length}
        </span>
      </div>

      <div className="flex flex-col gap-1.5">
        {visible.map((item) => (
          <PolicyItemRow
            key={`${item.policy_type}-${item.effective_date}-${item.name}`}
            item={item}
          />
        ))}
      </div>

      {hidden.length > 0 && !expanded && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="mt-2 inline-flex items-center gap-1.5 text-[11px] font-medium text-on-surface-variant/70 hover:text-on-surface transition-colors"
        >
          <ChevronDown className="h-3 w-3" />
          View all policies
          <span className="font-mono tabular-nums text-on-surface-variant/55">
            +{hidden.length}
          </span>
        </button>
      )}

      {expanded && sorted.length > _MO_POLICY_DEFAULT_VISIBLE && (
        <button
          type="button"
          onClick={() => setExpanded(false)}
          className="mt-2 inline-flex items-center gap-1.5 text-[11px] font-medium text-on-surface-variant/70 hover:text-on-surface transition-colors"
        >
          <ChevronDown className="h-3 w-3 rotate-180" />
          Collapse
        </button>
      )}
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

  const { data: registryDiagnostics } = useQuery({
    queryKey: qk.registryDiagnostics(),
    queryFn: () => api.registryDiagnostics(),
    staleTime: 300_000,
    refetchInterval: 300_000,
  });

  const { data: candidateQueue } = useQuery({
    queryKey: qk.registryCandidateQueue(25, 72),
    queryFn: () => api.registryCandidateQueue({ limit: 25, sinceHours: 72 }),
    staleTime: 300_000,
    refetchInterval: 300_000,
  });

  const { data: backfillPreview } = useQuery({
    queryKey: qk.backfillPreview(5, 72),
    queryFn: () => api.backfillPreview({ limit: 5, sinceHours: 72 }),
    staleTime: 300_000,
    refetchInterval: 300_000,
  });

  const { data: trackRecord, isLoading: trackLoading } = useQuery({
    queryKey: qk.trackRecord(),
    queryFn: () => api.trackRecord(),
    staleTime: 300_000,
  });

  const { data: validationStats, isLoading: validationStatsLoading } = useQuery({
    queryKey: qk.validationStatusStats(),
    queryFn: () => api.validationStatusStats(),
    staleTime: 300_000,
  });

  const { data: reactionStats, isLoading: reactionStatsLoading } = useQuery({
    queryKey: qk.reactionProfileStats(),
    queryFn: () => api.reactionProfileStats(),
    staleTime: 300_000,
  });

  const { data: newsData, isLoading: newsLoading } = useQuery({
    queryKey: qk.newsPaginated(30),
    queryFn: () => api.news(30),
    staleTime: 300_000,
  });

  // Distribute the unified context to child components.
  const stress = ctx?.stress ?? null;
  const rates = ctx?.rates ?? null;
  const regimeVec = ctx?.regime_vector ?? null;
  const snapshots = ctx?.snapshots ?? null;
  const uncertaintyConcentration = ctx?.uncertainty_concentration ?? null;
  const contextExplanations = ctx?.context_explanations ?? {};
  const todaysHighlights = ctx?.highlights ?? [];

  // Deeper engine blocks — surfaced by the /market-context enrichment.
  // Each carries its own ``available`` flag so Section B can map live
  // data into the approved design cards without changing API contracts.
  const financePlaybook = ctx?.finance_playbook ?? null;
  const creditRegime = ctx?.credit_regime ?? null;
  const sectorRotation = ctx?.sector_rotation ?? null;
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
        Section order — design package + brief:
          1. Raw market state         (what the market is doing)
          2. Regime interpretation    (what the engine reads it as)
          3. Movers                   (which events are moving things)
          4. Actionable read          (what changed, where to look next)
        Each block renders nothing when its data is empty so the page
        degrades gracefully on a cold-start install.
      */}

      {/* ────────────────── A · RAW MARKET STATE ────────────────── */}
      <div className="flex items-baseline justify-between mb-3 mt-2">
        <p className="section-kicker">Snapshot</p>
        <span className="text-[11px] text-on-surface-variant/55">
          A · Raw market state
        </span>
      </div>

      {/* Liquid Benchmark Snapshots — equities / rates / FX / commodities
          read at a glance.  Leads the page per the approved design
          package: the user opens on the snapshot read, not on a hero
          headline.  Warm-cached; hides cleanly when empty. */}
      <BenchmarkSnapshotsStrip snapshots={snapshots} isLoading={ctxLoading} />
      <ContextExplanationDisclosure
        explanation={contextExplanations.snapshots}
        className="-mt-6 mb-6"
      />

      {/* Stress card — compact regime panel + indicator grid.  No
          longer the page hero; sits below Snapshot as the "plumbing &
          vol" companion. */}
      <UncertaintySection
        stress={stress}
        isLoading={ctxLoading}
        uncertaintyConcentration={uncertaintyConcentration}
      />
      <ContextExplanationDisclosure
        explanation={contextExplanations.stress}
        className="-mt-4 mb-6"
      />

      {/* ─────────────── B · REGIME INTERPRETATION ─────────────── */}
      <div className="flex items-baseline justify-between mb-3 mt-2">
        <p className="section-kicker">Regime</p>
        <span className="text-[11px] text-on-surface-variant/55">
          B · Regime interpretation
        </span>
      </div>

      {/* Macro System — compound regime, funding-liquidity mode, sector
          rotation and the finance-playbook headline.  The institutional
          synthesis sits above the chip-level reads so the eye lands on
          the desk-quotable line first. */}
      <RegimeInterpretationSection
        regimeVec={regimeVec}
        credit={creditRegime}
        uncertainty={uncertaintyConcentration}
        highlights={todaysHighlights}
        rotation={sectorRotation}
        isLoading={ctxLoading}
        regimeVectorExplanation={contextExplanations.regime_vector}
        uncertaintyExplanation={contextExplanations.uncertainty_concentration}
      />

      {/* Macro Regime — rates regime + regime-vector axes (inflation /
          policy / FX / growth-stress) condensed into a single chip row. */}
      <RegimeStrip
        rates={rates}
        regimeVec={regimeVec}
        isLoading={ctxLoading}
        explanation={contextExplanations.rates}
      />

      {/* Policy Context — active / pre-effective / revisit-due policy
          items (tariffs, sanctions, rate decisions). */}


      {/* Trending Themes — dominant actions/sectors across recent clusters. */}


      {/* Regime Playbook — past validated events in similar conditions. */}


      {/* ──────────────────── C · MOVERS ──────────────────── */}
      {/* Three visually-distinct windows: Today (4-up cards) → Weekly
          (2-up editorial cards w/ sparkline) → Persistent (horizontal
          rows).  Backend already gates persistent to high-impact
          items via ``is_high_conviction_persistent`` — no extra
          frontend filter.  Today is fed by /market-context highlights
          (no separate fetch).  The chapter head inside ``MoversChapter``
          carries the C · Movers kicker. */}
      <MoversChapter
        today={todaysHighlights}
        weekly={weekly}
        persistent={persistent}
        registryDiagnostics={registryDiagnostics}
        candidateQueue={candidateQueue}
        backfillPreview={backfillPreview}
        todayLoading={ctxLoading}
        weeklyLoading={weeklyLoading}
        persistentLoading={persistentLoading}
        onAnalyze={onAnalyze}
      />

      {/* ─────────────── D · ACTIONABLE READ ─────────────── */}
      <div className="flex items-baseline justify-between mb-3 mt-8">
        <p className="section-kicker">Actionable read</p>
        <span className="text-[11px] text-on-surface-variant/55">
          D · what changed, where to look next
        </span>
      </div>

      {/* Latest Headlines — compact cluster strip with analyze action. */}
      <ActionableReadPanel
        playbook={financePlaybook}
      />

      <LatestHeadlinesStrip
        clusters={newsData?.clusters ?? []}
        isLoading={newsLoading}
        onAnalyze={onAnalyze}
        refreshMeta={newsData?.refresh_meta}
        failedHeadlines={failedHeadlines}
      />

      <PhaseOneDiagnosticsStrip
        validation={validationStats}
        reaction={reactionStats}
        isLoading={validationStatsLoading || reactionStatsLoading}
      />

      {/* Track Record — thesis outcome summary (hit rate, validated /
          contradicted / unresolved). */}
      <div className="pt-6">
        <TrackRecordStrip data={trackRecord} isLoading={trackLoading} />
      </div>

      {/* System Health — compact pipeline health panel. */}
      <SystemHealthPanel />
    </div>
  );
}
