// What every Client page shares: the contract's request helpers, the account as the server last reported it, the way
// a 401 ends the session, the registry of work typed but not saved (asked about before leaving, held in this tab's
// memory if the session ends, recovery.ts), and the drafts given back after the same user signed in again.
import { createContext, useContext, useEffect } from "react";
import type { NewsApi } from "../contracts/news.ts";
import type { StoriesApi } from "../contracts/stories.ts";
import type { Account, SignedInSession, UserApi } from "../contracts/user.ts";
import { guardLeaving } from "../leave";
import { draftText, type Recoverable } from "./recovery.ts";
import type { Notice, SessionReason } from "./refusals.ts";

export type AccountState =
  | { state: "loading" }
  | { state: "ready"; account: Account; readAt: string }
  | { state: "error"; notice: Notice };

export interface ClientContextValue {
  api: UserApi;
  /** The news, interests, import and limits routes (src/contracts/news.ts), bound to this tab's account like `api`. */
  news: NewsApi;
  /** The stories, topics and Go deeper routes (src/contracts/stories.ts), bound to this tab's account like `api`. */
  stories: StoriesApi;
  session: SignedInSession;
  account: AccountState;
  /** Read the account again (GET only). */
  readAccount: () => Promise<void>;
  /** Adopt the account a quote or run reply carried: the server's figures after that action. */
  adoptAccount: (account: Account) => void;
  /** A request answered 401. */
  endSession: (reason: SessionReason) => void;
  /** Before an action that does not go through `api` (a download link): whether this tab still acts for its own
   * account. When it does not, the tab stops (identity.ts) and this returns false. */
  mayAct: () => boolean;
  setUnsaved: (key: string, draft: Recoverable | null) => void;
  /** Drafts given back after the same user signed in again, by page key, until their page takes them or they are
   * discarded. */
  recovered: Record<string, Recoverable>;
  /** A page took its recovered draft back into its form, or the person discarded it. */
  releaseRecovered: (key: string) => void;
}

export const ClientContext = createContext<ClientContextValue | null>(null);

export function useClient(): ClientContextValue {
  const value = useContext(ClientContext);
  if (!value) throw new Error("Client pages render inside ClientApp");
  return value;
}

export const accountOf = (state: AccountState): Account | null => (state.state === "ready" ? state.account : null);
export const zoneOf = (state: AccountState): string => accountOf(state)?.daily.timezone ?? "UTC";

const LEAVE_QUESTION = "This page has text you have not saved. Leave it?";

/** Register a page's unsaved work under `key` (null when there is none). */
export function useUnsaved(key: string, draft: Recoverable | null): void {
  const { setUnsaved } = useClient();
  const pending = draft !== null && draftText(draft).trim() !== "";
  useEffect(() => {
    setUnsaved(key, pending ? draft : null);
    return () => setUnsaved(key, null);
  }, [key, draft, pending, setUnsaved]);
  useEffect(() => {
    if (!pending) return;
    const release = guardLeaving(() => LEAVE_QUESTION);
    const unload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", unload);
    return () => {
      release();
      window.removeEventListener("beforeunload", unload);
    };
  }, [pending]);
}
