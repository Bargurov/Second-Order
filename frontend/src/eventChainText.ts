// Plain rendering rules of the event chains page, kept out of the JSX so they can be tested.

export const SAVE_READING_FIRST = "Save or clear your reading first.";
export const EVENT_GONE = "No longer on the events register.";
const NOT_SERVED = "Withheld: the register does not serve it.";

type When = { kind?: unknown; when?: unknown } | null;
export type EventLine = { label: string | null; text: string };

const shown = (value: unknown): string | null => (typeof value === "string" && value !== "" ? value : null);

/** "kind, when" as served; a null or empty part is named as withheld, never left empty. */
export function eventText(value: unknown): string {
  if (typeof value !== "object" || value === null) return NOT_SERVED;
  const one = value as NonNullable<When>;
  return `${shown(one.kind) ?? "kind withheld"}, ${shown(one.when) ?? "date withheld"}`;
}

/** The lines that show the event of a chain: its kind and date, and how the retained record compares with the pin. */
export function eventLines(event: { state: string; pinned: unknown; current: unknown }): EventLine[] {
  if (event.state === "changed") {
    return [{ label: "Pinned", text: eventText(event.pinned) }, { label: "Current", text: eventText(event.current) }];
  }
  if (event.state === "gone") return [{ label: null, text: EVENT_GONE }, { label: "Pinned", text: eventText(event.pinned) }];
  if (event.state === "unreadable") {
    return [{ label: null, text: "The events register cannot be read." }, { label: "Pinned", text: eventText(event.pinned) }];
  }
  return [{ label: "Event", text: eventText(event.current ?? event.pinned) }];
}

/** The history's sentence beside a version's change note when the review it answers is not on this machine (the view's
 * `change.review_note`), or null for any other version. */
export function reviewNoteSentence(change: unknown): string | null {
  if (typeof change !== "object" || change === null || Array.isArray(change)) return null;
  const note = shown((change as { review_note?: unknown }).review_note);
  return note === null ? null : `The version's change ${note}.`;
}

/** How a mechanism's mark ends, after "Drafted by the assistant;": what the owner's latest review of this version is.
 * It never says a review is awaited once one was given; with no approval state (an unverifiable history) it says so. */
export function mechanismMark(approval: { state: string | null; saved_at: string | null }): string {
  const on = approval.saved_at === null ? "" : ` on ${approval.saved_at.slice(0, 10)}`;
  if (approval.state === "approved") return `approved by the owner${on}`;
  if (approval.state === "approved_earlier_basis") {
    return `approved by the owner${on} on an earlier basis, not on this one`;
  }
  if (approval.state === "needs_revision") return `you asked for a revision${on}`;
  return approval.state === "awaiting_review" ? "awaiting your review" : "your review of it cannot be verified";
}

/** Whether a review may be sent: never while a reading is typed and unsaved. */
export const reviewBlockedBy = (readingLine: string): string | null =>
  readingLine.trim() !== "" ? SAVE_READING_FIRST : null;

/** Each price change as "From {event_year} to {year}: {change_pct}%". */
export const priceChanges = (eventYear: number, changes: { year: number; change_pct: string }[]): string[] =>
  changes.map((item) => `From ${eventYear} to ${item.year}: ${item.change_pct}%`);

/** Each year-to-year context item as "From {from} to {to}: {change_pct}%". */
export const priceContext = (context: { from: number; to: number; change_pct: string }[]): string[] =>
  context.map((item) => `From ${item.from} to ${item.to}: ${item.change_pct}%`);
