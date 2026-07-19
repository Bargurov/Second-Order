/**
 * E2 — Mission I event-level evidence drilldown (mission-i-evidence-v2).
 *
 * The audit workpaper beneath the published 20-cell surface: opening one
 * available family/horizon/metric cell exposes that cell's exact
 * denominator, its separately labeled published and internally recomputed
 * aggregates, its reconciliation status, and the publication-ordered
 * per-event observations — all verbatim from the endpoint payload.  No
 * statistic is recomputed here, no outcome ranking or filter exists, and
 * default row order is always the publication's own ascending
 * anchor-session order (progressive 25-row disclosure never reorders).
 *
 * Fail-closed: an absent or malformed `event_level` block renders no
 * disclosure affordance and no fabricated empty state — the aggregate
 * surface stays, the refusal is explicit.  A structure-valid zero-row
 * cell (not expected in the published contract) renders its honest zero,
 * which stays distinct from the unavailable and malformed states.
 */
import { useState } from "react";

import type {
  MissionIEventLevel,
  MissionIEventLevelCell,
  MissionIEventRow,
  MissionIEvidenceSummary,
} from "@/lib/api";

/** Rows mounted per disclosure step — the panel never mounts a cell's
 *  full surface at once unless the reviewer asks for it. */
export const EVENT_ROWS_PAGE_SIZE = 25;

export type MissionIEventLevelState = "ok" | "absent" | "malformed";

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function nonEmptyString(v: unknown): v is string {
  return typeof v === "string" && v.length > 0;
}

const METHOD_KEYS = [
  "percentile_definition",
  "aggregate_definition",
  "signed_definition",
  "ordering_statement",
  "precision_policy",
  "claim_ceiling",
] as const;

const ROW_KEYS = [
  "event",
  "anchor_session",
  "response",
  "abs_mid_rank_pct",
  "signed_pct",
] as const;

function isContractRow(v: unknown): boolean {
  return isRecord(v) && ROW_KEYS.every((k) => nonEmptyString(v[k]));
}

// Frozen contract vocabulary and inventory (identities only — never
// research values).  The expected identity/order of the 20 cells is
// derived from the payload's own `primary_cells` surface, not from a
// second manually maintained table.
const CONTRACT_VERSION = "mission-i-evidence-v2";
const PUBLISHED_CELL_COUNT = 20;
const FAMILIES: ReadonlySet<string> = new Set(["FOMC", "OPEC"]);
const HORIZONS: ReadonlySet<string> = new Set(["1d", "5d", "20d"]);
const METRICS: ReadonlySet<string> = new Set([
  "raw_return",
  "spy_relative_ar",
  "sector_relative_ar",
  "sar",
]);

function isShapedCell(v: unknown): v is MissionIEventLevelCell {
  if (!isRecord(v)) return false;
  const published = v.published;
  const recomputed = v.recomputed;
  return (
    typeof v.cell === "number" &&
    nonEmptyString(v.cell_key) &&
    nonEmptyString(v.family) &&
    nonEmptyString(v.horizon) &&
    nonEmptyString(v.metric) &&
    typeof v.event_n === "number" &&
    v.event_n >= 0 &&
    isRecord(published) &&
    nonEmptyString(published.memp) &&
    nonEmptyString(published.signed_percentile_median) &&
    isRecord(recomputed) &&
    nonEmptyString(recomputed.memp) &&
    nonEmptyString(recomputed.signed_percentile_median) &&
    // the backend refuses service on any unreconciled cell, so a served
    // cell carrying anything but `true` is contract damage, never data
    v.reconciled === true &&
    Array.isArray(v.rows) &&
    v.rows.every(isContractRow)
  );
}

/** Classify the payload's event-level block: `absent` (no block — a
 *  pre-v2 record), `ok`, or `malformed` (present but inconsistent →
 *  fail closed, zero affordances).
 *
 *  `ok` is an EXACT contract, not a shape check: the declared v2
 *  version; exactly the 20 published cells, matching `primary_cells`
 *  index-by-index on cell number, cell key, family, horizon and metric
 *  (frozen vocabulary, unique numbers and keys, no FOMC 20d cell ever);
 *  denominators equal across both surfaces; published aggregates equal
 *  the primary surface AND the recomputed copies as exact decimal
 *  strings (no float conversion, no tolerance); rows unique and
 *  strictly ascending by anchor session in the served publication
 *  order; and every whole-block count (`total_rows`,
 *  `source.row_count`, `family_counts` restricted to exactly
 *  FOMC + OPEC) reconciling with the summed rows.  Damaged input is
 *  never sorted, repaired, or partially served. */
