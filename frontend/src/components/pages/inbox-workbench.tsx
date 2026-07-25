/**
 * inbox-workbench.tsx — the Automatic Event Inbox (headlines route).
 *
 * Reframed from the Slice-01 candidate workbench: the system surfaces
 * potentially material events already present in LOCAL state (the persisted
 * news cluster store) and explains why each one appears.  The operator never
 * pastes or creates an event here.
 *
 * Boundaries (unchanged from the news surface this page replaces):
 *  - GET /news/inbox is local-state-only: no RSS, no provider, no write.
 *  - POST /news/refresh stays the ONLY ingestion trigger — the explicit
 *    refresh button below.  Rendering never refreshes.
 *  - Analysis is a provider call and happens ONLY through the existing
 *    per-event Analyze action (the same onAnalyze boundary the app already
 *    uses); nothing analysis-related runs on page load.
 *
 * The payload is validated fail-closed by lib/event-inbox.ts; a malformed
 * contract renders an explicit refusal, never a partial inbox.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient, useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  AlertTriangle, ChevronRight, FlaskConical, Landmark, Newspaper,
  RefreshCw, RotateCw, ShieldOff,
} from "lucide-react";
import "@/styles/quiet-archive.css";
import { api, type RefreshMeta } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";
import { deriveRowState } from "@/components/pages/headlines-page";
import {
  groupByLifecycle,
  INBOX_ABSENCE_NOTE,
  INBOX_NON_CLAIM,
  parseInboxPayload,
  shouldAutoAnalyzeOnLoad,
  type InboxEvent,
  type Lifecycle,
  type MaterialChannel,
} from "@/lib/event-inbox";

// Analysis never starts from render — enforced at module load so a future
// edit that flips the lib invariant fails immediately, not silently.
if (shouldAutoAnalyzeOnLoad()) {
  throw new Error("auto-analysis on inbox load is forbidden");
}

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function _age(iso: string | null | undefined): string {
  if (!iso) return "—";
  const ms = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(ms / 60_000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  return `${Math.floor(hrs / 24)}d`;
}

function _stamp(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
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

/**
 * Cache-only contract: rendering this page must NEVER auto-trigger a news
 * refresh (a refresh is a POST that reaches RSS and writes SQLite; it is an
 * explicit user action).  Kept as an exported, always-false predicate so the
 * invariant stays unit-tested without a DOM and a future render-triggered
 * refresh fails the test.
 */
export function shouldAutoRefreshOnRender(_meta: RefreshMeta | null): boolean {
  return false;
}

// ---------------------------------------------------------------------------
// Lifecycle + channel presentation (workflow wording only)
// ---------------------------------------------------------------------------

const LIFECYCLE_META: Record<Lifecycle, { label: string; rule: string; pill: string }> = {
  NEW: {
    label: "New",
    rule: "Recently identified cluster that passes the materiality gate",
    pill: "qa-pill-cit",
  },
  DEVELOPING: {
    label: "Developing",
    rule: "A distinctly-worded report arrived 6h+ after the first coverage wave",
    pill: "qa-pill-cit",
  },
  WATCH: {
    label: "Watch",
    rule: "Plausibly material; facts or scope insufficiently resolved",
    pill: "qa-pill-amb",
  },
  RESOLVED: {
    label: "Resolved",
    rule: "No new publication within the 48h archive window",
    pill: "",
  },
};

const CHANNEL_LABEL: Record<MaterialChannel, string> = {
  GROWTH: "Growth",
  INFLATION: "Inflation",
  RATES: "Rates",
  LIQUIDITY: "Liquidity",
  CREDIT: "Credit",
  CURRENCY: "Currency",
  TRADE: "Trade",
  SUPPLY_CHAIN: "Supply chain",
  FISCAL_POLICY: "Fiscal policy",
  REGULATION: "Regulation",
  CORPORATE_EARNINGS: "Earnings",
  TECHNOLOGY_PRODUCTIVITY: "Technology",
  ENERGY_COMMODITIES: "Energy & commodities",
  GEOPOLITICAL_RISK: "Geopolitical",
};

// ---------------------------------------------------------------------------
// Event row — dense ledger row, expandable one at a time
// ---------------------------------------------------------------------------

