// The tabs of one browser share one session cookie, so signing in or out in one tab changes which account every other
// tab's next request acts as. Each tab's shell announces the session it has just seen, on a BroadcastChannel of this
// origin: only whether someone is signed in and, if so, their user_id. Nothing is stored and no password or token is
// ever announced. The Client listens, so a tab opened for one account stops before acting as another. Where the browser
// has no BroadcastChannel nothing is announced; the Client still checks every account a reply carries.

const NAME = "second-order:session";

/** Who another tab just saw signed in: a user_id, or null when nobody is. */
export interface SessionNews { signedIn: string | null }

let channel: BroadcastChannel | null | undefined;

/** This tab's one channel: a tab never receives its own announcements. */
function open(): BroadcastChannel | null {
  if (channel === undefined) {
    try {
      channel = typeof BroadcastChannel === "function" ? new BroadcastChannel(NAME) : null;
    } catch {
      channel = null;
    }
  }
  return channel;
}

/** An announcement as another tab sent it, or null when it is not one. */
export function readNews(data: unknown): SessionNews | null {
  if (typeof data !== "object" || data === null || !("signedIn" in data)) return null;
  const signedIn = (data as { signedIn: unknown }).signedIn;
  return signedIn === null || (typeof signedIn === "string" && signedIn !== "") ? { signedIn } : null;
}

/** Tell the other tabs who this tab just saw signed in (null: nobody). */
export function announce(signedIn: string | null): void {
  try {
    open()?.postMessage({ signedIn } satisfies SessionNews);
  } catch { /* a closed or unavailable channel announces nothing */ }
}

/** Hear the other tabs' announcements until the returned function is called. */
export function listen(hear: (news: SessionNews) => void): () => void {
  const opened = open();
  if (!opened) return () => undefined;
  const receive = (event: MessageEvent) => {
    const news = readNews(event.data);
    if (news) hear(news);
  };
  opened.addEventListener("message", receive);
  return () => opened.removeEventListener("message", receive);
}
