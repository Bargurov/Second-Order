// Pure client-side boundaries for the Tracker's local event-intake form.
// The server remains authoritative and stores the exact normalized request; these checks only keep incomplete
// forms from being submitted. Source text is never trimmed or rewritten.

export type MockOutcome = "draft" | "no_draft";

/** What the server has recorded for one capture (GET /api/intake/<capture>/attempt). */
export interface AttemptState {
  flow_version: string;
  capture_id: string;
  state: "none" | "incomplete" | "awaiting_publication" | "ready" | "invalid";
  files: string[];
  detail: string;
  draft_id?: string;
  outcome?: "draft" | "no_draft" | "invalid" | "technical_failure";
  /** The manifest's outcome, for example "transport error" when no response arrived. */
  recorded_outcome?: string;
  mode: "mock" | "paid" | null;
  /** Whether a paid request left the server (attempt.json was written before sending). */
  sent: boolean;
  sent_at?: string | null;
  provider_called: false;
}

/** What a recorded outcome means for the reviewer, in words; a paid outcome never claims more than is known. */
export function outcomeText(recorded: string | undefined, mode: "mock" | "paid" | null): string {
  switch (recorded) {
    case "draft":
      return mode === "paid" ? "The model proposed a draft." : "The local mock produced a draft.";
    case "no draft":
      return mode === "paid" ? "The model declined to draft." : "The local mock declined to draft.";
    case "refused":
      return "The response broke the drafting contract, so none of its content is shown.";
    case "provider error":
      return "The provider returned an error; its request ID is recorded.";
    case "transport error":
      return "No response arrived. The outcome is unknown: the provider may have received and billed the request.";
    case "credential echo":
      return "The response echoed the credential, so nothing from it was kept.";
    default:
      return "The recorded outcome is shown in the review screen.";
  }
}

/**
 * Whether a new mock attempt may be approved. Only before any dispatch, or when the recorded state shows that no
 * attempt exists. An unreadable state, an interrupted attempt or a recorded response never allow another one.
 */
export function mayApprove(attempt: AttemptState | "unreadable" | null): boolean {
  return attempt === null || (attempt !== "unreadable" && attempt.state === "none");
}

export interface IntakeFields {
  headline: string;
  sourceUrl: string;
  /** The publication's calendar date, YYYY-MM-DD, as printed with it. */
  publishedDate: string;
  /** Its time of day, HH:MM or HH:MM:SS. */
  publishedTime: string;
  /** Its UTC offset, ±HH:MM, chosen explicitly. This computer's time zone is never used. */
  publishedOffset: string;
  sourceText: string;
}

export interface IntakePayload {
  headline: string;
  source_url: string;
  published_at: string;
  source_text: string;
  /** The Inbox entry version that filled the form, recorded beside the capture; never part of the request. */
  origin?: { item_id: string; content_sha256: string };
}

/** Every offset the form offers and the server accepts: -12:00 to +14:00 in 15-minute steps (+00:00 is UTC). */
export const UTC_OFFSETS: readonly string[] = Array.from({ length: (26 * 60) / 15 + 1 }, (_, step) => {
  const minutes = -12 * 60 + step * 15;
  const size = Math.abs(minutes);
  const hours = String(Math.floor(size / 60)).padStart(2, "0");
  return `${minutes < 0 ? "-" : "+"}${hours}:${String(size % 60).padStart(2, "0")}`;
});

/** "UTC−04:00", with a typographic minus; +00:00 is labelled as UTC itself. */
export const offsetLabel = (offset: string) =>
  offset === "+00:00" ? "UTC+00:00 (UTC)" : `UTC${offset.replace("-", "−")}`;

const DAYS_IN_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
const isLeapYear = (year: number) => (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;

/**
 * The publication time exactly as the operator gave it: date, time of day and explicit UTC offset, joined as
 * YYYY-MM-DDTHH:MM:SS±HH:MM. Nothing is converted here, so the result never depends on this computer's time zone;
 * the server normalizes it to UTC and the preview shows both. Impossible dates and times are refused, not rolled
 * over.
 */
export function publishedAt(date: string, time: string, offset: string): { value: string } | { problem: string } {
  const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  if (!day) return { problem: "Enter the publication date." };
  const [year, month, dayOfMonth] = day.slice(1).map(Number);
  const monthDays = month === 2 && isLeapYear(year) ? 29 : DAYS_IN_MONTH[month - 1];
  if (month < 1 || month > 12 || dayOfMonth < 1 || dayOfMonth > monthDays) {
    return { problem: `${date} is not a calendar date.` };
  }
  const clock = /^(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(time);
  if (!clock) return { problem: "Enter the publication time of day." };
  const seconds = clock[3] ?? "00";
  if (Number(clock[1]) > 23 || Number(clock[2]) > 59 || Number(seconds) > 59) {
    return { problem: `${time} is not a time of day.` };
  }
  if (!offset) return { problem: "Choose the publication's UTC offset; this computer's time zone is never used." };
  if (!UTC_OFFSETS.includes(offset)) return { problem: `${offset} is not an accepted UTC offset.` };
  return { value: `${date}T${clock[1]}:${clock[2]}:${seconds}${offset}` };
}

/** The "Published at (UTC)" line of the saved request's user message: the instant the request actually holds. */
export function requestPublishedAt(request: Record<string, unknown>): string | null {
  const messages = request.messages;
  if (!Array.isArray(messages) || messages.length !== 1) return null;
  const content: unknown = (messages[0] as { content?: unknown }).content;
  const text = typeof content === "string" ? content
    : Array.isArray(content) ? content.map((block) => (block as { text?: unknown }).text).join("\n") : null;
  const line = typeof text === "string" ? /^Published at \(UTC\): (.+)$/m.exec(text) : null;
  return line ? line[1] : null;
}

export function intakePayload(fields: IntakeFields): { payload: IntakePayload | null; problem: string | null } {
  const headline = fields.headline.trim();
  const sourceUrl = fields.sourceUrl.trim();
  if (!headline) return { payload: null, problem: "Enter a headline." };
  if (!sourceUrl) return { payload: null, problem: "Enter the published source URL." };
  try {
    const url = new URL(sourceUrl);
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      return { payload: null, problem: "The source must be an http or https URL." };
    }
  } catch {
    return { payload: null, problem: "Enter a valid source URL." };
  }
  const time = publishedAt(fields.publishedDate, fields.publishedTime, fields.publishedOffset);
  if ("problem" in time) return { payload: null, problem: time.problem };
  if (!fields.sourceText.trim()) return { payload: null, problem: "Paste the published text." };
  return {
    payload: { headline, source_url: sourceUrl, published_at: time.value, source_text: fields.sourceText },
    problem: null,
  };
}