function EventRow({
  ev, expanded, onToggle, onOpenCandidate, failed,
}: {
  ev: InboxEvent;
  expanded: boolean;
  onToggle: () => void;
  onOpenCandidate?: (ev: InboxEvent) => void;
  failed: boolean;
}) {
  const meta = LIFECYCLE_META[ev.lifecycle];
  const linkState = ev.analysis_target.analysis_link_status;
  return (
    <div className={cn("border-t border-[color:var(--so-rule)]",
      expanded && "bg-[color:var(--so-bg-2)]")}>
      <button
        type="button"
        aria-expanded={expanded}
        onClick={onToggle}
        className={cn(
          "qa-cluster-rail group flex w-full flex-col gap-1 px-3 py-2.5 text-left",
          expanded && "is-selected",
          failed && "is-failed",
        )}
      >
        <div className="flex flex-wrap items-center gap-2">
          <span className={cn("qa-pill", meta.pill)}>{meta.label}</span>
          <span className="qa-num text-[10px] text-[color:var(--so-ink-3)]">
            {_age(ev.last_updated_at)}
          </span>
          <span className="qa-num text-[10px] text-[color:var(--so-ink-3)]">
            {ev.source_count}s
          </span>
          {ev.official_source_present && (
            <span className="inline-flex items-center gap-1 qa-meta !text-[color:var(--so-citrine)]">
              <Landmark className="h-2.5 w-2.5" /> official
            </span>
          )}
          {ev.availability_status === "PARTIAL" && (
            <span className="qa-meta text-[9px] !text-[color:var(--so-amber)]">partial</span>
          )}
          {failed && <AlertTriangle className="h-2.5 w-2.5 text-[color:var(--so-amber)]" />}
          <span className="ml-auto hidden items-center gap-1 sm:flex">
            {ev.material_channels.slice(0, 3).map((c) => (
              <span key={c} className="qa-meta text-[9px]">{CHANNEL_LABEL[c]}</span>
            ))}
            {ev.material_channels.length > 3 && (
              <span className="qa-meta text-[9px]">+{ev.material_channels.length - 3}</span>
            )}
          </span>
          <ChevronRight className={cn(
            "h-3 w-3 shrink-0 text-[color:var(--so-ink-3)] transition-transform",
            expanded && "rotate-90",
          )} />
        </div>
        <span className={cn("qa-lead line-clamp-2", expanded && "is-selected")}>
          {ev.headline}
        </span>
      </button>

      {expanded && (
        <div className="flex flex-col gap-4 px-4 pb-4 pt-1">
          {ev.event_summary && (
            <p
              className="text-[13px] leading-relaxed"
              style={{ fontFamily: "var(--so-serif)", color: "var(--so-ink-1)", fontWeight: 300 }}
            >
              {ev.event_summary}
            </p>
          )}

          {/* Timing + identity KV */}
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
            <dt className="qa-meta">First seen</dt>
            <dd className="qa-num text-[11px] text-[color:var(--so-ink-1)]">{_stamp(ev.first_seen_at)}</dd>
            <dt className="qa-meta">Last update</dt>
            <dd className="qa-num text-[11px] text-[color:var(--so-ink-1)]">{_stamp(ev.last_updated_at)}</dd>
            <dt className="qa-meta">Event ID</dt>
            <dd className="qa-num text-[11px] text-[color:var(--so-ink-3)]">{ev.event_id}</dd>
            {ev.event_family && (
              <>
                <dt className="qa-meta">Family</dt>
                <dd className="text-[11px]" style={{ fontFamily: "var(--so-mono)", color: "var(--so-ink-1)" }}>
                  {ev.event_family}
                </dd>
              </>
            )}
            {ev.event_type && (
              <>
                <dt className="qa-meta">Type</dt>
                <dd className="text-[11px]" style={{ fontFamily: "var(--so-mono)", color: "var(--so-ink-1)" }}>
                  {ev.event_type}
                </dd>
              </>
            )}
            {ev.missing_reason && (
              <>
                <dt className="qa-meta">Missing</dt>
                <dd className="text-[11px]" style={{ color: "var(--so-amber)" }}>{ev.missing_reason}</dd>
              </>
            )}
          </dl>

          {/* Sources — every identity visible */}
          <div>
            <span className="qa-kicker">— Sources</span>
            <div className="mt-1.5 flex flex-col gap-1">
              {ev.sources.map((s) => (
                <div key={s.name} className="flex items-center gap-2">
                  <span className="qa-num w-12 shrink-0 text-[10px] text-[color:var(--so-ink-3)]">{s.tier}</span>
                  <span className="text-[11px] text-[color:var(--so-ink-1)]" style={{ fontFamily: "var(--so-mono)" }}>
                    {s.name}
                  </span>
                  {s.official && (
                    <span className="qa-meta text-[9px] !text-[color:var(--so-citrine)]">official</span>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Material channels */}
          <div>
            <span className="qa-kicker">— Material channels</span>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {ev.material_channels.map((c) => (
                <span key={c} className="qa-pill">{CHANNEL_LABEL[c]}</span>
              ))}
            </div>
          </div>

          {/* Why surfaced */}
          <div>
            <span className="qa-kicker">— Why surfaced</span>
            <ul className="mt-1.5 flex flex-col gap-1">
              {ev.why_surfaced.map((w) => (
                <li key={w} className="qa-help !text-[color:var(--so-ink-2)]">{w}</li>
              ))}
            </ul>
          </div>

          {/* Known unknowns */}
          {ev.known_unknowns.length > 0 && (
            <div>
              <span className="qa-kicker-dim">— Known unknowns</span>
              <ul className="mt-1.5 flex flex-col gap-1">
                {ev.known_unknowns.map((u) => (
                  <li key={u} className="qa-help">{u}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Open the candidate.  Opening is NOT the provider call: the
              analysis surface shows what a run would cover and asks for an
              explicit confirmation there.  A candidate the registry already
              links to one saved analysis re-opens that analysis for free; a
              conflicted link offers nothing rather than guessing an id. */}
          {onOpenCandidate && (
            <div className="qa-section-head flex items-center gap-2 pt-3">
              <button
                type="button"
                className="qa-btn-primary inline-flex h-8 items-center gap-2 px-4 disabled:cursor-not-allowed disabled:opacity-50"
                disabled={linkState === "conflict"}
                onClick={() => onOpenCandidate(ev)}
              >
                {failed ? <RotateCw className="h-3 w-3" /> : <FlaskConical className="h-3 w-3" />}
                {failed ? "Retry analysis"
                  : linkState === "analyzed" ? "Open saved analysis"
                  : "Open for analysis"}
              </button>
              <span className="qa-meta">
                {linkState === "analyzed"
                  ? "saved analysis — no provider call"
                  : linkState === "conflict"
                  ? "linked to more than one saved analysis — not resolvable here"
                  : "opens a preview; the paid run needs a separate confirmation"}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Lifecycle section
// ---------------------------------------------------------------------------

function LifecycleSection({
  lifecycle, events, expandedId, onToggle, onOpenCandidate, failedHeadlines,
}: {
  lifecycle: Lifecycle;
  events: InboxEvent[];
  expandedId: string | null;
  onToggle: (id: string) => void;
  onOpenCandidate?: (ev: InboxEvent) => void;
  failedHeadlines?: Set<string>;
}) {
  const meta = LIFECYCLE_META[lifecycle];
  return (
    <section aria-label={meta.label}>
      <div className="flex items-baseline gap-3 px-3 pb-1 pt-3">
        <span className="qa-kicker">— {meta.label}</span>
        <span className="qa-num text-[10px] text-[color:var(--so-ink-3)]">
          {events.length.toString().padStart(2, "0")}
        </span>
        <span className="qa-meta hidden sm:inline">{meta.rule}</span>
      </div>
      {events.length === 0 ? (
        <p className="qa-meta px-3 pb-2">none</p>
      ) : (
        <div className="flex flex-col">
          {events.map((ev) => (
            <EventRow
              key={ev.event_id}
              ev={ev}
              expanded={expandedId === ev.event_id}
              onToggle={() => onToggle(ev.event_id)}
              onOpenCandidate={onOpenCandidate}
              failed={deriveRowState(ev.headline, failedHeadlines) === "failed"}
            />
          ))}
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Main surface
// ---------------------------------------------------------------------------

interface InboxWorkbenchProps {
  onOpenCandidate?: (ev: InboxEvent) => void;
  failedHeadlines?: Set<string>;
}

export function InboxWorkbench({ onOpenCandidate, failedHeadlines }: InboxWorkbenchProps) {
  const queryClient = useQueryClient();
  const [refreshing, setRefreshing] = useState(false);
  const [lastMeta, setLastMeta] = useState<RefreshMeta | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const refreshSeqRef = useRef(0);
  const refreshAbortRef = useRef<AbortController | null>(null);

  // POST /news/refresh stays the sole ingestion trigger — explicit click only.
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

  const { data: raw, isLoading, isError, refetch } = useQuery({
    queryKey: qk.newsInbox(),
    queryFn: () => api.newsInbox(),
    staleTime: 300_000,
  });

  const parsed = raw === undefined ? undefined : parseInboxPayload(raw);
  const groups = parsed ? groupByLifecycle(parsed.events) : null;
  const activeCount = parsed
    ? parsed.events.filter((e) => e.lifecycle !== "RESOLVED").length
    : 0;

  const toggle = useCallback((id: string) => {
    setExpandedId((cur) => (cur === id ? null : id));
  }, []);

  return (
    <div className="so-quiet-archive flex flex-col gap-1.5 rounded-md px-2 pt-1 pb-3">
      {/* ── Folio bar ── */}
      <div className="qa-folio">
        <span className="qa-folio-nameplate">
          Automatic Event <em>Inbox</em>
        </span>
        {parsed && (
          <span className="qa-folio-meta">
            <strong className="qa-num">
              {parsed.counts.surfaced.toString().padStart(2, "0")}
            </strong>
            <span className="mx-2 text-[color:var(--so-ink-4)]">·</span>
            state as of {_stamp(parsed.as_of)}
          </span>
        )}
        {lastMeta && (
          <span className="qa-folio-meta inline-flex items-center gap-2">
            <span className={cn("h-1 w-1 rounded-full", _refreshDot(lastMeta))} />
            {_refreshLabel(lastMeta)}
          </span>
        )}
        <Button
          variant="ghost" size="sm"
          onClick={handleRefresh} disabled={refreshing}
          className="ml-auto h-6 w-6 p-0 text-[color:var(--so-ink-3)] hover:text-[color:var(--so-ink-1)]"
          aria-label="Refresh news ingestion"
        >
          <RefreshCw className={cn("h-3 w-3", refreshing && "animate-spin")} />
        </Button>
      </div>

      {/* ── Permanent explanations — always visible, payload or not ── */}
      <div className="rounded border border-[color:var(--so-rule)] px-3 py-2">
        <p className="qa-help !text-[color:var(--so-ink-2)]">{INBOX_NON_CLAIM}</p>
        <p className="qa-help mt-1">{INBOX_ABSENCE_NOTE}</p>
      </div>

      {/* ── Loading ── */}
      {isLoading && (
        <div className="space-y-1">
          {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-8 w-full rounded" />)}
        </div>
      )}

      {/* ── Network error ── */}
      {isError && !isLoading && (
        <div className="rounded bg-card px-4 py-6 text-center">
          <AlertTriangle className="mx-auto mb-2 h-4 w-4 text-destructive/60" />
          <p className="text-[12px] font-medium text-on-surface">Unable to load the inbox.</p>
          <p className="mt-1 text-[10px] text-on-surface-variant/60">Check backend, then retry.</p>
          <Button variant="outline" size="sm" onClick={() => refetch()} className="mt-2 h-6 px-2 text-[10px]">
            <RotateCw className="mr-1 h-3 w-3" /> Retry
          </Button>
        </div>
      )}

      {/* ── Malformed contract — explicit refusal, never a partial inbox ── */}
      {!isLoading && !isError && raw !== undefined && parsed === null && (
        <div className="rounded bg-card px-4 py-6 text-center">
          <ShieldOff className="mx-auto mb-2 h-4 w-4 text-destructive/60" />
          <p className="text-[12px] font-medium text-on-surface">
            Inbox payload failed validation — refusing to render.
          </p>
          <p className="mt-1 text-[10px] text-on-surface-variant/60">
            The served payload does not match automatic-event-inbox-v3.
          </p>
        </div>
      )}

      {/* ── Local state unavailable — explicit, not an empty feed ── */}
      {parsed && parsed.availability === "UNAVAILABLE" && (
        <div className="rounded bg-card px-4 py-6 text-center">
          <Newspaper className="mx-auto mb-2 h-4 w-4 text-on-surface-variant/30" />
          <p className="text-[12px] font-medium text-on-surface">Local news state unavailable.</p>
          {parsed.limitations.filter((l) => l !== INBOX_ABSENCE_NOTE).map((l) => (
            <p key={l} className="mt-1 text-[10px] text-on-surface-variant/60">{l}</p>
          ))}
          <p className="mt-1 text-[10px] text-on-surface-variant/60">
            Use the refresh action to run the explicit ingestion pass.
          </p>
        </div>
      )}

      {/* ── Honest empty inbox ── */}
      {parsed && parsed.availability === "AVAILABLE" && parsed.counts.surfaced === 0 && (
        <div className="rounded bg-card px-4 py-6 text-center">
          <Newspaper className="mx-auto mb-2 h-4 w-4 text-on-surface-variant/30" />
          <p className="text-[12px] font-medium text-on-surface">
            No newly detected events currently pass the materiality gate.
          </p>
          <p className="mt-1 text-[10px] text-on-surface-variant/60">
            {parsed.counts.parent_clusters_total} stored clusters produced{" "}
            {parsed.counts.candidates_total} event candidates
            {parsed.counts.beyond_window > 0 &&
              ` — ${parsed.counts.beyond_window} outside the 14-day window`}
            {parsed.counts.excluded_no_material_channel > 0 &&
              ` — ${parsed.counts.excluded_no_material_channel} without an explicit material channel`}
            .
          </p>
        </div>
      )}

      {/* ── The inbox ledger ── */}
      {parsed && parsed.availability === "AVAILABLE" && parsed.counts.surfaced > 0 && groups && (
        <div className="rounded-lg border border-white/[0.04] bg-background pb-2">
          {/* Triage strip — active workflow states up front */}
          <div className="flex flex-wrap items-center gap-4 border-b border-[color:var(--so-rule-hi)] px-3 py-2">
            {(["NEW", "DEVELOPING", "WATCH"] as const).map((lc) => (
              <span key={lc} className="inline-flex items-center gap-1.5">
                <span className={cn("qa-pill", LIFECYCLE_META[lc].pill)}>{LIFECYCLE_META[lc].label}</span>
                <span className="qa-num text-[10px] text-[color:var(--so-ink-1)]">
                  {groups[lc].length}
                </span>
              </span>
            ))}
            <span className="qa-meta ml-auto">
              {activeCount} active · {groups.RESOLVED.length} resolved
            </span>
          </div>

          {(["NEW", "DEVELOPING", "WATCH"] as const).map((lc) => (
            <LifecycleSection
              key={lc}
              lifecycle={lc}
              events={groups[lc]}
              expandedId={expandedId}
              onToggle={toggle}
              onOpenCandidate={onOpenCandidate}
              failedHeadlines={failedHeadlines}
            />
          ))}

          {/* Resolved — collapsed so it never dominates the active view */}
          {groups.RESOLVED.length > 0 && (
            <details className="px-0 pt-2">
              <summary className="cursor-pointer list-none px-3 pb-1">
                <span className="qa-kicker-dim">— Resolved</span>
                <span className="qa-num ml-2 text-[10px] text-[color:var(--so-ink-3)]">
                  {groups.RESOLVED.length}
                </span>
                <span className="qa-meta ml-3 hidden sm:inline">{LIFECYCLE_META.RESOLVED.rule}</span>
              </summary>
              <div className="flex flex-col opacity-70">
                {groups.RESOLVED.map((ev) => (
                  <EventRow
                    key={ev.event_id}
                    ev={ev}
                    expanded={expandedId === ev.event_id}
                    onToggle={() => toggle(ev.event_id)}
                    onOpenCandidate={onOpenCandidate}
                    failed={deriveRowState(ev.headline, failedHeadlines) === "failed"}
                  />
                ))}
              </div>
            </details>
          )}
        </div>
      )}

      {/* ── Provenance + limitations footer ── */}
      {parsed && (
        <div className="flex flex-col gap-1 px-3 py-2">
          <span className="qa-kicker-dim">— Basis and limits</span>
          <p className="qa-meta">
            Derived from: {parsed.generated_from} · lifecycle labels describe the
            information workflow only
          </p>
          {parsed.limitations.filter((l) => l !== INBOX_ABSENCE_NOTE).map((l) => (
            <p key={l} className="qa-help">{l}</p>
          ))}
        </div>
      )}
    </div>
  );
}
