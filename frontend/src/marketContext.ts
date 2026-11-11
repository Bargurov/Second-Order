// Market context: the Federal Reserve Board's daily H.15 Treasury yields around a case's publication date, as
// description only. Dates are calendar dates (YYYY-MM-DD) and are never converted through the reader's time zone.
// Missing values stay missing: nothing is interpolated, and a missing expected session breaks the drawn line.
import { linear, niceTicks, paddedExtent } from "./chart.ts";

export const MARKET_CONTEXT_VIEW_VERSION = "market-context-view-0.2";

export interface ContextObservation {
  /** The source row's exact text ("ND" where the source gives no value), or null when it has no row for the date. */
  raw: string | null;
  value: number | null;
  status: string;
}

export interface ContextDay {
  date: string;
  weekday: string;
  session: boolean;
  observations: Record<string, ContextObservation>;
}

export interface ContextSeries {
  id: string;
  unique_identifier: string;
  label: string;
  short_label: string;
  description: string;
  unit: string;
  units_label: string;
  multiplier: string;
  currency: string;
  frequency: string;
  fred_equivalent: string;
  fred_page: string;
  citation: string;
  values: number;
  no_value_rows: number;
}

export interface ContextSource {
  file: string;
  sha256: string;
  bytes: number;
  url: string;
  requested_start: string;
  requested_end: string;
  returned_first: string;
  returned_last: string;
  rows: number;
  requested_at: string;
  received_at: string;
  http_status: number;
  content_type: string;
  response_date: string;
}

export interface MarketContextView {
  view_version: string;
  case_id: string;
  publication: { published_at: string; new_york_date: string };
  window: { start: string; end: string; days_before: number; days_after: number };
  series: ContextSeries[];
  source: ContextSource;
  days: ContextDay[];
  provenance: {
    publisher: string;
    release: string;
    release_url: string;
    data_download_url: string;
    help_url: string;
    crosswalk_url: string;
    underlying_source: string;
    terms: { url: string; statement: string };
    method: string;
    tool: string;
    vintage: null;
    vintage_note: string;
    calendar: { calendar: string; library: string; library_version: string; exceptions_version: string };
    bundle_version: string;
    preparation_version: string;
    view_sha256: string;
    manifest: string;
    manifest_sha256: string;
    acquisition_record: string;
    acquisition_sha256: string;
    index_version: string;
    index_sha256: string;
    /** The acquisition run this case's download belongs to; runs made at different times are never merged. */
    run: number;
    runs: number;
    run_cases: string[];
    /** Replies to this case's address that were refused in its run, before the kept one; none is used as data. */
    discarded: { requested_at: string; http_status: number | null; content_type: string | null; bytes: number;
                 reason: string }[];
  };
}

/** Every status the preparation can record, in words a reader can check against the table. */
export const STATUS_LABEL: Record<string, string> = {
  session_value: "Observed",
  session_missing: "Missing: expected session, the source gives no value",
  session_absent: "Missing: expected session, no row in the source",
  calendar_holiday: "No session: SIFMA holiday",
  not_a_session: "No session",
  unreconciled_value_on_calendar_holiday: "A value on a non-session date, not shown as an observation",
  issuer_no_observation: "No observation, documented by the issuer",
  issuer_observation_on_calendar_holiday: "Observed on a calendar holiday, documented by the issuer",
  // Private market context for selected events (event-market-context-view): states the case library never records.
  weekend: "No session: weekend",
  not_held: "Not in the local data: no retrieval covers this date",
  after_retrieval: "Not in the local data: after the last date its retrieval returned",
  future: "Not yet available: today or later",
  conflict: "Retrieval versions disagree: no value is chosen",
};
const SHOWN = new Set(["session_value", "issuer_observation_on_calendar_holiday"]);
/** Statuses that are gaps in a series: marked on the chart and breaking its line. */
export const GAPS = new Set(["session_missing", "session_absent", "unreconciled_value_on_calendar_holiday"]);
/** Statuses with no value that also break the line, unmarked or (conflicts) marked apart: never drawn across. */
export const BREAKS = new Set([...GAPS, "conflict", "not_held", "after_retrieval", "future"]);

/** What the chart and the table read: the case library's view and an event's private view both have it. */
export interface ChartView {
  window: { start: string; end: string };
  series: { id: string; label: string; short_label: string }[];
  days: ContextDay[];
  publication: { new_york_date: string };
}
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

function parts(isoDate: string): [number, number, number] {
  const match = DATE.exec(isoDate);
  if (!match) throw new Error(`${isoDate} is not a YYYY-MM-DD date`);
  const [year, month, day] = match.slice(1).map(Number);
  const check = new Date(Date.UTC(year, month - 1, day));
  if (check.getUTCFullYear() !== year || check.getUTCMonth() !== month - 1 || check.getUTCDate() !== day) {
    throw new Error(`${isoDate} is not a calendar date`);
  }
  return [year, month, day];
}

/** Days since 1970-01-01 for a calendar date, computed in UTC so no time zone can move it. */
export function dayNumber(isoDate: string): number {
  const [year, month, day] = parts(isoDate);
  return Date.UTC(year, month - 1, day) / 86_400_000;
}

