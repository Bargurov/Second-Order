import { useState, useRef, useEffect, useCallback } from "react";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  FlaskConical, Newspaper, Search, Loader2, EyeOff, RefreshCw,
  AlertTriangle, RotateCw, ChevronRight,
  ArrowLeft, Info, ShieldOff, Archive,
} from "lucide-react";
import {
  api,
  type NewsCluster,
  type NewsResponse,
  type RefreshMeta,
  type MacroRelease,
  type PolicyItem,
  type NewsTrend,
  type NewsClusterEvidence,
} from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";
import { buildClusterContext } from "@/lib/cluster-context";
import {
  _getNextPageParam,
  _normalizeNewsPage,
  _sortPolicyItems,
  _splitPolicyVisibility,
  PolicyTimingStrip,
  MacroSurpriseBadge,
  deriveRowState,
} from "@/components/pages/headlines-page";

const PAGE_SIZE = 30;
const _INF_KEY = (limit: number) => ["news", "headlines", "infinite", limit] as const;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _age(iso: string | undefined): string {
  if (!iso) return "";
  const ms = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(ms / 60_000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  return `${Math.floor(hrs / 24)}d`;
}

function _refreshLabel(meta: RefreshMeta): string {
  if (meta.status === "throttled") return "Refresh in progress";
  if (meta.status === "recent") return "Current";
  if (meta.status === "error") return meta.error ?? "Refresh failed";
  if (meta.status === "degraded") {
    const base = meta.error ?? `${meta.fail_feeds ?? 0} feeds failed`;
    const count = meta.created + meta.merged + meta.reused;
    return count > 0 ? `${base} — ${count} clusters` : base;
  }
  if (meta.source === "empty") return "No headlines";
  if (meta.source === "stored" || meta.source === "stored_fallback")
    return `${meta.reused} stored`;
  const parts: string[] = [];
  if (meta.created > 0) parts.push(`${meta.created} new`);
  if (meta.merged > 0) parts.push(`${meta.merged} merged`);
  if (meta.reused > 0) parts.push(`${meta.reused} reused`);
  return parts.join(", ") || "Refreshed";
}

function _refreshDot(meta: RefreshMeta): string {
  if (meta.status === "error") return "bg-destructive";
  if (meta.status === "degraded") return "bg-[#facc15]";
  if (meta.status === "throttled" || meta.status === "recent") return "bg-muted-foreground/40";
  if (meta.new > 0) return "bg-primary";
  return "bg-muted-foreground/40";
}

const _MACRO_LABELS: Record<string, string> = { Unemployment: "U-Rate" };
function _relLabel(d: number): string {
  if (d === 0) return "today";
  if (d === 1) return "tmrw";
  if (d > 1) return `${d}d`;
  if (d === -1) return "yest";
  return `${Math.abs(d)}d ago`;
}

const _POL_LABEL: Record<string, string> = {
  tariff: "Tariff", sanction: "Sanction", regulation: "Rule",
  executive_order: "EO", rate_decision: "Rate",
};

// ---------------------------------------------------------------------------
// Collapsed context drawer — macro, policy, themes in one disclosure
// ---------------------------------------------------------------------------

function ContextDrawer({
  releases, items, trends, onTheme,
}: {
  releases: MacroRelease[];
  items: PolicyItem[];
  trends: NewsTrend[];
  onTheme: (t: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const visRelease = releases.filter((r) => r.status !== "past");
  const sorted = _sortPolicyItems(items);
  const hasMacro = visRelease.length > 0;
  const hasPolicy = sorted.length > 0;
  const hasTrends = trends.length > 0;
  if (!hasMacro && !hasPolicy && !hasTrends) return null;

  const summary = [
    hasMacro && `${visRelease.length} macro`,
    hasPolicy && `${sorted.length} policy`,
    hasTrends && `${trends.length} themes`,
  ].filter(Boolean).join(" · ");

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="group flex w-full items-center gap-2 rounded bg-surface-container-low/50 px-3 py-1.5 text-left transition-colors hover:bg-surface-container-low"
      >
        <ChevronRight className={cn("h-3 w-3 text-on-surface-variant/40 transition-transform", open && "rotate-90")} />
        <span className="text-[9px] font-bold uppercase tracking-[0.12em] text-on-surface-variant/45">Context</span>
        <span className="text-[10px] text-on-surface-variant/40">{summary}</span>
      </button>

      {open && (
        <div className="mt-1.5 flex flex-col gap-2 rounded bg-surface-container-low/30 px-3 py-2.5">
          {/* Macro releases */}
          {hasMacro && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[9px] font-bold uppercase tracking-[0.1em] text-on-surface-variant/40">Macro</span>
              {visRelease.map((r) => {
                const up = r.status === "upcoming" || r.status === "today";
                return (
                  <span key={`${r.name}-${r.release_date}`} className={cn(
                    "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px]",
                    up ? "bg-primary/[0.06] text-foreground/70" : "text-muted-foreground/40",
                  )}>
                    {r.status === "today" && <span className="h-1 w-1 rounded-full bg-primary" />}
                    <span className="font-medium">{_MACRO_LABELS[r.name] ?? r.name}</span>
                    <span className="font-num tabular-nums opacity-60">{_relLabel(r.days_until)}</span>
                  </span>
                );
              })}
            </div>
          )}

          {/* Policy items */}
          {hasPolicy && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[9px] font-bold uppercase tracking-[0.1em] text-on-surface-variant/40">Policy</span>
              {sorted.slice(0, 5).map((p) => (
                <span key={`${p.policy_type}-${p.name}`} className="inline-flex items-center gap-1 text-[10px] text-on-surface-variant/60">
                  <span className="font-semibold uppercase tracking-wide text-[9px]">{_POL_LABEL[p.policy_type] ?? p.policy_type}</span>
                  <span className="max-w-[120px] truncate">{p.name}</span>
                </span>
              ))}
              {sorted.length > 5 && <span className="text-[10px] text-on-surface-variant/30">+{sorted.length - 5}</span>}
            </div>
          )}

          {/* Trending themes */}
          {hasTrends && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[9px] font-bold uppercase tracking-[0.1em] text-on-surface-variant/40">Themes</span>
              {trends.map((t) => (
                <button key={t.headline} onClick={() => { onTheme(t.headline.split(/\s+/).slice(0, 4).join(" ")); setOpen(false); }}
                  className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-primary/60 hover:text-primary hover:bg-primary/[0.04] transition-colors">
                  <span className="max-w-[140px] truncate font-medium">{t.headline}</span>
                  <span className="font-num tabular-nums opacity-60">{t.source_count}s</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stream card
// ---------------------------------------------------------------------------

function StreamCard({
  c, selected, onSelect, muted, failed,
}: {
  c: NewsCluster;
  selected: boolean;
  onSelect: () => void;
  muted?: boolean;
  failed?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "group relative flex w-full flex-col gap-0.5 px-3 py-2 text-left transition-colors",
        "border-l-[3px]",
        selected
          ? "border-l-primary bg-primary/[0.08]"
          : failed
            ? "border-l-destructive/30 hover:bg-white/[0.02]"
            : "border-l-transparent hover:bg-white/[0.02]",
        muted && "opacity-40",
      )}
    >
      <div className="flex items-center gap-1.5">
        <span className="font-num text-[9px] tabular-nums text-muted-foreground/40">{_age(c.published_at)}</span>
        <span className={cn(
          "font-num text-[9px] font-bold tabular-nums",
          c.source_count >= 5 ? "text-primary/70" : c.source_count >= 3 ? "text-foreground/50" : "text-muted-foreground/30",
        )}>
          {c.source_count}s
        </span>
        {c.agreement === "mixed" && <span className="text-[8px] font-bold uppercase tracking-wider text-destructive/50">mix</span>}
        {c.low_signal && <span className="text-[8px] font-bold uppercase tracking-wider text-muted-foreground/30">low</span>}
        {failed && <AlertTriangle className="h-2.5 w-2.5 text-destructive/50" />}
      </div>
      <span className="text-[11.5px] leading-snug text-foreground/90 line-clamp-2">{c.headline}</span>
      {(c.macro_surprise || c.policy_timing) && (
        <div className="flex items-center gap-1 pt-0.5">
          {c.policy_timing && <PolicyTimingStrip block={c.policy_timing} />}
          {c.macro_surprise && <MacroSurpriseBadge block={c.macro_surprise} />}
        </div>
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Worksheet field rows (disabled skeleton for deferred fields)
// ---------------------------------------------------------------------------

const _WORKSHEET_FIELDS = [
  { key: "mechanism_family", label: "Mechanism Family", mono: true },
  { key: "primary_ticker", label: "Primary Ticker", mono: true },
  { key: "benchmark_ticker", label: "Benchmark Ticker", mono: true },
  { key: "market_relevance", label: "Market Relevance", mono: false },
  { key: "hypothesis", label: "Hypothesis", mono: false },
  { key: "falsifier", label: "Falsifier", mono: false },
] as const;

function WorksheetSkeleton() {
  return (
    <div className="flex flex-col gap-0">
      <div className="flex items-center gap-2 pb-2">
        <span className="text-[9px] font-bold uppercase tracking-[0.12em] text-on-surface-variant/45">Candidate Worksheet</span>
        <span className="rounded-full bg-on-surface-variant/8 px-2 py-px text-[8px] font-semibold uppercase tracking-wider text-on-surface-variant/30">Deferred</span>
      </div>
      {_WORKSHEET_FIELDS.map((f) => (
        <div key={f.key} className="flex items-center gap-3 border-t border-white/[0.03] py-2">
          <span className={cn(
            "w-[120px] shrink-0 text-[10px] uppercase tracking-[0.04em] text-on-surface-variant/35",
            f.mono ? "font-mono" : "font-medium",
          )}>
            {f.key}
          </span>
          <div className="h-[22px] flex-1 rounded bg-white/[0.02] border border-dashed border-white/[0.04]" />
        </div>
      ))}
      <p className="pt-2 text-[9.5px] leading-relaxed text-on-surface-variant/30">
        Worksheet fields require candidate_id propagation through clustered /news; deferred in Slice 01.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Desk — selected cluster detail + worksheet
// ---------------------------------------------------------------------------

function DeskIdle() {
  return (
    <div className="flex h-full min-h-[400px] flex-col items-center justify-center px-8">
      <div className="text-center">
        <div className="mx-auto mb-4 flex h-10 w-10 items-center justify-center rounded-lg bg-white/[0.02]">
          <Newspaper className="h-4 w-4 text-on-surface-variant/20" />
        </div>
        <p className="font-headline text-[14px] font-semibold text-on-surface/60">No cluster selected</p>
        <p className="mt-1.5 max-w-[240px] text-[11px] leading-relaxed text-on-surface-variant/40">
          Select a cluster from the stream to populate the desk with headline context, evidence, and worksheet fields.
        </p>
      </div>
    </div>
  );
}

function DeskPanel({
  cluster, onAnalyze, failed, onSkip,
}: {
  cluster: NewsCluster;
  onAnalyze?: (headline: string, opts?: { eventId?: number; context?: string }) => void;
  failed: boolean;
  onSkip: () => void;
}) {
  const con = cluster.consensus;
  const evidence: NewsClusterEvidence[] | undefined = cluster.evidence;

  return (
    <div className="flex flex-col gap-0 overflow-y-auto" style={{ maxHeight: "calc(100dvh - 140px)" }}>
      {/* Desk header */}
      <div className="border-b border-white/[0.04] px-5 py-4">
        <div className="flex items-center gap-2 pb-2">
          <span className="text-[9px] font-bold uppercase tracking-[0.12em] text-primary/60">Candidate Desk</span>
          <span className="text-on-surface-variant/15">·</span>
          <span className="font-num text-[10px] tabular-nums text-muted-foreground/40">
            {cluster.source_count} source{cluster.source_count !== 1 ? "s" : ""}
            {cluster.agreement ? ` · ${cluster.agreement}` : ""}
          </span>
        </div>

        <h3 className="font-headline text-[18px] font-bold leading-tight tracking-[-0.015em] text-foreground">
          {cluster.headline}
        </h3>

        {/* Source tier chips — compact inline */}
        <div className="mt-2.5 flex flex-wrap items-center gap-1">
          {cluster.sources.slice(0, 4).map((s) => (
            <span key={s.name} className={cn(
              "inline-flex items-center gap-1 rounded px-1.5 py-px text-[9.5px]",
              s.tier === "T1" ? "bg-primary/[0.06] text-primary/70" : "text-muted-foreground/50",
            )}>
              {s.tier && <span className="font-num text-[8px] font-bold opacity-50">{s.tier}</span>}
              {s.name}
            </span>
          ))}
          {cluster.sources.length > 4 && (
            <span className="text-[9px] text-muted-foreground/30">+{cluster.sources.length - 4}</span>
          )}
        </div>

        {/* Enrichment badges */}
        {(cluster.macro_surprise || cluster.policy_timing) && (
          <div className="mt-2 flex items-center gap-1.5">
            {cluster.policy_timing && <PolicyTimingStrip block={cluster.policy_timing} />}
            {cluster.macro_surprise && <MacroSurpriseBadge block={cluster.macro_surprise} />}
          </div>
        )}
      </div>

      {/* Desk body — scrollable content */}
      <div className="flex flex-col gap-4 px-5 py-4">
        {/* Summary */}
        {cluster.summary && (
          <div>
            <span className="text-[9px] font-bold uppercase tracking-[0.12em] text-on-surface-variant/40">Summary</span>
            <p className="mt-1 text-[12.5px] leading-relaxed text-on-surface/80">{cluster.summary}</p>
          </div>
        )}

        {/* Consensus KV */}
        {con && Object.keys(con).length > 0 && (
          <div>
            <span className="text-[9px] font-bold uppercase tracking-[0.12em] text-on-surface-variant/40">Consensus</span>
            <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
              {(["actors", "action", "sector", "geography", "uncertainty"] as const).map((k) => {
                const v = con[k];
                if (!v) return null;
                return (
                  <div key={k} className="contents">
                    <dt className="text-[10px] font-semibold uppercase tracking-[0.06em] text-on-surface-variant/40">{k}</dt>
                    <dd className="text-[11px] text-on-surface/70">{String(v)}</dd>
                  </div>
                );
              })}
            </dl>
          </div>
        )}

        {/* Evidence — compact */}
        {evidence && evidence.length > 0 && (
          <div>
            <span className="text-[9px] font-bold uppercase tracking-[0.12em] text-on-surface-variant/40">Evidence</span>
            <div className="mt-1 flex flex-col gap-1">
              {evidence.map((e, i) => (
                <div key={i} className="flex items-start gap-2 py-1">
                  <span className={cn(
                    "mt-0.5 shrink-0 font-num text-[9px] font-bold",
                    e.tier === "T1" ? "text-primary/60" : "text-muted-foreground/35",
                  )}>
                    {e.tier ?? "—"}
                  </span>
                  <div className="min-w-0 flex-1">
                    <span className="text-[10px] font-semibold text-on-surface-variant/60">{e.source}</span>
                    {e.note && <span className="ml-1.5 text-[9px] italic text-destructive/40">{e.note}</span>}
                    <p className="text-[10.5px] leading-snug text-on-surface/60">{e.title}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Worksheet skeleton — the visual signature of the desk */}
        <div className="border-t border-white/[0.04] pt-4">
          <WorksheetSkeleton />
        </div>

        {/* Actions — pinned feel */}
        <div className="flex items-center gap-2 border-t border-white/[0.04] pt-3">
          {onAnalyze && (
            <Button
              size="sm"
              className="h-7 gap-1.5 rounded bg-primary/[0.12] px-3 text-[11px] font-semibold text-primary hover:bg-primary/20 border border-primary/20"
              onClick={() => onAnalyze(cluster.headline, { context: buildClusterContext(cluster) })}
            >
              {failed ? <RotateCw className="h-3 w-3" /> : <FlaskConical className="h-3 w-3" />}
              {failed ? "Retry" : "Analyze"}
            </Button>
          )}
          <Button variant="ghost" size="sm" className="h-7 px-2 text-[10px] text-muted-foreground/50 hover:text-muted-foreground" onClick={onSkip}>
            Skip
          </Button>
          <Button variant="ghost" size="sm" disabled className="ml-auto h-7 gap-1 px-2 text-[9px] text-on-surface-variant/25 cursor-not-allowed"
            title="Staging from UI requires backend support. Use CLI: scripts/">
            <Archive className="h-3 w-3" />
            Stage
          </Button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dossier — tight metadata + workflow status
// ---------------------------------------------------------------------------

function DossierPanel({ cluster }: { cluster: NewsCluster }) {
  const [srcOpen, setSrcOpen] = useState(false);
  return (
    <div className="flex flex-col gap-0 overflow-y-auto px-4 py-3" style={{ maxHeight: "calc(100dvh - 140px)" }}>
      {/* Cluster metadata KV */}
      <div className="pb-3">
        <span className="text-[9px] font-bold uppercase tracking-[0.12em] text-on-surface-variant/40">Cluster Metadata</span>
        <dl className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
          <dt className="text-[9px] font-semibold uppercase tracking-[0.06em] text-on-surface-variant/35">Sources</dt>
          <dd className="font-num text-[10px] tabular-nums text-on-surface/70">{cluster.source_count}</dd>

          <dt className="text-[9px] font-semibold uppercase tracking-[0.06em] text-on-surface-variant/35">Agreement</dt>
          <dd className={cn("text-[10px]", cluster.agreement === "mixed" ? "text-destructive/60" : "text-on-surface/70")}>
            {cluster.agreement ?? "—"}
          </dd>

          <dt className="text-[9px] font-semibold uppercase tracking-[0.06em] text-on-surface-variant/35">Published</dt>
          <dd className="font-num text-[10px] tabular-nums text-on-surface/70">
            {cluster.published_at ? new Date(cluster.published_at).toLocaleString(undefined, {
              month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
            }) : "—"}
          </dd>

          <dt className="text-[9px] font-semibold uppercase tracking-[0.06em] text-on-surface-variant/35">Candidate ID</dt>
          <dd className="font-num text-[10px] tabular-nums text-on-surface-variant/25">— deferred</dd>

          <dt className="text-[9px] font-semibold uppercase tracking-[0.06em] text-on-surface-variant/35">Artifact</dt>
          <dd className="text-[10px] text-on-surface-variant/25">— not staged</dd>
        </dl>
      </div>

      {/* Source list — collapsed by default */}
      <div className="border-t border-white/[0.03] py-2.5">
        <button type="button" onClick={() => setSrcOpen((o) => !o)}
          className="flex w-full items-center gap-1.5 text-left">
          <ChevronRight className={cn("h-2.5 w-2.5 text-on-surface-variant/30 transition-transform", srcOpen && "rotate-90")} />
          <span className="text-[9px] font-bold uppercase tracking-[0.12em] text-on-surface-variant/35">Sources</span>
          <span className="font-num text-[9px] tabular-nums text-on-surface-variant/25">{cluster.sources.length}</span>
        </button>
        {srcOpen && (
          <div className="mt-1.5 flex flex-col gap-0.5 pl-4">
            {cluster.sources.map((s) => (
              <div key={s.name} className="flex items-center gap-1.5">
                <span className={cn("font-num text-[9px] font-bold", s.tier === "T1" ? "text-primary/50" : "text-muted-foreground/25")}>{s.tier ?? "—"}</span>
                <span className="text-[10px] text-on-surface/50">{s.name}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Workflow status panels — compact */}
      <div className="flex flex-col gap-2 border-t border-white/[0.03] pt-2.5">
        <div className="flex items-start gap-2">
          <Info className="mt-0.5 h-3 w-3 shrink-0 text-primary/30" />
          <div>
            <span className="text-[9px] font-bold uppercase tracking-[0.06em] text-primary/45">Staging</span>
            <p className="text-[9.5px] leading-relaxed text-on-surface-variant/40">
              Artifact workflow remains CLI-only. Writes land in artifacts/staging/ when backend support is added.
            </p>
          </div>
        </div>

        <div className="flex items-start gap-2">
          <ShieldOff className="mt-0.5 h-3 w-3 shrink-0 text-on-surface-variant/20" />
          <div>
            <span className="text-[9px] font-bold uppercase tracking-[0.06em] text-on-surface-variant/30">Gate Preview</span>
            <p className="text-[9.5px] leading-relaxed text-on-surface-variant/40">
              Not run from UI in Slice 01. Use CLI gate diagnostic.
            </p>
          </div>
        </div>
      </div>

      {/* Held ≠ rejected */}
      <div className="border-t border-white/[0.03] pt-2.5 mt-2">
        <p className="text-[9.5px] leading-relaxed text-on-surface-variant/35">
          <span className="font-semibold text-on-surface-variant/50">Held ≠ rejected.</span>{" "}
          A held candidate stays in the inbox. The gate identifies candidates that need more evidence — it does not discard.
        </p>
      </div>
    </div>
  );
}

function DossierIdle() {
  return (
    <div className="flex flex-col gap-3 px-4 py-3">
      <span className="text-[9px] font-bold uppercase tracking-[0.12em] text-on-surface-variant/30">Dossier</span>
      <p className="text-[10px] text-on-surface-variant/25">Select a cluster.</p>

      <div className="flex flex-col gap-2 pt-1">
        <div className="flex items-start gap-2">
          <Info className="mt-0.5 h-3 w-3 shrink-0 text-primary/20" />
          <p className="text-[9.5px] leading-relaxed text-on-surface-variant/25">
            <span className="font-semibold text-primary/30">Staging.</span> Artifact writes land in artifacts/staging/.
          </p>
        </div>
        <div className="flex items-start gap-2">
          <ShieldOff className="mt-0.5 h-3 w-3 shrink-0 text-on-surface-variant/15" />
          <p className="text-[9.5px] leading-relaxed text-on-surface-variant/25">
            <span className="font-semibold text-on-surface-variant/30">Gate.</span> CLI-only in Slice 01.
          </p>
        </div>
      </div>

      <div className="border-t border-white/[0.02] pt-2">
        <p className="text-[9.5px] text-on-surface-variant/20">
          <span className="font-semibold text-on-surface-variant/30">Held ≠ rejected.</span>{" "}
          Held candidates stay in the inbox.
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Inbox Workbench
// ---------------------------------------------------------------------------

interface InboxWorkbenchProps {
  onAnalyze?: (headline: string, opts?: { eventId?: number; context?: string }) => void;
  failedHeadlines?: Set<string>;
}

export function InboxWorkbench({ onAnalyze, failedHeadlines }: InboxWorkbenchProps) {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [showLowSignal, setShowLowSignal] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [lastMeta, setLastMeta] = useState<RefreshMeta | null>(null);
  const [selectedHeadline, setSelectedHeadline] = useState<string | null>(null);
  const [mobileDesk, setMobileDesk] = useState(false);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const refreshSeqRef = useRef(0);
  const refreshAbortRef = useRef<AbortController | null>(null);

  const handleRefresh = useCallback(async () => {
    refreshAbortRef.current?.abort();
    const ctrl = new AbortController();
    refreshAbortRef.current = ctrl;
    const seq = ++refreshSeqRef.current;
    setRefreshing(true);
    try {
      const res = await api.newsRefresh(ctrl.signal);
      if (seq !== refreshSeqRef.current) return;
      const meta = res.refresh_meta;
      if (meta) {
        setLastMeta(meta);
        if (meta.status === "ok" || meta.status === "recent") {
          queryClient.invalidateQueries({ queryKey: ["news"] });
        }
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      if (seq !== refreshSeqRef.current) return;
      setLastMeta((prev) =>
        prev ? { ...prev, status: "error", freshness: "stale", error: "Network error" } : null,
      );
    } finally {
      if (seq === refreshSeqRef.current) setRefreshing(false);
    }
  }, [queryClient]);

  useEffect(() => {
    return () => { refreshAbortRef.current?.abort(); };
  }, []);

  const { data: trendsData } = useQuery({
    queryKey: qk.newsTrends(),
    queryFn: () => api.newsTrends(),
    staleTime: 300_000,
  });
  const trends = trendsData ?? [];

  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading, isError } = useInfiniteQuery({
    queryKey: _INF_KEY(PAGE_SIZE),
    queryFn: async ({ pageParam }: { pageParam: string | undefined }) => {
      const raw = await api.news(PAGE_SIZE, pageParam);
      return _normalizeNewsPage(raw);
    },
    getNextPageParam: _getNextPageParam,
    initialPageParam: undefined as string | undefined,
    staleTime: 300_000,
  });

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => { if (entries[0]?.isIntersecting && hasNextPage && !isFetchingNextPage) fetchNextPage(); },
      { rootMargin: "200px" },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  const pages: NewsResponse[] = Array.isArray(data?.pages)
    ? data.pages.map((page) => _normalizeNewsPage(page))
    : [];
  const firstPage = pages[0];
  const allClusters: NewsCluster[] = pages.flatMap((p) => p?.clusters ?? []);
  const totalCount = firstPage?.total_count ?? 0;
  const effectiveMeta = lastMeta ?? firstPage?.refresh_meta ?? null;
  const macroReleases = firstPage?.macro_releases ?? [];
  const policyItems = firstPage?.policy_items ?? [];

  const autoRefreshedRef = useRef(false);
  useEffect(() => {
    if (autoRefreshedRef.current || refreshing || !effectiveMeta) return;
    const f = effectiveMeta.freshness;
    if (f === "stale" || f === "degraded") {
      autoRefreshedRef.current = true;
      handleRefresh();
    }
  }, [effectiveMeta, refreshing, handleRefresh]);

  useEffect(() => {
    if (selectedHeadline && !allClusters.find((c) => c.headline === selectedHeadline)) {
      setSelectedHeadline(null);
      setMobileDesk(false);
    }
  }, [selectedHeadline, allClusters]);

  const searchLower = search.toLowerCase().trim();
  const filtered = searchLower
    ? allClusters.filter((c) => c.headline.toLowerCase().includes(searchLower))
    : allClusters;
  const normal = filtered.filter((c) => !c.low_signal);
  const lowSignal = filtered.filter((c) => c.low_signal);

  const selected = selectedHeadline
    ? allClusters.find((c) => c.headline === selectedHeadline) ?? null
    : null;

  const handleSelect = useCallback((headline: string) => {
    setSelectedHeadline(headline);
    setMobileDesk(true);
  }, []);

  const handleSkip = useCallback(() => {
    setSelectedHeadline(null);
    setMobileDesk(false);
  }, []);

  return (
    <div className="flex flex-col gap-1.5">
      {/* ── Compact header row ── */}
      <div className="flex items-center gap-2">
        <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary/50" />
        <span className="text-[9px] font-bold uppercase tracking-[0.1em] text-primary/55">Staging</span>
        <span className="text-on-surface-variant/15">|</span>
        <h2 className="font-headline text-[15px] font-bold tracking-[-0.02em] text-foreground">Inbox Workbench</h2>
        <Badge variant="outline" className="font-num text-[9px] py-0 px-1.5 h-[18px]">{totalCount}</Badge>

        {/* Refresh status inline */}
        {effectiveMeta && (
          <div className="flex items-center gap-1.5 text-[9px] text-muted-foreground/50">
            <span className={cn("h-1 w-1 rounded-full", _refreshDot(effectiveMeta))} />
            <span>{_refreshLabel(effectiveMeta)}</span>
          </div>
        )}

        <Button
          variant="ghost" size="sm"
          onClick={handleRefresh} disabled={refreshing}
          className="ml-auto h-6 w-6 p-0 text-muted-foreground/40 hover:text-muted-foreground"
        >
          <RefreshCw className={cn("h-3 w-3", refreshing && "animate-spin")} />
        </Button>
      </div>

      {/* ── Context drawer — collapsed by default ── */}
      <ContextDrawer releases={macroReleases} items={policyItems} trends={trends} onTheme={(t) => setSearch(t)} />

      {/* ── Loading ── */}
      {isLoading && (
        <div className="space-y-1">
          {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-8 w-full rounded" />)}
        </div>
      )}

      {/* ── Error ── */}
      {isError && !isLoading && allClusters.length === 0 && (
        <div className="rounded bg-card px-4 py-6 text-center">
          <AlertTriangle className="mx-auto mb-2 h-4 w-4 text-destructive/60" />
          <p className="text-[12px] font-medium text-on-surface">Unable to load headlines.</p>
          <p className="mt-1 text-[10px] text-on-surface-variant/60">Check backend, then refresh.</p>
          <Button variant="outline" size="sm" onClick={handleRefresh} disabled={refreshing} className="mt-2 h-6 px-2 text-[10px]">
            <RotateCw className={cn("mr-1 h-3 w-3", refreshing && "animate-spin")} /> Retry
          </Button>
        </div>
      )}

      {/* ── Empty ── */}
      {!isLoading && !isError && allClusters.length === 0 && (
        <div className="rounded bg-card px-4 py-6 text-center">
          <Newspaper className="mx-auto mb-2 h-4 w-4 text-on-surface-variant/30" />
          <p className="text-[12px] font-medium text-on-surface">No headlines available.</p>
          <p className="mt-1 text-[10px] text-on-surface-variant/60">Try refreshing.</p>
        </div>
      )}

      {/* ══════════════════════════════════════════════════════════════════
          THREE-ZONE WORKBENCH GRID
          Zone separation via tonal layering:
            Stream  = bg-background  (#0a0a0f — darkest)
            Desk    = bg-card        (#13131a — section surface)
            Dossier = bg-surface-container (#191922 — between)
         ═══════════════════════════════════════════════════════════════ */}
      {!isLoading && allClusters.length > 0 && (
        <div className="grid gap-0 lg:grid-cols-[280px_1fr_300px] rounded-lg overflow-hidden border border-white/[0.04]">

          {/* ── STREAM ── */}
          <div className={cn(
            "flex flex-col bg-background",
            mobileDesk && "hidden lg:flex",
          )}>
            {/* Zone header */}
            <div className="flex flex-col gap-1.5 px-3 pb-1.5 pt-2.5">
              <div className="flex items-center gap-2">
                <span className="text-[9px] font-bold uppercase tracking-[0.12em] text-on-surface-variant/40">Stream</span>
                <span className="font-num text-[9px] tabular-nums text-muted-foreground/25">{filtered.length}</span>
                {lowSignal.length > 0 && (
                  <button type="button" onClick={() => setShowLowSignal((s) => !s)}
                    className="ml-auto flex items-center gap-1 text-[8px] text-muted-foreground/30 hover:text-muted-foreground/50">
                    <EyeOff className="h-2.5 w-2.5" />
                    {showLowSignal ? "Hide" : "+"}{lowSignal.length} low
                  </button>
                )}
              </div>
              <div className="relative">
                <Search className="absolute left-2 top-1/2 h-2.5 w-2.5 -translate-y-1/2 text-muted-foreground/30" />
                <input
                  type="text"
                  placeholder="Filter…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="w-full rounded border border-white/[0.04] bg-white/[0.02] py-1 pl-6 pr-2 text-[10px] text-foreground placeholder:text-foreground/20 focus:outline-none focus:ring-1 focus:ring-primary/30"
                />
              </div>
            </div>

            {/* Stream list */}
            <div className="flex flex-col gap-0 overflow-y-auto" style={{ maxHeight: "calc(100dvh - 200px)" }}>
              {normal.map((c) => (
                <StreamCard
                  key={c.headline}
                  c={c}
                  selected={c.headline === selectedHeadline}
                  onSelect={() => handleSelect(c.headline)}
                  failed={deriveRowState(c.headline, failedHeadlines) === "failed"}
                />
              ))}
              {showLowSignal && lowSignal.length > 0 && (
                <>
                  <div className="px-3 pt-2 pb-0.5">
                    <span className="text-[8px] font-bold uppercase tracking-[0.12em] text-muted-foreground/20">Low Signal</span>
                  </div>
                  {lowSignal.map((c) => (
                    <StreamCard
                      key={c.headline}
                      c={c}
                      selected={c.headline === selectedHeadline}
                      onSelect={() => handleSelect(c.headline)}
                      muted
                      failed={deriveRowState(c.headline, failedHeadlines) === "failed"}
                    />
                  ))}
                </>
              )}
              <div ref={sentinelRef} className="py-1.5 text-center">
                {isFetchingNextPage && (
                  <div className="flex items-center justify-center gap-1 text-[9px] text-muted-foreground/30">
                    <Loader2 className="h-2.5 w-2.5 animate-spin" /> Loading
                  </div>
                )}
                {!hasNextPage && allClusters.length > 0 && (
                  <span className="text-[9px] text-muted-foreground/20">
                    {allClusters.length}/{totalCount}
                  </span>
                )}
              </div>
            </div>
          </div>

          {/* ── DESK ── */}
          <div className={cn(
            "min-h-[420px] bg-card",
            !mobileDesk && !selected && "hidden lg:block",
            mobileDesk && "block",
            !mobileDesk && selected && "hidden lg:block",
          )}>
            {mobileDesk && (
              <button type="button" onClick={() => { setMobileDesk(false); setSelectedHeadline(null); }}
                className="flex items-center gap-1.5 px-4 pt-2.5 text-[10px] text-primary/60 hover:text-primary lg:hidden">
                <ArrowLeft className="h-3 w-3" /> Stream
              </button>
            )}
            {selected ? (
              <DeskPanel
                cluster={selected}
                onAnalyze={onAnalyze}
                failed={deriveRowState(selected.headline, failedHeadlines) === "failed"}
                onSkip={handleSkip}
              />
            ) : (
              <DeskIdle />
            )}
          </div>

          {/* ── DOSSIER ── */}
          <div className={cn(
            "hidden lg:block bg-surface-container",
            !selected && "opacity-50",
          )}>
            {selected ? <DossierPanel cluster={selected} /> : <DossierIdle />}
          </div>
        </div>
      )}
    </div>
  );
}
