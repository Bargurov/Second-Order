import type { IfPersists } from "@/lib/api";
import { TrendingUp, TrendingDown, Clock, Zap } from "lucide-react";

/** True when the if_persists object has at least one usable field. */
export function hasIfPersistsContent(data: IfPersists | undefined | null): boolean {
  if (!data) return false;
  const { substitution, delayed_winners, delayed_losers } = data;
  const hasSub = !!substitution && substitution !== "null" && substitution !== "None";
  const hasWin = !!delayed_winners && delayed_winners.length > 0;
  const hasLos = !!delayed_losers && delayed_losers.length > 0;
  return hasSub || hasWin || hasLos;
}

// ---------------------------------------------------------------------------
// Full "If This Persists" — Stitch pill style
// ---------------------------------------------------------------------------

export function IfPersistsSection({ data }: { data: IfPersists | undefined }) {
  if (!data) return null;

  if (!hasIfPersistsContent(data)) {
    return (
      <p className="text-[11px] text-on-surface-variant italic">
        No credible second-round effects identified for this event.
      </p>
    );
  }

  const { substitution, delayed_winners, delayed_losers, horizon } = data;
  const hasSub = !!substitution && substitution !== "null" && substitution !== "None";
  const hasWin = !!delayed_winners && delayed_winners.length > 0;
  const hasLos = !!delayed_losers && delayed_losers.length > 0;

  return (
    <div className="space-y-4">
      {hasSub && (
        <p className="text-xs text-on-surface-variant leading-relaxed">{substitution}</p>
      )}
      <div className="flex flex-wrap gap-3">
        {hasWin && delayed_winners!.map((w, i) => (
          <div key={`w-${i}`} className="bg-primary-container/20 px-4 py-2 rounded-full flex items-center gap-2 border border-primary/20">
            <span className="text-xs font-bold text-primary">{w}</span>
            <Zap className="h-3 w-3 text-primary" />
          </div>
        ))}
        {hasLos && delayed_losers!.map((l, i) => (
          <div key={`l-${i}`} className="bg-error-container/10 px-4 py-2 rounded-full flex items-center gap-2 border border-error-dim/20">
            <span className="text-xs font-bold text-error-dim">{l}</span>
            <TrendingDown className="h-3 w-3 text-error-dim" />
          </div>
        ))}
      </div>
      {horizon && (
        <div className="flex items-center gap-2 text-[10px] text-on-surface-variant">
          <Clock className="h-3 w-3" />
          Horizon: <span className="font-bold text-on-surface">{horizon}</span>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Compact version — for Market Mover cards
// ---------------------------------------------------------------------------

export function IfPersistsCompact({ data }: { data: IfPersists | undefined }) {
  if (!data || !hasIfPersistsContent(data)) return null;
  const { substitution, horizon } = data;
  const hasSub = !!substitution && substitution !== "null" && substitution !== "None";
  if (!hasSub) return null;

  const truncated = substitution!.length > 100
    ? substitution!.slice(0, 97) + "..."
    : substitution!;

  return (
    <div className="text-[10px] text-on-surface-variant">
      <span className="font-bold uppercase tracking-wide text-[9px] text-on-surface-variant">If persists</span>
      {horizon && <span className="text-[9px] text-on-surface-variant/60"> ({horizon})</span>}
      <span className="mx-1 text-outline-variant">|</span>
      {truncated}
    </div>
  );
}