/** "3 Jul 2025", read from the date's own digits. */
export function formatContextDate(isoDate: string, withYear = true): string {
  const [year, month, day] = parts(isoDate);
  return `${day} ${MONTHS[month - 1]}${withYear ? ` ${year}` : ""}`;
}

/** "2y" for "2-year": the short tag that marks a series' gap on the chart. */
export const gapTag = (series: { short_label: string }) => `${series.short_label.split("-")[0]}y`;

export const CHART = { width: 720, height: 300, top: 28, right: 32, bottom: 34, left: 58 };
/** Phones: a smaller drawing, so its text is not scaled down to an unreadable size. */
export const CHART_NARROW = { width: 360, height: 250, top: 30, right: 26, bottom: 30, left: 50 };

export interface ChartPoint { date: string; raw: string; value: number; cx: number; cy: number }

export function chartModel(view: ChartView, size = CHART) {
  const { width, height, top, right, bottom, left } = size;
  const x = linear([dayNumber(view.window.start), dayNumber(view.window.end)], [left, width - right]);
  const values = view.days.flatMap((day) => view.series.flatMap((series) => {
    const observation = day.observations[series.id];
    return observation && SHOWN.has(observation.status) && observation.value !== null ? [observation.value] : [];
  }));
  const yDomain = paddedExtent(values.length ? values : [0, 1], 0.15);
  const y = linear(yDomain, [height - bottom, top]);
  const lines = view.series.map((series) => {
    const points: ChartPoint[] = [];
    const segments: ChartPoint[][] = [];
    const missing: string[] = [];
    const conflicts: string[] = [];
    let current: ChartPoint[] = [];
    for (const day of view.days) {
      const observation = day.observations[series.id];
      if (SHOWN.has(observation.status) && observation.value !== null && observation.raw !== null) {
        const point = { date: day.date, raw: observation.raw, value: observation.value,
                        cx: x(dayNumber(day.date)), cy: y(observation.value) };
        points.push(point);
        current.push(point);
      } else if (BREAKS.has(observation.status)) {
        if (GAPS.has(observation.status)) missing.push(day.date);
        if (observation.status === "conflict") conflicts.push(day.date);
        if (current.length) segments.push(current);
        current = [];
      }
    }
    if (current.length) segments.push(current);
    return { id: series.id, label: series.label, tag: gapTag(series), points, segments, missing, conflicts };
  });
  const xTicks = [];  // Weekly from the window's first day; the publication date falls on the middle tick.
  for (let day = dayNumber(view.window.start); day <= dayNumber(view.window.end); day += 7) {
    const date = new Date(day * 86_400_000).toISOString().slice(0, 10);  // A UTC date: no zone can shift it.
    xTicks.push({ date, label: formatContextDate(date, false), x: x(day) });
  }
  const yTicks = niceTicks(yDomain[0], yDomain[1], 5).map((value) => ({ value, label: `${value.toFixed(2)}%`, y: y(value) }));
  const marker = { date: view.publication.new_york_date, x: x(dayNumber(view.publication.new_york_date)) };
  return { x, y, yDomain, xTicks, yTicks, marker, lines };
}

export interface ContextRow {
  date: string;
  label: string;
  weekday: string;
  publication: boolean;
  cells: { series: string; text: string; observed: boolean; status: string }[];
  note: string;
}

/** One table row per calendar date, with each series' value as published and every non-observation in words. */
export function contextRows(view: ChartView): ContextRow[] {
  return view.days.map((day) => {
    const cells = view.series.map((series) => {
      const observation = day.observations[series.id];
      const observed = SHOWN.has(observation.status) && observation.raw !== null && observation.value !== null;
      return { series: series.id, text: observed ? `${observation.raw}%` : "—", observed, status: observation.status };
    });
    const unobserved = cells.filter((cell) => !cell.observed);
    const statuses = new Set(unobserved.map((cell) => cell.status));
    const note = unobserved.length === 0 ? ""
      : unobserved.length === cells.length && statuses.size === 1 ? STATUS_LABEL[unobserved[0].status] ?? unobserved[0].status
      : unobserved.map((cell) => `${view.series.find((series) => series.id === cell.series)!.short_label}: ${
          (STATUS_LABEL[cell.status] ?? cell.status).toLowerCase()}`).join("; ");
    return { date: day.date, label: formatContextDate(day.date), weekday: day.weekday,
             publication: day.date === view.publication.new_york_date, cells, note };
  });
}

/** What the page says about replies to this case's address that were refused before the kept one. */
export function discardedNote(discarded: MarketContextView["provenance"]["discarded"]): string {
  if (discarded.length === 0) return "No reply to this address was discarded in its run.";
  const replies = discarded.map((item) => `${item.requested_at}, ${item.reason} (HTTP ${item.http_status ?? "none"}, ${
    item.content_type ?? "no content type"}, ${item.bytes} bytes)`).join("; ");
  return discarded.length === 1
    ? `Before it, one reply to this address was discarded: ${replies}. Nothing from it is used.`
    : `Before it, ${discarded.length} replies to this address were discarded: ${replies}. Nothing from them is used.`;
}

/** How many expected sessions lack a value, per series: what the page says about gaps in this window. */
export function gapCounts<V extends ChartView>(view: V): { series: V["series"][number]; count: number }[] {
  return view.series.map((series) => ({
    series, count: view.days.filter((day) => GAPS.has(day.observations[series.id].status)).length,
  }));
}