export function missionIEventLevelState(
  data: MissionIEvidenceSummary,
): MissionIEventLevelState {
  const summary = data as
    | (MissionIEvidenceSummary & { event_level?: unknown })
    | null
    | undefined;
  const ev = summary?.event_level;
  if (ev === undefined || ev === null) return "absent";
  if (!isRecord(ev)) return "malformed";

  // ---- Version and shallow block shape ---------------------------------
  if (summary?.contract_version !== CONTRACT_VERSION) return "malformed";
  const source = ev.source;
  const method = ev.method;
  const familyCounts = ev.family_counts;
  if (
    !isRecord(source) ||
    !nonEmptyString(source.artifact) ||
    !nonEmptyString(source.sha256) ||
    typeof source.bytes !== "number" ||
    typeof source.row_count !== "number"
  ) {
    return "malformed";
  }
  if (!isRecord(method) || !METHOD_KEYS.every((k) => nonEmptyString(method[k]))) {
    return "malformed";
  }
  if (typeof ev.total_rows !== "number" || !Array.isArray(ev.cells)) {
    return "malformed";
  }

  // ---- Inventory: exactly the 20 published cells, both surfaces --------
  const primaries = summary?.primary_cells;
  if (
    !Array.isArray(primaries) ||
    primaries.length !== PUBLISHED_CELL_COUNT ||
    summary?.constitution?.primary_cell_count !== PUBLISHED_CELL_COUNT ||
    ev.cells.length !== PUBLISHED_CELL_COUNT
  ) {
    return "malformed";
  }

  // ---- Per-cell: frozen order/identity, denominators, aggregates -------
  const cellNumbers = new Set<number>();
  const cellKeys = new Set<string>();
  const familyRowSums: Record<string, number> = {};
  let summedRows = 0;
  for (let i = 0; i < ev.cells.length; i++) {
    const c = ev.cells[i];
    if (!isShapedCell(c)) return "malformed";
    const p = primaries[i];
    if (p === undefined) return "malformed";
    if (
      c.cell !== p.cell ||
      c.cell_key !== p.cell_key ||
      c.family !== p.family ||
      c.horizon !== p.horizon ||
      c.metric !== p.metric
    ) {
      return "malformed";
    }
    if (
      !FAMILIES.has(c.family) ||
      !HORIZONS.has(c.horizon) ||
      !METRICS.has(c.metric) ||
      c.cell_key !== `${c.family}|${c.horizon}|${c.metric}`
    ) {
      return "malformed";
    }
    if (c.family === "FOMC" && c.horizon === "20d") return "malformed";
    if (cellNumbers.has(c.cell) || cellKeys.has(c.cell_key)) {
      return "malformed";
    }
    cellNumbers.add(c.cell);
    cellKeys.add(c.cell_key);
    if (c.rows.length !== c.event_n || c.event_n !== p.event_n_available) {
      return "malformed";
    }
    if (
      c.published.memp !== p.memp ||
      c.published.signed_percentile_median !== p.signed_percentile_median ||
      c.published.memp !== c.recomputed.memp ||
      c.published.signed_percentile_median !==
        c.recomputed.signed_percentile_median
    ) {
      return "malformed";
    }
    const seenEvents = new Set<string>();
    let prevAnchor = "";
    for (const row of c.rows) {
      if (seenEvents.has(row.event)) return "malformed";
      seenEvents.add(row.event);
      // strictly ascending anchors (also forbids duplicate anchors);
      // the served publication order is verified, never re-sorted
      if (!(row.anchor_session > prevAnchor)) return "malformed";
      prevAnchor = row.anchor_session;
    }
    familyRowSums[c.family] = (familyRowSums[c.family] ?? 0) + c.rows.length;
    summedRows += c.rows.length;
  }

  // ---- Whole-block counts reconcile ------------------------------------
  if (
    !isRecord(familyCounts) ||
    Object.keys(familyCounts).sort().join("|") !== "FOMC|OPEC" ||
    familyCounts.FOMC !== (familyRowSums.FOMC ?? 0) ||
    familyCounts.OPEC !== (familyRowSums.OPEC ?? 0)
  ) {
    return "malformed";
  }
  if (summedRows !== ev.total_rows) return "malformed";
  if (source.row_count !== ev.total_rows) return "malformed";
  return "ok";
}

/** The rows currently disclosed: a pure prefix of the publication-ordered
 *  input.  Never sorts, never filters, never reorders — progressive
 *  disclosure is a slice, nothing else. */
export function visibleEventRows(
  rows: MissionIEventRow[],
  shown: number,
): MissionIEventRow[] {
  return rows.slice(0, Math.max(0, shown));
}

/** Human-readable metric wording; the raw identity stays visible in the
 *  cell key wherever this is used. */
export function metricLabel(metric: string): string {
  switch (metric) {
    case "raw_return":
      return "raw return";
    case "spy_relative_ar":
      return "SPY-relative AR";
    case "sector_relative_ar":
      return "sector-relative AR";
    case "sar":
      return "SAR";
    default:
      return metric.replace(/_/g, " ");
  }
}

