// The shared shell of both builds: it asks the server who is signed in (GET /api/session), shows the signed-out pages
// when nobody is (the Client build's public pages, docs/onboarding-contract.md section 7; the Admin build's sign-in
// form), and mounts the role's app. The server decides the role and serves each role its own build (the Admin build
// to admins, the Client build to users and signed-out visitors), so a build that meets the other role reloads once to
// receive the right one. Nothing here grants anything: every API route checks the session and role again. Each session
// this shell sees is announced to the browser's other tabs (sessionChannel.ts), which share its cookie.
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import type { PublicAppProps } from "../contracts/onboarding.ts";
import {
  userApi, type SignedInSession, type SignedOutReason, type Role, type Session,
} from "../contracts/user.ts";
import { announce } from "./sessionChannel.ts";
import { SignIn } from "./SignIn";
import "./shell.css";

export type Build = "admin" | "client";
const ROLE_FOR: Record<Build, Role> = { admin: "admin", client: "user" };
const RELOADED = "second-order:role-reload";
const api = userApi();

/** What the shell gives the mounted app. */
export interface ShellProps {
  session: SignedInSession;
  signOut: () => Promise<void>;
  sessionEnded: (reason: "not_signed_in" | "session_expired") => void;
}

type ShellState =
  | { state: "loading" }
  | { state: "signed-out"; reason: SignedOutReason }
  | { state: "signed-in"; session: SignedInSession }
  | { state: "other-role"; session: SignedInSession }
  | { state: "error"; message: string };

function reloadOnce(): boolean {
  try {
    if (window.sessionStorage.getItem(RELOADED)) return false;
    window.sessionStorage.setItem(RELOADED, "1");
  } catch {
    return false;
  }
  window.location.reload();
  return true;
}

function settled(): void {
  try {
    window.sessionStorage.removeItem(RELOADED);
  } catch { /* storage unavailable: nothing to clear */ }
}

/** `signedOut` renders what a signed-out visitor sees; without it, the sign-in form. */
export function Shell({ build, render, signedOut }: {
  build: Build; render: (props: ShellProps) => ReactNode; signedOut?: (props: PublicAppProps) => ReactNode;
}) {
  const [shown, setShown] = useState<ShellState>({ state: "loading" });
  /** The account this page was opened for: its sign-out names it, so a tab left open after a sign-in elsewhere cannot
   * end someone else's session unseen (docs/account-binding-contract.md section 3). */
  const opened = useRef<string | null>(null);

  const show = useCallback((session: Session) => {
    opened.current = session.state === "signed_in" ? session.user.user_id : null;
    // Every tab of this browser shares the session just seen: tell the others (sessionChannel.ts).
    announce(opened.current);
    if (session.state === "signed_out") {
      settled();
      setShown({ state: "signed-out", reason: session.reason });
    } else if (session.user.role === ROLE_FOR[build]) {
      settled();
      setShown({ state: "signed-in", session });
    } else if (!reloadOnce()) {
      setShown({ state: "other-role", session });
    }
  }, [build]);

  const load = useCallback(async () => {
    setShown({ state: "loading" });
    const reply = await api.session();
    if (reply.state === "ok") show(reply.data);
    else setShown({ state: "error", message: reply.state === "refused" ? reply.error.detail : reply.message });
  }, [show]);

  useEffect(() => { void load(); }, [load]);

  const signOut = useCallback(async () => {
    const reply = await userApi(undefined, opened.current === null ? null : { account: opened.current }).signOut();
    if (reply.state === "ok") show(reply.data);
    else setShown({ state: "error", message: reply.state === "refused" ? reply.error.detail : reply.message });
  }, [show]);

  const sessionEnded = useCallback((reason: "not_signed_in" | "session_expired") => {
    setShown({ state: "signed-out", reason });
  }, []);

  if (shown.state === "loading") return <p className="shell-status" role="status">Checking your session…</p>;
  if (shown.state === "error") {
    return (
      <main className="shell-panel" role="alert">
        <p className="kicker">Session</p>
        <h1>The session could not be checked</h1>
        <p>{shown.message}</p>
        <button type="button" className="button" onClick={() => void load()}>Check again</button>
      </main>
    );
  }
  if (shown.state === "signed-out") {
    const props: PublicAppProps = { reason: shown.reason, onSignedIn: (session) => show(session) };
    return <>{signedOut ? signedOut(props) : <main><SignIn {...props} /></main>}</>;
  }
  if (shown.state === "other-role") {
    return (
      <main className="shell-panel" role="alert">
        <p className="kicker">Session</p>
        <h1>This page is not for your account</h1>
        <p>You are signed in as {shown.session.user.display_name}. Reload the page, or sign out and sign in with
          another account.</p>
        {shown.session.mode === "accounts" &&
          <button type="button" className="button" onClick={() => void signOut()}>Sign out</button>}
      </main>
    );
  }
  return <>{render({ session: shown.session, signOut, sessionEnded })}</>;
}
