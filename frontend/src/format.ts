import type { AnchorKey, DossierSummary, DossierVerdict, Hypothesis, LegResult, LegView } from "./types";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MINUS = "−";

const pad = (value: number) => String(value).padStart(2, "0");

/** "18 Sep 2024" in UTC. */
export function formatDay(iso: string): string {
  const date = new Date(iso);
  return `${date.getUTCDate()} ${MONTHS[date.getUTCMonth()]} ${date.getUTCFullYear()}`;
}

/** A snapshot's vintage: FRED's real-time date, or plainly none (the Board's release package has no vintage). */
export function vintageLabel(vintage: string | null): string {
  return vintage === null ? "None: no historical vintage" : formatDay(vintage);
}

/** "18 Sep 2024, 18:00 UTC". */
export function formatUtc(iso: string): string {
  const date = new Date(iso);
  return `${formatDay(iso)}, ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())} UTC`;
}

export const monthLabel = (time: number, withYear: boolean) => {
  const date = new Date(time);
  return withYear ? `${MONTHS[date.getUTCMonth()]} ${date.getUTCFullYear()}` : MONTHS[date.getUTCMonth()];
};

export function signed(value: number, digits: number): string {
  const text = Math.abs(value).toFixed(digits);
  if (Number(text) === 0) return text;
  return `${value < 0 ? MINUS : "+"}${text}`;
}

export function formatNumber(value: number, digits: number): string {
  return value < 0 ? `${MINUS}${Math.abs(value).toFixed(digits)}` : value.toFixed(digits);
}

/** Measured changes in their registry units: basis points, percent or percent abnormal return. */
export function formatChange(value: number, unit: string): string {
  if (unit === "bp") return `${signed(value, 1)} bp`;
  if (unit === "% AR") return `${signed(value, 2)}% AR`;
  return `${signed(value, 2)}%`;
}

export const unitDigits = (unit: string) => (unit === "bp" ? 1 : 2);

export const shortHash = (hash: string, length = 10) => `${hash.slice(0, length)}…`;

export const percent = (value: number | null) => (value === null ? "—" : `${Math.round(value * 100)}%`);

export const VERDICT_LABEL: Record<DossierVerdict, string> = {
  supported: "Supported",
  contradicted: "Contradicted",
  inconclusive: "Inconclusive",
  unavailable: "Unavailable",
  excluded: "Excluded",
  pending: "Pending",
  mixed: "Mixed",
  incomplete: "Incomplete",
};

export function verdictMeaning(verdict: DossierVerdict, upper: number, lower: number): string {
  switch (verdict) {
    case "supported":
      return `Moved in the expected direction by an unusual amount (rank ≥ ${upper.toFixed(2)}).`;
    case "contradicted":
      return `Moved against the expected direction by an unusual amount (rank ≤ ${lower.toFixed(2)}).`;
    case "inconclusive":
      // An extreme rank is still inconclusive when the direction condition fails.
      return "The measured move does not meet the combined direction and percentile criteria for support or contradiction.";
    case "mixed":
      return "The primary leg is supported and a secondary leg is contradicted.";
    case "incomplete":
      return "The primary leg is supported; secondary evidence is missing or pending.";
    default:
      return "No scored outcome for this leg.";
  }
}

export const ANCHOR_POLICY: Record<string, string> = {
  simulated_publication_replay: "Simulated replay: scored from the last observation before publication.",
  regular_session_last_close_before_freeze: "Regular session: last close before an out-of-session freeze.",
  regular_session_first_close_after_freeze: "Regular session: first close after an in-session freeze.",
  first_post_freeze_observation: "First observation after the freeze.",
  daily_first_date_after_freeze_date: "Daily convention: first observation dated after the freeze date (New York).",
  daily_replay_before_publication_date:
    "Daily replay: scored from the last observation dated before the publication date (New York).",
};

export const NOT_EVALUATED = "Not yet evaluated";

/** A recorded verdict, or an explicit not-yet-evaluated state when nothing has been recorded. */
export function verdictStatus(verdict: DossierVerdict | null): { label: string; className: string } {
  return verdict
    ? { label: VERDICT_LABEL[verdict], className: `verdict-${verdict}` }
    : { label: NOT_EVALUATED, className: "state-unevaluated" };
}

export const caseStatus = (row: Pick<DossierSummary, "state" | "verdict">) =>
  verdictStatus(row.state === "evaluated" ? row.verdict : null);

const ANCHOR_KEYS: AnchorKey[] = ["event_anchor", "reference_end", "score_anchor", "target_at"];

/**
 * Recorded anchors keyed as the prepared series keys its points: New York observation dates for
 * daily-date series (a UTC reading of their 23:59:59 New York instants would shift the day),
 * recorded timestamps otherwise.
 */
export function anchorPoints(result: LegResult, view: LegView): Partial<Record<AnchorKey, string>> {
  if (view.anchor_dates) return view.anchor_dates;
  return Object.fromEntries(ANCHOR_KEYS.flatMap((key) => (result[key] ? [[key, result[key]]] : [])));
}

/** The window is shaded only when its end is in the evaluated data; otherwise say so instead. */
export function horizonLegend(day: string | null, horizon: number): string {
  return day
    ? `Horizon end · ${day} (${horizon}-session scored window shaded)`
    : `Horizon end · not in the evaluated data (${horizon}-session window, so nothing is shaded)`;
}

export function anchorDay(anchors: Partial<Record<AnchorKey, string>>, key: AnchorKey): string | null {
  const at = anchors[key];
  return at ? formatDay(at) : null;
}

/**
 * How the hypothesis was submitted, in the reader's terms; null when there is nothing to add.
 * "Manual" means outside the project's model adapter, not that no AI was involved.
 */
export function authorshipNote(hypothesis: Hypothesis): string | null {
  if (hypothesis.engine.provider !== "manual") return null;
  const adapter = "not a run of the project's model adapter, which does not rule out AI assistance";
  return hypothesis.evidence_class === "replay"
    ? `Submitted manually after the event; ${adapter}. Not research evidence.`
    : `Submitted manually and frozen before its outcome; ${adapter}. Not research evidence.`;
}
