import { useState, useRef, useEffect, useCallback } from "react";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  FlaskConical, Newspaper, Search, Loader2, EyeOff, RefreshCw, AlertTriangle, RotateCw, CalendarClock, Scale, TrendingUp, ChevronDown,
} from "lucide-react";
import { api, type ClusterMacroSurprise, type NewsCluster, type NewsResponse, type RefreshMeta, type MacroRelease, type PolicyItem, type PolicyTiming, type PolicyTimingStatus, type NewsTrend } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";
import { buildClusterContext } from "@/lib/cluster-context";

const PAGE_SIZE = 30;
const headlinesInfiniteKey = (limit: number) => ["news", "headlines", "infinite", limit] as const;

/**
 * Pure pagination helper — extracted so the contract is unit-testable.
 *
 * The backend issues an opaque `next_cursor` string with each page; when
 * the field is null/missing there are no more pages.  Undefined means
 * "stop fetching" to `useInfiniteQuery`.  Guards against:
 *   - `lastPage` being undefined (malformed/failed fetch) → terminate
 *   - `allPages` being undefined / empty (early-mount race) → terminate
 *   - empty-string cursor → terminate (treat as no more pages)
 *
 * The helper accepts the second `allPages` argument because TanStack Query
 * passes it positionally; making it explicit (and guarding it) keeps any
 * future maintainer who reaches for `pages.length` from re-introducing
 * the crash this PR fixes.
 */
export function _getNextPageParam(
  lastPage: NewsResponse | undefined,
  allPages?: Array<NewsResponse | undefined> | null,
): string | undefined {
  // When TanStack passes `allPages` it is contractually a non-empty
  // array (it always contains at least the page we just received).  If
  // a caller hands us something else (null, an object, an empty array
  // from a re-mount race), terminate rather than crash on a future
  // ``pages.length`` access.  Direct unit-test callers omit `allPages`
  // entirely; in that case we fall through to the cursor check.
  if (allPages !== undefined && (!Array.isArray(allPages) || allPages.length === 0)) {
    return undefined;
  }
  const next = lastPage?.next_cursor;
  if (next === null || next === undefined || next === "") return undefined;
  return next;
}

/**
 * Normalise a raw `/news` response into a defensive {@link NewsResponse}
 * shape.  The backend contract is well-typed, but treating every
 * downstream read as "the field is here and well-formed" has bitten us
 * when:
 *   - a degraded backend returns `clusters: undefined`
 *   - a JSON parse anomaly drops `total_count` / `total_headlines`
 *   - `next_cursor` arrives as an empty string instead of null
 *
 * The helper is total (never throws), shape-stable (always returns
 * `clusters: []` not `undefined`), and idempotent — feeding a valid page
 * back through it produces an equivalent page.  Used inside the
 * `useInfiniteQuery` queryFn so every entry in `data.pages` carries the
 * same minimal structure regardless of the wire payload.
 */
export function _normalizeNewsPage(raw: unknown): NewsResponse {
  const r = (raw && typeof raw === "object" ? raw : {}) as Partial<NewsResponse>;
  const cursor = r.next_cursor;
  return {
    clusters: Array.isArray(r.clusters) ? r.clusters : [],
    next_cursor:
      typeof cursor === "string" && cursor.length > 0 ? cursor : null,
    total_headlines: typeof r.total_headlines === "number" ? r.total_headlines : 0,
    total_count:     typeof r.total_count     === "number" ? r.total_count     : 0,
    feed_status:     Array.isArray(r.feed_status) ? r.feed_status : [],
    refresh_meta:    r.refresh_meta,
    macro_releases:  Array.isArray(r.macro_releases) ? r.macro_releases : [],
    policy_items:    Array.isArray(r.policy_items)   ? r.policy_items   : [],
    data_quality:    r.data_quality,
    degraded_fields: Array.isArray(r.degraded_fields) ? r.degraded_fields : undefined,
    _schema_version: r._schema_version,
  };
}

// ---------------------------------------------------------------------------
// Macro calendar strip
// ---------------------------------------------------------------------------

const _MACRO_LABELS: Record<string, string> = {
  Unemployment: "U-Rate",
};

function _relativeLabel(days: number): string {
  if (days === 0) return "Today";
  if (days === 1) return "Tomorrow";
  if (days > 1) return `in ${days}d`;
  if (days === -1) return "Yesterday";
  return `${Math.abs(days)}d ago`;
}

