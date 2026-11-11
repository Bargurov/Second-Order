// Replies bound to the inputs they were sent for (the copper tools' preview and capital panel). Each request takes a
// ticket naming its inputs; a reply is used only when its ticket is still the latest and its inputs are still the ones
// on the page. A changed input invalidates every ticket in flight, so a slow reply can never put an earlier
// computation on the screen or let it be saved. Pure: no React and no requests here.

/** The inputs as one canonical string: object keys sorted, so equal inputs always give equal keys. */
export function inputKey(value: unknown): string {
  const canonical = (item: unknown): unknown => {
    if (Array.isArray(item)) return item.map(canonical);
    if (item !== null && typeof item === "object") {
      return Object.fromEntries(Object.keys(item as object).sort()
        .map((key) => [key, canonical((item as Record<string, unknown>)[key])]));
    }
    return item;
  };
  return JSON.stringify(canonical(value));
}

export interface Ticket { serial: number; key: string }

export class Latest {
  private serial = 0;

  /** A ticket for one request sent for inputs `key`; it supersedes every earlier ticket. */
  begin(key: string): Ticket {
    this.serial += 1;
    return { serial: this.serial, key };
  }

  /** The inputs changed: no ticket in flight may be used any more. */
  invalidate(): void {
    this.serial += 1;
  }

  /** Whether a reply sent with `ticket` may be used now that the page's inputs are `current`. */
  accepts(ticket: Ticket, current: string): boolean {
    return ticket.serial === this.serial && ticket.key === current;
  }
}

/** Send one request with a ticket for `key`; the reply is returned only if, when it arrives, its ticket is still the
 * latest and `current()` still names the same inputs. */
export async function latest<T>(gate: Latest, key: string, current: () => string,
                                call: () => Promise<T>): Promise<{ used: true; value: T } | { used: false }> {
  const ticket = gate.begin(key);
  const value = await call();
  return gate.accepts(ticket, current()) ? { used: true, value } : { used: false };
}
