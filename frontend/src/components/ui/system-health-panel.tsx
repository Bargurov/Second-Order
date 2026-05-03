/**
 * SystemHealthPanel — compact pipeline-health summary for Market Overview.
 *
 * Self-contained: owns its own /health/detail query.
 * Design: one quiet row when healthy; auto-expands with feed failure list
 * when degraded or errored.  Never blocks page render — returns null until
 * data arrives.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronUp } from "lucide-react";
import { api, type HealthDetail } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Pure helpers — exported for tests
// ---------------------------------------------------------------------------

export function ageLabel(seconds: number | null): string {
  if (seconds === null) return "–";
  if (seconds < 60)    return "just now";
  if (seconds < 3600)  return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export function overallVariant(
  overall: HealthDetail["overall"],
): "ok" | "degraded" | "error" | "no_data" {
  return overall;
}

// ---------------------------------------------------------------------------
// Panel
// ---------------------------------------------------------------------------

export function SystemHealthPanel() {
  const [expanded, setExpanded] = useState(false);

  const { data } = useQuery({
    queryKey: qk.healthDetail(),
    queryFn:  () => api.healthDetail(),
    refetchInterval: 60_000,
    staleTime:       30_000,
    retry: false,
  });

  if (!data) return null;

  const { overall, feed_health, pipeline, refresh_age_seconds, refresh_at } = data;
  const hasFailing = feed_health.failed > 0;
  const isError    = overall === "error";
  const isDegraded = overall === "degraded";
  const showList   = (expanded || isError) && hasFailing;

  const dotClass = isError ? "bg-error-dim" : isDegraded ? "bg-[#facc15]" : "bg-primary/60";
  const labelClass = isError
    ? "text-error-dim/80"
    : isDegraded
    ? "text-[#facc15]/70"
    : "text-on-surface-variant/40";

  const freshnessChip =
    pipeline.freshness === "stale"    ? "bg-error-dim/10 text-error-dim/60"
    : pipeline.freshness === "degraded" ? "bg-[#facc15]/10 text-[#facc15]/60"
    : pipeline.freshness === "fresh"    ? "bg-primary/10 text-primary/50"
    : null;

  return (
    <section className="mt-8">
      {/* Row */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[9px] font-bold uppercase tracking-[0.15em] text-on-surface-variant/30 mr-1">
          System Health
        </span>

        {/* Overall dot + label */}
        <span className="flex items-center gap-1.5">
          <span className={cn("h-1.5 w-1.5 rounded-full shrink-0", dotClass)} />
          <span className={cn("text-[9px] font-bold uppercase tracking-wider", labelClass)}>
            {isError ? "Error" : isDegraded ? "Degraded" : overall === "no_data" ? "No data" : "Ok"}
          </span>
        </span>

        <span className="text-on-surface-variant/20 text-[9px]">·</span>

        {/* Feed ratio */}
        <span className={cn(
          "text-[9px] font-bold uppercase tracking-wider",
          hasFailing ? "text-error-dim/60" : "text-on-surface-variant/35",
        )}>
          Feeds {feed_health.ok}/{feed_health.total}
        </span>

        {/* Refresh age */}
        {refresh_at && (
          <>
            <span className="text-on-surface-variant/20 text-[9px]">·</span>
            <span className="text-[9px] text-on-surface-variant/35 font-num tabular-nums">
              {ageLabel(refresh_age_seconds)}
            </span>
          </>
        )}

        {/* Freshness chip */}
        {freshnessChip && (
          <span className={cn(
            "inline-flex items-center px-1.5 py-px rounded text-[8px] font-bold uppercase tracking-widest",
            freshnessChip,
          )}>
            {pipeline.freshness}
          </span>
        )}

        {/* Cluster count */}
        {pipeline.clusters_cached > 0 && (
          <>
            <span className="text-on-surface-variant/20 text-[9px]">·</span>
            <span className="text-[9px] text-on-surface-variant/30 font-num tabular-nums">
              {pipeline.clusters_cached} clusters
            </span>
          </>
        )}

        {/* Expand toggle — only when there are failures and not auto-expanded */}
        {hasFailing && !isError && (
          <button
            onClick={() => setExpanded((v) => !v)}
            className="ml-auto flex items-center gap-1 text-[9px] text-on-surface-variant/30 hover:text-on-surface-variant/60 transition-colors"
          >
            {expanded
              ? <><ChevronUp className="h-3 w-3" /><span>Hide</span></>
              : <><ChevronDown className="h-3 w-3" /><span>{feed_health.failed} failed</span></>}
          </button>
        )}
      </div>

      {/* Failing feeds list */}
      {showList && (
        <div className="mt-1.5 space-y-1">
          {feed_health.failing.map((f) => (
            <div
              key={f.name}
              className="flex items-start gap-2 bg-surface-container-low rounded px-2.5 py-1.5 shadow-[inset_0_0_0_1px_rgba(187,85,81,0.15)]"
            >
              <span className="mt-[3px] h-1.5 w-1.5 rounded-full shrink-0 bg-error-dim/40 self-start" />
              <span className="text-[10px] font-semibold text-error-dim/70 shrink-0">{f.name}</span>
              <span className="text-[10px] text-on-surface-variant/40 truncate min-w-0 ml-1">{f.error}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