function MacroReleaseChip({ r }: { r: MacroRelease }) {
  const upcoming = r.status === "upcoming" || r.status === "today";
  const label = _MACRO_LABELS[r.name] ?? r.name;

  return (
    <div className={cn(
      "flex items-center gap-2 rounded px-2.5 py-1.5 shrink-0 border",
      upcoming
        ? "bg-[#242533] border-[#93d1d3]/20"
        : "bg-[#13131a] border-border/20 opacity-55",
    )}>
      <span className={cn(
        "h-1.5 w-1.5 rounded-full shrink-0",
        r.status === "today" ? "bg-[#93d1d3]"
          : upcoming ? "bg-[#93d1d3]/50"
          : "bg-muted-foreground/30",
      )} />
      <span className="text-[11px] font-semibold text-foreground/80 tracking-tight">{label}</span>
      <span className="text-[10px] text-muted-foreground/55">{r.period}</span>
      <span className={cn(
        "text-[10px] font-num shrink-0 tabular-nums",
        r.status === "today" ? "text-[#93d1d3]"
          : upcoming ? "text-[#93d1d3]/65"
          : "text-muted-foreground/45",
      )}>
        {_relativeLabel(r.days_until)}
      </span>
    </div>
  );
}

function MacroCalendarStrip({ releases }: { releases: MacroRelease[] }) {
  // Show today + upcoming + recent; omit past (> 2 days ago)
  const visible = releases.filter((r) => r.status !== "past");
  if (visible.length === 0) return null;

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground/50 uppercase tracking-widest">
        <CalendarClock className="h-3 w-3" />
        <span>Macro Calendar</span>
      </div>
      <div className="flex gap-1.5 overflow-x-auto pb-0.5 scrollbar-none">
        {visible.map((r) => (
          <MacroReleaseChip key={`${r.name}-${r.release_date}`} r={r} />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Policy tracker — compact section with a top-N list and expandable overflow.
// Renders one row per item: type · region · title · status.  Type controls a
// muted accent stripe so tariff / sanction / rule / rate items remain
// visually distinct without bucketing into separate sub-sections.
// ---------------------------------------------------------------------------

const _POLICY_TYPE_LABEL: Record<string, string> = {
  tariff:          "Tariff",
  sanction:        "Sanction",
  regulation:      "Rule",
  executive_order: "EO",
  rate_decision:   "Rate",
};

/** Per-type label tone — drives the small uppercase TYPE kicker on each
 *  row.  Mirrors the extracted design package's editorial palette:
 *  tariff & sanction share coral (restrictive), rate is teal (monetary),
 *  EO is amber (watch), regulation is neutral. */
const _POLICY_TYPE_LABEL_TONE: Record<string, string> = {
  tariff:          "text-[#ee7d77]",
  sanction:        "text-[#ee7d77]",
  rate_decision:   "text-[#93d1d3]",
  executive_order: "text-[#facc15]/85",
  regulation:      "text-on-surface-variant/75",
};

/** Per-type left-edge accent stripe — full-height vertical bar that
 *  reads the policy type at a glance.  Same hue family as the type
 *  label tone but at a slightly higher opacity so the stripe carries
 *  even when the row is dense.  Mirrors the design's "muted accents"
 *  brief: the bar is felt, not loud. */
const _POLICY_TYPE_STRIPE: Record<string, string> = {
  tariff:          "bg-[#ee7d77]/55",
  sanction:        "bg-[#ee7d77]/55",
  rate_decision:   "bg-[#93d1d3]/55",
  executive_order: "bg-[#facc15]/45",
  regulation:      "bg-on-surface-variant/30",
};

/** Status bucket — collapses the back-end status enum into the three
 *  user-facing pill words (ACTIVE / REVIEW / EXPIRED).  ``revisit_due``,
 *  ``pre_effective``, and ``announced`` all read as REVIEW because each
 *  requires a deliberate read against the live tape; the timing hint on
 *  the pill text differentiates their urgency. */
type _PolicyBucket = "active" | "review" | "expired";

const _POLICY_STATUS_BUCKET: Record<string, _PolicyBucket> = {
  active:        "active",
  revisit_due:   "review",
  pre_effective: "review",
  announced:     "review",
  past:          "expired",
};

/** Compact pill tone per bucket — quiet by design.  ACTIVE is barely a
 *  chip so a row of mostly-active policies doesn't read as repeated
 *  noise; REVIEW carries the only saturated accent so the eye lands on
 *  the action item; EXPIRED is a ghost outline. */
const _POLICY_PILL_TONE: Record<_PolicyBucket, string> = {
  active:  "bg-white/[0.04] text-on-surface-variant/80",
  review:  "bg-[#ee7d77]/12 text-[#f4a8a4]",
  expired: "text-on-surface-variant/45 ring-1 ring-inset ring-white/[0.05]",
};

/** Status priority — drives sort order and the right-side status pill tone.
 *  revisit_due (urgent ask) ranks first, then live/imminent, then heads-up. */
const _STATUS_PRIORITY: Record<PolicyItem["status"], number> = {
  revisit_due:   0,
  active:        1,
  pre_effective: 2,
  announced:     3,
  past:          99,
};

const _DEFAULT_VISIBLE = 4;

/** Pure helper — strip past items and sort by status priority then by
 *  proximity (days_until ASC for non-revisit; days_until_revisit ASC for
 *  revisit items).  Exported for unit tests. */
export function _sortPolicyItems(items: PolicyItem[]): PolicyItem[] {
  const live = items.filter((i) => i.status !== "past");
  return live.slice().sort((a, b) => {
    const pa = _STATUS_PRIORITY[a.status];
    const pb = _STATUS_PRIORITY[b.status];
    if (pa !== pb) return pa - pb;
    const aProx = a.status === "revisit_due" ? a.days_until_revisit : a.days_until;
    const bProx = b.status === "revisit_due" ? b.days_until_revisit : b.days_until;
    return aProx - bProx;
  });
}

/** Pure visibility split — top-N visible always, the rest hidden behind
 *  the expandable area.  When ``expanded`` is true the entire list is
 *  visible.  Exported for unit tests. */
export function _splitPolicyVisibility(
  items: PolicyItem[],
  expanded: boolean,
  visibleCount: number = _DEFAULT_VISIBLE,
): { visible: PolicyItem[]; hidden: PolicyItem[] } {
  if (expanded) return { visible: items, hidden: [] };
  return {
    visible: items.slice(0, visibleCount),
    hidden:  items.slice(visibleCount),
  };
}

function _bucketLabelFor(item: PolicyItem): string {
  // Map the back-end status to one of the three user-facing pill words
  // (ACTIVE / REVIEW / EXPIRED).  Layers a short timing hint on REVIEW
  // rows so the user can read urgency without inspecting the row body —
  // "Review · 2d" / "Review · today".  ACTIVE and EXPIRED are calm.
  const bucket = _POLICY_STATUS_BUCKET[item.status] ?? "active";
  if (bucket === "active")  return "Active";
  if (bucket === "expired") return "Expired";
  // bucket === "review"
  const d = item.status === "revisit_due"
    ? item.days_until_revisit
    : item.days_until;
  if (d <= 0) return "Review · today";
  if (d === 1) return "Review · 1d";
  return `Review · ${d}d`;
}

// Card chrome class — matches design/extracted/styles.css ``.card``:
// section background (#13131a), 8px radius, 18px 20px padding.
const _POLICY_CARD = "rounded-lg bg-surface-container-low px-5 py-4";

// Card-title class — matches design ``.card .card-title``: Manrope 600,
// 12.5px, ink-2, 0.08em letter-spacing, UPPERCASE, 14px bottom margin.
const _POLICY_CARD_TITLE =
  "font-headline text-[12.5px] font-semibold uppercase tracking-[0.08em] text-on-surface-variant";

// Inter-row separator — matches design ``--line``: rgba(255,255,255,0.055).
const _POLICY_ROW_SEP = "border-white/[0.055]";

function PolicyItemRow({ item, isLast }: { item: PolicyItem; isLast: boolean }) {
  const typeLabel = _POLICY_TYPE_LABEL[item.policy_type] ?? item.policy_type;
  const typeTone = _POLICY_TYPE_LABEL_TONE[item.policy_type] ?? "text-on-surface-variant/75";
  const stripeTone = _POLICY_TYPE_STRIPE[item.policy_type] ?? "bg-on-surface-variant/30";
  const bucket = _POLICY_STATUS_BUCKET[item.status] ?? "active";
  const pillTone = _POLICY_PILL_TONE[bucket];

  return (
    // Compact policy row — full-width, two-line layout:
    //   left: type-tinted vertical accent stripe (felt, not loud)
    //   centre: TYPE · REGION kicker + truncated short title
    //   right: compact, quiet status pill (ACTIVE / REVIEW / EXPIRED)
    // No hover-only tooltip drives the read; the visible kicker, title,
    // and status pill carry the whole primary meaning.
    <div
      className={cn(
        "relative flex w-full items-center gap-3 py-2.5 pl-3 pr-1",
        !isLast && cn("border-b", _POLICY_ROW_SEP),
      )}
    >
      {/* Left accent stripe — full row height; carries the policy type. */}
      <span
        aria-hidden
        className={cn(
          "absolute left-0 top-1.5 bottom-1.5 w-[2px] rounded-r-sm",
          stripeTone,
        )}
      />

      {/* Body — TYPE · REGION kicker, then short title */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className={cn(
            "text-[11px] font-semibold uppercase tracking-[0.1em]",
            typeTone,
          )}>
            {typeLabel}
          </span>
          <span className="text-on-surface-variant/30">·</span>
          <span className="font-mono text-[11px] uppercase tracking-[0.04em] text-on-surface-variant/55">
            {item.jurisdiction}
          </span>
        </div>
        <p className="mt-0.5 truncate text-[12.5px] leading-snug text-on-surface">
          {item.name}
        </p>
      </div>

      {/* Status pill — design ``.pill``: 2px 9px padding, fully rounded,
          11px text, weight 500, nowrap.  Quiet by tone (ACTIVE = barely
          a chip, REVIEW = single saturated accent, EXPIRED = ghost). */}
      <span className={cn(
        "shrink-0 inline-flex items-center rounded-full px-2.5 py-[2px]",
        "text-[11px] font-medium uppercase tracking-[0.08em] whitespace-nowrap",
        pillTone,
      )}>
        {_bucketLabelFor(item)}
      </span>
    </div>
  );
}

function PolicyTrackerStrip({ items }: { items: PolicyItem[] }) {
  const sorted = _sortPolicyItems(items);
  const [expanded, setExpanded] = useState(false);
  if (sorted.length === 0) return null;

  const { visible, hidden } = _splitPolicyVisibility(sorted, expanded);

  return (
    // Card wrapper from design/extracted/screens/market.jsx — same chrome
    // the design uses for the editorial Highlights list, repurposed here
    // for the Policy Tracker.  Trending Themes and other sections sit
    // visually separate below this card.
    <section
      data-testid="policy-tracker"
      className={_POLICY_CARD}
    >
      <div className="mb-3.5 flex items-baseline gap-2">
        <Scale className="h-3 w-3 text-on-surface-variant/55 self-center" />
        <h3 className={_POLICY_CARD_TITLE}>
          POLICY TRACKER
        </h3>
        <span className="ml-auto font-mono text-[11px] tabular-nums text-on-surface-variant/45">
          {sorted.length} active
        </span>
      </div>

      {/* highlights-list — design ``.highlights-list`` is a flex column
          with 2px gap; the per-row 1px ghost-border supplies the visual
          separation, not the gap. */}
      <div className="flex flex-col">
        {visible.map((item, idx) => {
          const isLast = idx === visible.length - 1 && hidden.length === 0;
          return (
            <PolicyItemRow
              key={`${item.policy_type}-${item.effective_date}-${item.name}`}
              item={item}
              isLast={isLast}
            />
          );
        })}
      </div>

      {hidden.length > 0 && !expanded && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="mt-2 flex w-full items-center justify-between rounded-md bg-white/[0.018] px-3 py-2 text-[11px] font-medium text-on-surface-variant/70 transition-colors hover:bg-white/[0.03] hover:text-on-surface"
        >
          <span className="inline-flex items-center gap-1.5">
            <ChevronDown className="h-3 w-3" />
            View all policies
          </span>
          <span className="font-mono tabular-nums text-on-surface-variant/55">+{hidden.length}</span>
        </button>
      )}

      {expanded && sorted.length > _DEFAULT_VISIBLE && (
        <button
          type="button"
          onClick={() => setExpanded(false)}
          className="mt-2 flex w-full items-center gap-1.5 rounded-md bg-white/[0.018] px-3 py-2 text-[11px] font-medium text-on-surface-variant/70 transition-colors hover:bg-white/[0.03] hover:text-on-surface"
        >
          <ChevronDown className="h-3 w-3 rotate-180" />
          Collapse
        </button>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Trending themes strip
// ---------------------------------------------------------------------------

function _trendSearchTerm(headline: string): string {
  return headline.split(/\s+/).slice(0, 4).join(" ");
}

function TrendingThemesStrip({
  trends,
  onSelect,
}: {
  trends: NewsTrend[];
  onSelect: (term: string) => void;
}) {
  if (trends.length === 0) return null;

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground/50 uppercase tracking-widest">
        <TrendingUp className="h-3 w-3" />
        <span>Trending Themes</span>
      </div>
      <div className="flex gap-1.5 overflow-x-auto pb-0.5 scrollbar-none">
        {trends.map((t) => (
          <button
            key={t.headline}
            onClick={() => onSelect(_trendSearchTerm(t.headline))}
            title={t.headline}
            className={cn(
              "flex items-center gap-1.5 rounded px-2.5 py-1.5 shrink-0 border",
              "bg-[#242533] border-[#93d1d3]/15 hover:border-[#93d1d3]/35 transition-colors",
            )}
          >
            <span className="h-1.5 w-1.5 rounded-full shrink-0 bg-[#93d1d3]/50" />
            <span className="text-[11px] font-semibold text-foreground/80 max-w-[200px] truncate">
              {t.headline}
            </span>
            <span className="text-[10px] font-num tabular-nums text-[#93d1d3]/60 shrink-0">
              {t.source_count}s
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Cluster-level macro surprise badge
// ---------------------------------------------------------------------------

const _MACRO_SURPRISE_LABEL: Record<string, string> = {
  beat:    "Beat",
  miss:    "Miss",
  in_line: "In line",
  unknown: "Print",
};

const _MACRO_SURPRISE_COLOR: Record<string, string> = {
  beat:    "border-[#93d1d3]/35 bg-[#93d1d3]/10 text-[#93d1d3]",
  miss:    "border-[#ee7d77]/35 bg-[#ee7d77]/10 text-[#ee7d77]",
  in_line: "border-border/40 bg-secondary/40 text-foreground/65",
  unknown: "border-border/40 bg-secondary/40 text-muted-foreground",
};

function _fmtNum(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  if (abs >= 1000) return value.toLocaleString();
  if (Number.isInteger(value)) return value.toString();
  return value.toFixed(2);
}

// ---------------------------------------------------------------------------
// Per-row policy timing strip
// ---------------------------------------------------------------------------

const _POLICY_TIMING_LABEL: Record<PolicyTimingStatus, string> = {
  announced:    "Announced",
  effective:    "Effective",
  under_review: "Under Review",
  expired:      "Expired",
};

// Announced vs effective must read as visually distinct states — teal for
// future-dated policy (anticipation), coral for in-force (material impact
// priced in), muted yellow for active review, dimmed neutral for expired.
const _POLICY_TIMING_STYLE: Record<PolicyTimingStatus, {
  border: string; bg: string; text: string; dot: string;
}> = {
  announced: {
    border: "border-[#93d1d3]/35",
    bg:     "bg-[#93d1d3]/10",
    text:   "text-[#93d1d3]",
    dot:    "bg-[#93d1d3]",
  },
  effective: {
    border: "border-[#ee7d77]/35",
    bg:     "bg-[#ee7d77]/10",
    text:   "text-[#ee7d77]",
    dot:    "bg-[#ee7d77]",
  },
  under_review: {
    border: "border-[#facc15]/30",
    bg:     "bg-[#facc15]/8",
    text:   "text-[#facc15]/85",
    dot:    "bg-[#facc15]/80",
  },
  expired: {
    border: "border-border/40",
    bg:     "bg-secondary/40",
    text:   "text-muted-foreground/55",
    dot:    "bg-muted-foreground/40",
  },
};

/**
 * Compact per-row policy-timing strip.  Rendered ONLY when the cluster
 * carries a ``policy_timing`` block (deterministic backend match); an
 * unmatched headline leaves this slot empty so the row shape stays
 * identical to before.  Announced vs effective carry different accent
 * colours so the two states read as visually distinct at a glance.
 */
export function PolicyTimingStrip({ block }: { block: PolicyTiming }) {
  const style = _POLICY_TIMING_STYLE[block.status]
    ?? _POLICY_TIMING_STYLE.announced;
  const label = _POLICY_TIMING_LABEL[block.status] ?? block.status;

  // Emphasise the key date for the status: announced → when it kicks
  // in; effective / under_review → when the review lands; expired →
  // when the review closed.
  const keyDateLabel =
    block.status === "announced"   ? `effective ${block.effective_date}`
    : block.status === "effective" ? `review ${block.review_date}`
    : block.status === "under_review" ? `review ${block.review_date}`
    : `review ${block.review_date}`;

  const tooltip = [
    `announced ${block.announced_date}`,
    `effective ${block.effective_date}`,
    `review ${block.review_date}`,
    `source ${block.source}`,
  ].join(" · ");

  return (
    <span
      title={tooltip}
      className={cn(
        "shrink-0 inline-flex items-center gap-1.5 rounded-full border px-2 py-[2px]",
        "text-[9px] font-bold uppercase tracking-wider",
        style.border, style.bg, style.text,
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full shrink-0", style.dot)} />
      <span>{label}</span>
      <span className="font-num tabular-nums normal-case font-medium opacity-75">
        {keyDateLabel}
      </span>
      <span className="normal-case font-medium opacity-60">
        · {block.source}
      </span>
    </span>
  );
}


export function MacroSurpriseBadge({ block }: { block: ClusterMacroSurprise }) {
  const label = block.surprise_label ?? "unknown";
  const text = _MACRO_SURPRISE_LABEL[label] ?? "Print";
  const color = _MACRO_SURPRISE_COLOR[label] ?? _MACRO_SURPRISE_COLOR.unknown;
  const priorDisplay =
    block.revised_prior !== null && block.revised_prior !== undefined
      ? `${_fmtNum(block.prior)} → ${_fmtNum(block.revised_prior)}`
      : _fmtNum(block.prior);

  const tooltip = [
    `actual ${_fmtNum(block.actual)}`,
    `consensus ${_fmtNum(block.consensus)}`,
    `prior ${priorDisplay}`,
    block.source ? `source ${block.source}` : "",
  ].filter(Boolean).join(" · ");

  return (
    <span
      title={tooltip}
      className={cn(
        "shrink-0 inline-flex items-center gap-1 rounded-full border px-2 py-[2px] text-[9px] font-bold uppercase tracking-wider",
        color,
      )}
    >
      <span>{text}</span>
      <span className="font-num tabular-nums normal-case font-medium opacity-80">
        {_fmtNum(block.actual)} / {_fmtNum(block.consensus)}
      </span>
      {block.revised_prior !== null && block.revised_prior !== undefined && (
        <span className="font-num tabular-nums normal-case font-medium opacity-65">
          (rev {_fmtNum(block.revised_prior)})
        </span>
      )}
    </span>
  );
}


// ---------------------------------------------------------------------------
// Headline row
// ---------------------------------------------------------------------------

/**
 * Derive the row action state from the headline's failure status.
 *
 * Exported for tests — pure function, no React dependencies.
 */
export type HeadlineRowState = "normal" | "failed";

export function deriveRowState(
  headline: string,
  failedHeadlines?: Set<string>,
): HeadlineRowState {
  if (failedHeadlines?.has(headline)) return "failed";
  return "normal";
}

function HeadlineRow({
  c, onAnalyze, muted, failed,
}: {
  c: NewsCluster;
  onAnalyze?: (headline: string, opts?: { eventId?: number; context?: string }) => void;
  muted?: boolean;
  failed?: boolean;
}) {
  return (
    <div
      className={cn(
        "group flex items-center gap-3 rounded-lg border bg-card px-3 py-2 transition-colors",
        failed
          ? "border-error-dim/20 hover:border-error-dim/40"
          : "border-border hover:border-foreground/15",
        muted && "opacity-50",
      )}
    >
      <span className={cn(
        "flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-bold font-num border",
        c.source_count >= 5 && "border-emerald-500/40 bg-emerald-950/30 text-emerald-400",
        c.source_count >= 3 && c.source_count < 5 && "border-gray-500/40 bg-gray-900/30 text-gray-400",
        c.source_count < 3 && "border-border bg-secondary/60 text-muted-foreground",
      )}>
        {c.source_count}
      </span>
      <span className="min-w-0 flex-1 text-[13px] font-medium leading-snug text-foreground line-clamp-2">
        {c.headline}
      </span>
      {c.policy_timing && <PolicyTimingStrip block={c.policy_timing} />}
      {c.macro_surprise && <MacroSurpriseBadge block={c.macro_surprise} />}
      {failed && (
        <span className="shrink-0 flex items-center gap-1 text-[9px] font-bold text-error-dim/70">
          <AlertTriangle className="h-3 w-3" />
          <span className="hidden sm:inline">Failed</span>
        </span>
      )}
      {onAnalyze && (
        <Button
          variant="ghost"
          size="sm"
          className={cn(
            "shrink-0 transition-opacity text-muted-foreground hover:text-foreground",
            !failed && "opacity-0 group-hover:opacity-100",
          )}
          onClick={() => onAnalyze(c.headline, { context: buildClusterContext(c) })}
        >
          {failed ? (
            <>
              <RotateCw className="h-3 w-3" />
              <span className="hidden sm:inline ml-1">Retry</span>
            </>
          ) : (
            <>
              <FlaskConical className="h-3 w-3" />
              <span className="hidden sm:inline ml-1">Analyze</span>
            </>
          )}
        </Button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Headlines page
// ---------------------------------------------------------------------------

interface HeadlinesPageProps {
  onAnalyze?: (headline: string, opts?: { eventId?: number; context?: string }) => void;
  /** Headlines whose analysis returned failed/mock — hidden for this session. */
  failedHeadlines?: Set<string>;
}

function _refreshLabel(meta: RefreshMeta): string {
  if (meta.status === "throttled") return "Refresh in progress — try again shortly";
  if (meta.status === "recent") return "Already refreshed — data is current";
  if (meta.status === "error")
    return meta.error ?? "Refresh failed — showing last known data";
  if (meta.status === "degraded") {
    const base = meta.error ?? `${meta.fail_feeds ?? 0} feeds failed`;
    const count = meta.created + meta.merged + meta.reused;
    return count > 0 ? `${base} — ${count} clusters available` : base;
  }
  if (meta.source === "empty") return "No headlines found";
  if (meta.source === "stored" || meta.source === "stored_fallback")
    return `${meta.reused} stored cluster${meta.reused !== 1 ? "s" : ""} reused — nothing new`;
  // incremental or full_recluster
  const parts: string[] = [];
  if (meta.created > 0) parts.push(`${meta.created} new`);
  if (meta.merged > 0) parts.push(`${meta.merged} merged`);
  if (meta.reused > 0) parts.push(`${meta.reused} reused`);
  return parts.join(", ") || "Refreshed";
}

function _refreshDotClass(meta: RefreshMeta): string {
  if (meta.status === "error") return "bg-destructive";
  if (meta.status === "degraded") return "bg-[#facc15]";
  if (meta.status === "throttled" || meta.status === "recent") return "bg-muted-foreground/40";
  if (meta.new > 0) return "bg-primary";
  return "bg-muted-foreground/40";
}

export function HeadlinesPage({ onAnalyze, failedHeadlines }: HeadlinesPageProps) {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [showLowSignal, setShowLowSignal] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [lastMeta, setLastMeta] = useState<RefreshMeta | null>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);

  // Monotonic counter + AbortController: prevents out-of-order responses
  // from overwriting newer state, and cancels in-flight requests on
  // unmount or when a newer refresh supersedes.
  const refreshSeqRef = useRef(0);
  const refreshAbortRef = useRef<AbortController | null>(null);

  const handleRefresh = useCallback(async () => {
    // Abort any in-flight refresh before starting a new one
    refreshAbortRef.current?.abort();
    const ctrl = new AbortController();
    refreshAbortRef.current = ctrl;

    const seq = ++refreshSeqRef.current;
    setRefreshing(true);
    try {
      const res = await api.newsRefresh(ctrl.signal);
      if (seq !== refreshSeqRef.current) return; // stale response — discard
      const meta = res.refresh_meta;
      if (meta) {
        setLastMeta(meta);
        // Only invalidate the query cache when the refresh actually
        // produced a successful payload — avoids blanking the cluster
        // list during degraded/error transitions.
        if (meta.status === "ok" || meta.status === "recent") {
          queryClient.invalidateQueries({ queryKey: ["news"] });
        }
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return; // silent
      if (seq !== refreshSeqRef.current) return;
      // Network failure: keep the last good meta visible, just mark status
      setLastMeta((prev) =>
        prev ? { ...prev, status: "error", freshness: "stale", error: "Network error" } : null,
      );
    } finally {
      if (seq === refreshSeqRef.current) setRefreshing(false);
    }
  }, [queryClient]);

  // Abort in-flight refresh on unmount
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
    queryKey: headlinesInfiniteKey(PAGE_SIZE),
    // Always resolve to a normalised NewsResponse shape — even if the
    // backend returns a partial / degraded payload — so downstream
    // ``data.pages`` reads can rely on `clusters` / `total_count` /
    // `next_cursor` being present.  Network/HTTP errors still propagate
    // (api.news throws an ApiError) and surface via `isError`.
    queryFn: async ({ pageParam }: { pageParam: string | undefined }) => {
      const raw = await api.news(PAGE_SIZE, pageParam);
      return _normalizeNewsPage(raw);
    },
    getNextPageParam: _getNextPageParam,
    initialPageParam: undefined as string | undefined,
    staleTime: 300_000,
  });

  // IntersectionObserver for infinite scroll
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

  // Defensive page-array unwrap.  `data` can be undefined (initial mount
  // before the first fetch resolves), `data.pages` is contractually a
  // TPage[] in TanStack v5 but we still belt-and-brace in case a stale
  // cache slot returns something else, and each page is normalised by
  // ``_normalizeNewsPage`` so per-cluster reads never see undefined.
  const pages: NewsResponse[] = Array.isArray(data?.pages)
    ? data.pages.map((page) => _normalizeNewsPage(page))
    : [];
  const firstPage: NewsResponse | undefined = pages[0];
  const allClusters: NewsCluster[] = pages.flatMap((p) => p?.clusters ?? []);
  const totalCount = firstPage?.total_count ?? 0;
  // Effective refresh metadata: prefer the manual-refresh result, fall back
  // to the initial page load's refresh_meta so the status shows on cold start.
  const effectiveMeta = lastMeta ?? firstPage?.refresh_meta ?? null;
  // Macro releases come from the first page (static calendar data, same on every page)
  const macroReleases = firstPage?.macro_releases ?? [];
  const policyItems   = firstPage?.policy_items   ?? [];

  // Auto-refresh once on page load when news data is stale or degraded.
  const autoRefreshedRef = useRef(false);
  useEffect(() => {
    if (autoRefreshedRef.current || refreshing || !effectiveMeta) return;
    const f = effectiveMeta.freshness;
    if (f === "stale" || f === "degraded") {
      autoRefreshedRef.current = true;
      handleRefresh();
    }
  }, [effectiveMeta, refreshing, handleRefresh]);

  // Client-side search filter — failed headlines stay visible (inline state)
  const searchLower = search.toLowerCase().trim();
  const filtered = searchLower
    ? allClusters.filter((c) => c.headline.toLowerCase().includes(searchLower))
    : allClusters;

  const normal = filtered.filter((c) => !c.low_signal);
  const lowSignal = filtered.filter((c) => c.low_signal);
  const loadedCount = allClusters.length;

  return (
    // Page-level scroll: shell scrolls the document; this page is plain
    // flow.  Removed `h-full` + nested `overflow-auto` so the layout no
    // longer creates an inner scroll container.
    <div className="flex flex-col gap-3">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3">
        <Newspaper className="h-4 w-4 text-muted-foreground" />
        <h2 className="text-lg font-semibold tracking-[-0.02em] text-foreground">Live Headlines</h2>
        <Badge variant="outline" className="font-num text-[10px]">{totalCount} clusters</Badge>
        <Button
          variant="ghost"
          size="sm"
          onClick={handleRefresh}
          disabled={refreshing}
          className="ml-auto h-7 px-2 text-[10px] text-muted-foreground"
        >
          <RefreshCw className={cn("h-3 w-3 mr-1", refreshing && "animate-spin")} />
          Refresh
        </Button>
      </div>

      {/* Refresh status — shown on initial load (from GET /news) and after manual refresh */}
      {effectiveMeta && (
        <div className={cn(
          "flex items-center gap-2 text-[10px]",
          effectiveMeta.status === "error" ? "text-destructive/80" :
          effectiveMeta.status === "degraded" ? "text-[#facc15]/80" :
          "text-muted-foreground/70",
        )}>
          <span className={cn("inline-block w-1.5 h-1.5 rounded-full shrink-0", _refreshDotClass(effectiveMeta))} />
          <span>{_refreshLabel(effectiveMeta)}</span>
          {effectiveMeta.last_successful_refresh && (
            <span className="text-muted-foreground/40 ml-1">
              · as of {new Date(effectiveMeta.last_successful_refresh).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
            </span>
          )}
        </div>
      )}

      {/* Macro calendar strip */}
      {macroReleases.length > 0 && <MacroCalendarStrip releases={macroReleases} />}

      {/* Policy tracker strip */}
      {policyItems.length > 0 && <PolicyTrackerStrip items={policyItems} />}

      {/* Trending themes */}
      {trends.length > 0 && (
        <TrendingThemesStrip trends={trends} onSelect={(term) => setSearch(term)} />
      )}

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
        <input
          type="text"
          placeholder="Filter headlines..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full rounded-lg border border-input bg-background pl-9 pr-3 py-2 text-[13px] text-foreground placeholder:text-foreground/40 focus:outline-none focus:ring-1 focus:ring-ring"
        />
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="space-y-1.5">
          {Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-10 w-full rounded-lg" />)}
        </div>
      )}

      {/* Error fallback — query failed and no cached data */}
      {isError && !isLoading && allClusters.length === 0 && (
        <div className="rounded-lg bg-card px-4 py-8 text-center">
          <AlertTriangle className="mx-auto mb-2 h-5 w-5 text-destructive/70" />
          <p className="text-[13px] font-medium text-on-surface">Unable to load headlines.</p>
          <p className="mt-1 text-[11px] text-on-surface-variant/70">
            Check that the backend is running, then refresh.
          </p>
          <Button
            variant="outline"
            size="sm"
            onClick={handleRefresh}
            disabled={refreshing}
            className="mt-3 h-7 px-3 text-[11px]"
          >
            <RotateCw className={cn("mr-1 h-3 w-3", refreshing && "animate-spin")} />
            Retry
          </Button>
        </div>
      )}

      {/* Empty fallback — successful load but no clusters returned. Keeps
          the page rendering a stable surface instead of an empty grid. */}
      {!isLoading && !isError && allClusters.length === 0 && (
        <div className="rounded-lg bg-card px-4 py-8 text-center">
          <Newspaper className="mx-auto mb-2 h-5 w-5 text-on-surface-variant/45" />
          <p className="text-[13px] font-medium text-on-surface">No headlines available.</p>
          <p className="mt-1 text-[11px] text-on-surface-variant/70">
            The feed returned no clusters — try refreshing in a moment.
          </p>
        </div>
      )}

      {/* Headlines grid */}
      {!isLoading && (
        <>
          {/* Low-signal toggle */}
          {lowSignal.length > 0 && (
            <div className="flex justify-end">
              <button
                onClick={() => setShowLowSignal((s) => !s)}
                className="flex items-center gap-1 text-[10px] text-muted-foreground/60 hover:text-muted-foreground transition-colors"
              >
                <EyeOff className="h-3 w-3" />
                {showLowSignal ? "Hide" : "Show"} {lowSignal.length} low-signal
              </button>
            </div>
          )}

          <div className="fade-in grid gap-1.5 xl:grid-cols-2">
            {normal.map((c) => (
              <HeadlineRow
                key={c.headline}
                c={c}
                onAnalyze={onAnalyze}
                failed={deriveRowState(c.headline, failedHeadlines) === "failed"}
              />
            ))}
          </div>

          {showLowSignal && lowSignal.length > 0 && (
            <div className="space-y-1.5 pt-1">
              <span className="text-[10px] text-muted-foreground/50 uppercase tracking-widest">Low signal</span>
              <div className="grid gap-1.5 xl:grid-cols-2">
                {lowSignal.map((c) => (
                  <HeadlineRow
                    key={c.headline}
                    c={c}
                    onAnalyze={onAnalyze}
                    muted
                    failed={deriveRowState(c.headline, failedHeadlines) === "failed"}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Sentinel + bottom status */}
          <div ref={sentinelRef} className="py-3 text-center">
            {isFetchingNextPage && (
              <div className="flex items-center justify-center gap-2 text-[11px] text-muted-foreground">
                <Loader2 className="h-3 w-3 animate-spin" /> Loading more headlines
              </div>
            )}
            {!hasNextPage && loadedCount > 0 && (
              <span className="text-[11px] text-muted-foreground/50">
                Showing {loadedCount} of {totalCount} headlines
              </span>
            )}
          </div>
        </>
      )}
    </div>
  );
}