const PANEL_TH =
  "px-2 py-1 text-left font-mono text-[9.5px] font-medium uppercase tracking-[0.08em] text-on-surface-variant/55";
const PANEL_TD = "px-2 py-1 font-mono text-[11px] tabular-nums";

export interface MissionIEventLevelPanelProps {
  /** Contract-shaped summary whose event-level block validated `ok`. */
  data: MissionIEvidenceSummary;
  /** Frozen identity key of the opened cell (e.g. `FOMC|1d|raw_return`). */
  cellKey: string;
  /** DOM id the opening disclosure button points at via aria-controls. */
  panelId: string;
  /** Rendered as the panel's close control when provided. */
  onClose?: () => void;
  /** Optional starting disclosure depth; clamped to the cell's row count
   *  (the ReactionProfileCard `initialHorizon` precedent). */
  initialRowsShown?: number;
}

/** The opened audit workpaper for one published cell. */
export function MissionIEventLevelPanel({
  data,
  cellKey,
  panelId,
  onClose,
  initialRowsShown,
}: MissionIEventLevelPanelProps) {
  const eventLevel: MissionIEventLevel | undefined =
    missionIEventLevelState(data) === "ok" ? data.event_level : undefined;
  const cell = eventLevel?.cells.find((c) => c.cell_key === cellKey);
  const primary = data.primary_cells?.find?.((c) => c.cell_key === cellKey);
  const total = cell?.rows.length ?? 0;
  const [shown, setShown] = useState(() =>
    Math.min(Math.max(initialRowsShown ?? EVENT_ROWS_PAGE_SIZE, 0), total),
  );
  if (eventLevel === undefined || cell === undefined || primary === undefined) {
    return (
      <p className="border-l-2 border-on-surface-variant/50 bg-surface-container-low p-3 text-[11.5px] leading-relaxed text-on-surface-variant/85">
        Event-level disclosure unavailable: the requested cell is not present
        in the event-level block. No rows are shown in its place.
      </p>
    );
  }
  const labelId = `${panelId}-label`;
  const rows = visibleEventRows(cell.rows, shown);
  const clampedShown = rows.length;
  const knife = data.fragility?.knife_edge;
  const isKnifeCell = knife !== undefined && knife.cell_key === cellKey;

  return (
    <section
      id={panelId}
      aria-labelledby={labelId}
      className="flex flex-col gap-2.5 border-l-2 border-primary/40 bg-surface-container-low p-3"
    >
      {/* Identity — human labels first, raw identity kept visible */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-0.5">
          <p
            id={labelId}
            className="font-mono text-[10.5px] uppercase tracking-[0.1em] text-on-surface"
          >
            Event-level rows · {cell.family} · {cell.horizon} ·{" "}
            {metricLabel(cell.metric)} · {total} events
          </p>
          <p className="font-mono text-[9.5px] text-on-surface-variant/55">
            cell {cell.cell} of {eventLevel.cells.length} · {cell.cell_key}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 rounded-sm border border-border/50 px-2 py-0.5 font-mono text-[9.5px] uppercase tracking-[0.08em] text-on-surface-variant/70 hover:border-on-surface-variant/50 hover:text-on-surface focus-visible:outline focus-visible:outline-1 focus-visible:outline-primary"
        >
          close
        </button>
      </div>

      {/* Aggregate contract — published and recomputed stay separately
          labeled; reconciliation is the backend's internal exact-string
          comparison, never a new statistic */}
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-md bg-white/[0.06] sm:grid-cols-4">
        {[
          ["published MEMP", cell.published.memp],
          ["recomputed MEMP", cell.recomputed.memp],
          ["published signed pct median", cell.published.signed_percentile_median],
          ["recomputed signed pct median", cell.recomputed.signed_percentile_median],
        ].map(([label, value]) => (
          <div
            key={label}
            className="flex flex-col gap-0.5 bg-surface-container-lowest/60 p-2"
          >
            <span className="font-mono text-[8.5px] uppercase tracking-[0.08em] text-on-surface-variant/55">
              {label}
            </span>
            <span className="font-mono text-[12.5px] tabular-nums text-on-surface">
              {value}
            </span>
          </div>
        ))}
      </div>
      <p className="font-mono text-[10px] tabular-nums text-on-surface-variant/80">
        reconciliation: {cell.reconciled ? "reconciled" : "unreconciled"} —
        published equals recomputed as exact decimal strings · eligible
        denominator: event N {cell.event_n} · ordinary reference N{" "}
        {primary.reference_n_available} · {total} event rows
      </p>
      <p className="text-[11px] italic leading-relaxed text-on-surface-variant/70">
        Evidence class: descriptive · comparative · same-sample — the rows
        below are the published ordinary-period comparison observations
        behind this cell's aggregate, reconciled internally against it.
      </p>

      {isKnifeCell && (
        <p className="border-l-2 border-on-surface-variant/50 bg-surface-container-lowest/60 p-2 font-mono text-[10.5px] tabular-nums leading-relaxed text-on-surface-variant/85">
          knife-edge cell — MEMP {knife.memp} sits at the 0.5 midpoint edge ·
          LOEO {knife.f2_loeo.flips} / {knife.f2_loeo.runs} leave-out runs
          flip · the record's principal fragility (frozen explanation in the
          fragility section above)
        </p>
      )}

      {/* Publication-ordered event observations */}
      <div className="overflow-x-auto rounded-md border border-border/40">
        <table className="w-full min-w-[560px] border-collapse">
          <caption className="sr-only">
            {cell.family} {cell.horizon} {metricLabel(cell.metric)} event-level
            rows in publication order
          </caption>
          <thead>
            <tr>
              {["event", "anchor session", "response", "abs mid-rank pct", "signed pct"].map(
                (h) => (
                  <th key={h} scope="col" className={PANEL_TH}>
                    {h}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={`${cell.cell_key}|${row.anchor_session}|${row.event}`}
                data-mi-event-row
                className="border-t border-border/30"
              >
                <td className={`${PANEL_TD} text-on-surface`}>{row.event}</td>
                <td className={PANEL_TD}>{row.anchor_session}</td>
                <td className={PANEL_TD}>{row.response}</td>
                <td className={PANEL_TD}>{row.abs_mid_rank_pct}</td>
                <td className={`${PANEL_TD} text-on-surface-variant/70`}>
                  {row.signed_pct}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-mono text-[10px] tabular-nums text-on-surface-variant/70">
          Showing {clampedShown} of {total} event rows · publication order
          (ascending anchor session)
        </p>
        {clampedShown < total && (
          <button
            type="button"
            onClick={() =>
              setShown((s) => Math.min(s + EVENT_ROWS_PAGE_SIZE, total))
            }
            className="rounded-sm border border-border/50 px-2 py-0.5 font-mono text-[9.5px] uppercase tracking-[0.08em] text-on-surface-variant/70 hover:border-on-surface-variant/50 hover:text-on-surface focus-visible:outline focus-visible:outline-1 focus-visible:outline-primary"
          >
            show {Math.min(EVENT_ROWS_PAGE_SIZE, total - clampedShown)} more
          </button>
        )}
      </div>

      {/* Method context — the publication's own wording, verbatim */}
      <div className="flex flex-col gap-1 border-t border-border/30 pt-2">
        <p className="font-mono text-[9.5px] uppercase tracking-[0.12em] text-on-surface-variant/55">
          method · verbatim from the publication
        </p>
        <p className="text-[11px] leading-relaxed text-on-surface-variant/80">
          {eventLevel.method.percentile_definition}{" "}
          {eventLevel.method.aggregate_definition}{" "}
          {eventLevel.method.signed_definition}
        </p>
        <p className="text-[11px] leading-relaxed text-on-surface-variant/80">
          Row order: {eventLevel.method.ordering_statement}
        </p>
        <p className="text-[11px] leading-relaxed text-on-surface-variant/80">
          Reconciliation precision: {eventLevel.method.precision_policy}.
        </p>
        <p className="text-[11px] leading-relaxed text-on-surface-variant/80">
          Claim ceiling: {eventLevel.method.claim_ceiling}.
        </p>
      </div>

      {/* The explicit non-claim — the panel's one sanctioned negation site */}
      <p className="border-l-2 border-on-surface-variant/50 pl-2 text-[11px] italic leading-relaxed text-on-surface-variant/75">
        Event-level rows are reconciliation evidence for the published
        descriptive cell. They are not independent replication, causal
        estimates, statistical significance, forecasts, trade signals or
        representative-case proof.
      </p>

      {/* Provenance — payload values only.  The v2 contract exposes no
          source-section field: that limitation is stated, never inferred
          from the filename, the parser, or the repository; nulls stay
          stated the same way. */}
      <p className="break-all font-mono text-[9.5px] leading-relaxed text-on-surface-variant/50">
        GET /evidence/mission-i &middot; {data.contract_version} &middot;
        source {eventLevel.source.artifact} &middot;{" "}
        {eventLevel.source.bytes} bytes &middot;{" "}
        {eventLevel.source.row_count} rows parsed &middot; sha256{" "}
        {eventLevel.source.sha256} &middot; Source section: not exposed by{" "}
        {data.contract_version}. &middot; computation dates and execution
        commits: not recorded in any Mission I publication.
      </p>
    </section>
  );
}
