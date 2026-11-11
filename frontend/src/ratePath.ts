// Market-implied rate path: a saved event's separate rate-path record (/api/rate-context/capture/:id), read from a
// retained Atlanta Fed Market Probability Tracker workbook. The server verifies every read; this module refuses a reply
// that breaks the view's own rules: a percent that is not the exact decimal shift of its basis points, an observation
// on or after the publication date, windows out of order or beyond four, a probability anywhere in the windows, a
// meeting-specific price that is anything but unavailable, or provenance claiming an HTTP status it never recorded.
import type { Loaded } from "./api";

export const RATE_PATH_VERSION = "rate-path-view-0.1";
export const RATE_STATES = ["unsupported", "not_prepared", "unreadable", "no_coverage", "available"] as const;
export type RateState = (typeof RATE_STATES)[number];
export const MAX_WINDOWS = 4;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const DECIMAL = /^(-?)(\d+)(?:\.(\d+))?$/;
const SHA = /^[0-9a-f]{64}$/;
const SOURCE_PAGE = "https://www.atlantafed.org/";
const UNREACHABLE = "The local API did not answer. Start it with: python -m second_order serve";

export interface Statistic { bp: string; percent: string; raw: string; row: number }
export type StatisticKey = "mean" | "p25" | "p75";
export interface RateWindow { reference_start: string; statistics: Record<StatisticKey, Statistic | null> }
export interface Selection {
  state: "selected" | "no_coverage"; publication_new_york_date: string; observation_date: string | null;
  calendar_days_before: number | null; same_day_observation: boolean; first_observation: string;
  last_observation: string; reason: "none_before" | "none_on_or_after" | null;
}
export interface RatePathView {
  view_version: string; capture_id: string; state: RateState; problem: string | null;
  provider_called: false; written: false;
  publication: { published_at_as_supplied: string; published_at: string; new_york_date: string; new_york_time: string;
    new_york_offset: string };
  measure: { id: string; statement: string }; rule: { id: string; statement: string };
  meeting_specific: { state: "unavailable"; statement: string }; separate: string; limits: string[];
  source: { publisher: string; product: string; file: string; page_url: string; file_url: string; attribution: string };
  selection: Selection | null;
  target_range: { raw: string; bps: [number, number]; percent: [string, string] } | null;
  windows: RateWindow[]; windows_listed: number | null;
  origin: { state: "none" } | { state: "verified"; link_sha256: string; item_id: string; content_sha256: string;
    version: number | null; versions: number; title: string } | null;
  provenance: {
    source_id: string; sha256: string; bytes: number; obtained_on: string; method: string; supplied_name: string;
    retained_at: string; http_status: null; response_headers: null; publication_time: null; unknown: string;
    parser_version: string; validated_at: string; validation_sha256: string; workbook_rows: number;
    first_observation: string; last_observation: string; record_version: number; prepared_at: string;
  } | null;
  license: { statement: string; paragraphs: string[] } | null;
  definitions: { description: string; fields: Record<string, string> } | null;
  versions: { version: number; prepared_at: string; source_id: string }[];
}

const isText = (value: unknown): value is string => typeof value === "string" && value.trim().length > 0;
const object = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null &&
  !Array.isArray(value);
const isDay = (value: unknown): value is string => typeof value === "string" && DAY.test(value) &&
  !Number.isNaN(Date.parse(`${value}T00:00:00Z`)) && new Date(`${value}T00:00:00Z`).toISOString().startsWith(value);
const daysBetween = (from: string, to: string) => Math.round((Date.parse(`${to}T00:00:00Z`) -
  Date.parse(`${from}T00:00:00Z`)) / 86_400_000);

/** Basis points to percent by moving the decimal point two places, exactly as the server does: "315.50" -> "3.1550". */
export function shiftPercent(bp: string): string | null {
  const match = DECIMAL.exec(bp);
  if (!match) return null;
  const [, sign, whole, fraction = ""] = match;
  const digits = whole + fraction;
  const point = whole.length - 2;
  const head = point > 0 ? digits.slice(0, point).replace(/^0+(?=\d)/, "") : "0";
  const tail = point > 0 ? digits.slice(point) : "0".repeat(-point) + digits;
  return `${sign}${head}${tail ? `.${tail}` : ""}`;
}

function statisticOk(value: unknown): value is Statistic | null {
  if (value === null) return true;
  if (!object(value) || typeof value.bp !== "string" || typeof value.raw !== "string" ||
      !Number.isInteger(value.row) || (value.row as number) < 2) return false;
  return DECIMAL.test(value.bp) && value.raw.trim() === value.bp && shiftPercent(value.bp) === value.percent;
}

function windowsOk(body: Record<string, unknown>): boolean {
  const windows = body.windows as unknown[];
  if (!Array.isArray(windows) || windows.length === 0 || windows.length > MAX_WINDOWS ||
      !Number.isInteger(body.windows_listed) || windows.length !== Math.min(MAX_WINDOWS, body.windows_listed as number)) {
    return false;
  }
  if (JSON.stringify(windows).toLowerCase().includes("prob")) return false;  // No probability is ever carried here.
  const starts: string[] = [];
  for (const window of windows) {
    if (!object(window) || !isDay(window.reference_start) || !object(window.statistics)) return false;
    const stats = window.statistics as Record<string, unknown>;
    if (Object.keys(stats).sort().join() !== "mean,p25,p75" || !Object.values(stats).every(statisticOk)) return false;
    const low = stats.p25 as Statistic | null;
    const high = stats.p75 as Statistic | null;
    if (low && high && Number(low.bp) > Number(high.bp)) return false;
    starts.push(window.reference_start);
  }
  return starts.every((start, index) => index === 0 || starts[index - 1] < start);
}

