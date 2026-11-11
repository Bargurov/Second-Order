// Which account this tab acts for. A Client tab is opened for one signed-in account, but the browser keeps one session
// cookie for all its tabs: after a sign-in as someone else in another tab, this tab's next request would act as that
// account. The tab therefore stops as soon as it learns of it: from another tab's announcement
// (src/shell/sessionChannel.ts), or from any reply that carries another account. A stopped tab sends nothing more, so
// it never saves to, reads from or shows another account under this one's name; what was typed stays for this account
// only (recovery.ts). The server is the authority: every request names the tab's account (account binding,
// docs/account-binding-contract.md), and a request bound to another account than the browser's session is refused
// (401 account_changed) before anything is read or written; that refusal stops the tab too.
import { readError, type Account } from "../contracts/user.ts";

export type Identity =
  /** The browser's session is, as far as this tab knows, the account it was opened for. */
  | { state: "bound" }
  /** Another tab signed this browser in to another account. Nothing is sent from here; the person is told, and their
   * next action here shows why it stopped. */
  | { state: "elsewhere" }
  /** Stopped and shown: from here only signing in again (or reloading) continues. */
  | { state: "stopped" };

export const BOUND: Identity = { state: "bound" };

/** Another tab saw `signedIn` (a user_id, or nobody). Signing out elsewhere changes nothing here: this tab's next
 * request is answered as signed out, and the session-end recovery applies. Signing in again as this same account lifts
 * a warning that has not stopped the tab yet. */
export function afterAnnouncement(current: Identity, userId: string, signedIn: string | null): Identity {
  if (current.state === "stopped" || signedIn === null) return current;
  return signedIn === userId ? BOUND : { state: "elsewhere" };
}

/** Whether this tab may send a request now. */
export const maySend = (identity: Identity): boolean => identity.state === "bound";

/** Whether an account a reply carried is this tab's own: one that is not must never be shown or adopted here. */
export const isOwn = (account: Account, userId: string): boolean => account.user.user_id === userId;

/** Whether a response is the server's refusal of a request bound to another account (401 account_changed, read by the
 * contract's reader). The response itself is left unread for its caller. */
export async function changedAccount(response: Response): Promise<boolean> {
  if (response.status !== 401) return false;
  const body: unknown = await response.clone().json().catch(() => null);
  const error = readError(body);
  return error.ok && error.value.code === "account_changed";
}
