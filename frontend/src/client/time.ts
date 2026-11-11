// Times as the Client shows them: in the quota time zone the server names (Account.daily.timezone), with UTC where a
// boundary matters. Nothing here decides anything; the server's times are only formatted.

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function zoneParts(iso: string, timeZone: string): Record<string, string> | null {
  try {
    const format = new Intl.DateTimeFormat("en-GB", {
      timeZone, year: "numeric", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
    });
    return Object.fromEntries(format.formatToParts(new Date(iso)).map((part) => [part.type, part.value]));
  } catch {
    return null;  // An unknown time zone name or an unreadable time.
  }
}

const compose = (parts: Record<string, string>) =>
  `${Number(parts.day)} ${MONTHS[Number(parts.month) - 1]} ${parts.year}, ${parts.hour}:${parts.minute}`;

/** "14 Oct 2026, 21:00 UTC". */
export function inUtc(iso: string): string {
  const parts = zoneParts(iso, "UTC");
  return parts ? `${compose(parts)} UTC` : iso;
}

/** "15 Oct 2026, 00:00 (Asia/Jerusalem)", or UTC when the zone cannot be used. */
export function inZone(iso: string, timeZone: string): string {
  const parts = zoneParts(iso, timeZone);
  return parts ? `${compose(parts)} (${timeZone})` : inUtc(iso);
}

/** A calendar day as the server states it ("2026-10-14" -> "14 Oct 2026"); no time zone is applied. */
export function dayLabel(day: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  return match ? `${Number(match[3])} ${MONTHS[Number(match[2]) - 1]} ${match[1]}` : day;
}