function selectionOk(selection: unknown, publication: string, available: boolean): boolean {
  if (!object(selection) || selection.publication_new_york_date !== publication || !isDay(selection.first_observation) ||
      !isDay(selection.last_observation) || typeof selection.same_day_observation !== "boolean") return false;
  if (!available) {
    return selection.state === "no_coverage" && selection.observation_date === null &&
      selection.calendar_days_before === null && ["none_before", "none_on_or_after"].includes(selection.reason as string);
  }
  const observed = selection.observation_date;
  return selection.state === "selected" && selection.reason === null && isDay(observed) && observed < publication &&
    selection.first_observation <= observed && selection.last_observation >= publication &&
    selection.calendar_days_before === daysBetween(observed, publication);
}

function provenanceOk(body: Record<string, unknown>): boolean {
  const record = body.provenance;
  const license = body.license;
  const versions = body.versions;
  if (!object(record) || !SHA.test(String(record.sha256)) || !SHA.test(String(record.validation_sha256)) ||
      record.http_status !== null || record.response_headers !== null || record.publication_time !== null ||
      !isDay(record.obtained_on) || !isText(record.method) || !isText(record.unknown) ||
      !Number.isInteger(record.record_version) || !isText(record.prepared_at)) return false;
  if (!object(license) || !isText(license.statement) || !Array.isArray(license.paragraphs) ||
      !license.paragraphs.includes(license.statement)) return false;
  if (!object(body.definitions) || !object(body.definitions.fields) ||
      !["reference_start", "Rate: mean", "Rate: 25th percentile", "Rate: 75th percentile"]
        .every((name) => isText((body.definitions as { fields: Record<string, unknown> }).fields[name]))) return false;
  return Array.isArray(versions) && versions.length > 0 &&
    (versions.at(-1) as Record<string, unknown>).version === record.record_version;
}

/** The reply as served, or false. Every state keeps the meeting-specific measurement unavailable. */
export function isRatePathView(body: unknown, captureId?: string): body is RatePathView {
  if (!object(body) || body.view_version !== RATE_PATH_VERSION || body.provider_called !== false ||
      body.written !== false || !isText(body.capture_id) || (captureId !== undefined && body.capture_id !== captureId) ||
      !RATE_STATES.includes(body.state as RateState)) return false;
  const meeting = body.meeting_specific;
  const publication = body.publication;
  if (!object(meeting) || meeting.state !== "unavailable" || !isText(meeting.statement) || !isText(body.separate) ||
      !Array.isArray(body.limits) || body.limits.length === 0 || !body.limits.every(isText) ||
      !object(publication) || !isDay(publication.new_york_date) || !object(body.source) ||
      !String(body.source.page_url).startsWith(SOURCE_PAGE) || !isText(body.source.attribution)) return false;
  const state = body.state as RateState;
  const empty = Array.isArray(body.windows) && body.windows.length === 0 && body.target_range === null;
  if (state === "unsupported" || state === "not_prepared") {
    return empty && body.selection === null && body.provenance === null && body.problem === null;
  }
  if (state === "unreadable") return empty && body.selection === null && isText(body.problem);
  if (body.problem !== null || !provenanceOk(body)) return false;
  if (state === "no_coverage") return empty && selectionOk(body.selection, publication.new_york_date, false);
  const target = body.target_range;
  if (!object(target) || !Array.isArray(target.bps) || target.bps.length !== 2 ||
      !target.bps.every(Number.isInteger) || target.bps[0] > target.bps[1] ||
      target.raw !== `${target.bps[0]}bps - ${target.bps[1]}bps` || !Array.isArray(target.percent) ||
      target.percent[0] !== shiftPercent(String(target.bps[0])) ||
      target.percent[1] !== shiftPercent(String(target.bps[1]))) return false;
  return selectionOk(body.selection, publication.new_york_date, true) && windowsOk(body);
}

export async function fetchRatePath(captureId: string, signal: AbortSignal): Promise<Loaded<RatePathView>> {
  let response: Response;
  try {
    response = await fetch(`/api/rate-context/capture/${encodeURIComponent(captureId)}`,
                           { signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if (signal.aborted) throw error;
    return { state: "error", message: UNREACHABLE };
  }
  const body: unknown = await response.json().catch(() => null);
  const message = (object(body) && typeof body.detail === "string" ? body.detail : null) ??
    `Unexpected response (${response.status}).`;
  if (response.status === 404) return { state: "missing", message };
  if (!response.ok) return { state: "error", message };
  if (!isRatePathView(body, captureId)) return { state: "error", message: "The reply could not be read by this page." };
  return { state: "ready", data: body };
}

/** The command that prepares this event's context; only the operator runs it, never a page. */
export const prepareCommand = (captureId: string) => `python -m second_order rate-context prepare --capture ${captureId}`;

/** A shared scale for the four windows' 25th–75th ranges, as positions from 0 to 100. */
export function strip(windows: RateWindow[]): (window: RateWindow) => { low: number; high: number; mean: number | null } | null {
  const values = windows.flatMap((window) => [window.statistics.p25, window.statistics.p75, window.statistics.mean])
    .filter((item): item is Statistic => item !== null).map((item) => Number(item.bp));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const place = (value: number) => Math.round(((value - min) / span) * 1000) / 10;
  return (window) => {
    const { p25, p75, mean } = window.statistics;
    if (!p25 || !p75) return null;
    return { low: place(Number(p25.bp)), high: place(Number(p75.bp)), mean: mean ? place(Number(mean.bp)) : null };
  };
}
