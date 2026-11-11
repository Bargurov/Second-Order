// The sign-in form both builds show when nobody is signed in. The password goes only to POST /api/session/login with
// this page's session header; the server sets an HttpOnly cookie that no script reads. The password field is cleared
// after every reply, so it never outlives the one request. A registration that is waiting for approval or was not
// approved comes back inside the refusal (docs/onboarding-contract.md section 4; there is no session for it) and is
// handed to `onRegistration` when the page shows it. An unconfirmed reply proves nothing: the password is never sent
// again on its own, and the person may ask whether a session exists (GET /api/session, a read).
import { useRef, useState, type FormEvent, type ReactNode } from "react";
import {
  userApi, type RegistrationStatus, type Session, type SignedOutReason,
} from "../contracts/user.ts";
import { signInOutcome } from "../public/signIn.ts";

const REASON_TEXT: Record<SignedOutReason, string | null> = {
  not_signed_in: null,
  session_expired: "Your session has ended. Sign in again to continue.",
  signed_out: "You are signed out.",
};

export interface SignInProps {
  reason: SignedOutReason;
  onSignedIn: (session: Session) => void;
  /** Show a registrant's own registration; without it, the refusal's text is shown here. */
  onRegistration?: (registration: RegistrationStatus) => void;
  /** A username to start with (after a registration check). */
  username?: string;
  /** A line about why this form is shown here. */
  context?: ReactNode;
  footer?: ReactNode;
}

export function SignIn({ reason, onSignedIn, onRegistration, username: initial = "", context, footer }: SignInProps) {
  const [username, setUsername] = useState(initial);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [unsure, setUnsure] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const sending = useRef(false);
  const passwordField = useRef<HTMLInputElement>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (sending.current) return;  // Two presses delivered together still send once.
    sending.current = true;
    setBusy(true);
    setProblem(null);
    setUnsure(null);
    setNote(null);
    const reply = await userApi().signIn(username.trim(), password);
    setPassword("");
    sending.current = false;
    setBusy(false);
    const outcome = signInOutcome(reply);
    if (outcome.kind === "signed-in") return onSignedIn(outcome.session);
    if (outcome.kind === "registration" && onRegistration) return onRegistration(outcome.registration);
    if (outcome.kind === "unconfirmed") setUnsure(outcome.detail);
    else setProblem(outcome.kind === "registration" ? outcome.registration.detail : outcome.detail);
    passwordField.current?.focus();
  };

  const checkSession = async () => {
    if (sending.current) return;
    sending.current = true;
    setBusy(true);
    const reply = await userApi().session();
    sending.current = false;
    setBusy(false);
    if (reply.state === "ok" && reply.data.state === "signed_in") return onSignedIn(reply.data);
    if (reply.state === "ok") {
      setUnsure(null);
      setNote("You are not signed in. Type your password to sign in.");
      passwordField.current?.focus();
    } else {
      setUnsure(`${reply.state === "refused" ? reply.error.detail : reply.message} Whether you are signed in is ` +
        "still unknown.");
    }
  };

  return (
    <div className="shell-panel shell-sign-in">
      <p className="kicker">Second Order</p>
      <h1 tabIndex={-1}>Sign in</h1>
      {REASON_TEXT[reason] && <p className="shell-note" role="status">{REASON_TEXT[reason]}</p>}
      {context && <p className="shell-context">{context}</p>}
      <form onSubmit={(event) => void submit(event)} className="shell-form">
        <label>
          Username
          <input name="username" autoComplete="username" autoCapitalize="none" spellCheck={false} value={username}
                 required onChange={(event) => setUsername(event.target.value)} />
        </label>
        <label>
          Password
          <input name="password" type="password" autoComplete="current-password" value={password} required
                 ref={passwordField} onChange={(event) => setPassword(event.target.value)} />
        </label>
        {problem && <p className="shell-problem" role="alert">{problem}</p>}
        {note && <p className="shell-note" role="status">{note}</p>}
        {unsure && (
          <div className="shell-unsure" role="alert" data-sign-in="unconfirmed">
            <p>{unsure}</p>
            <button type="button" className="button button-quiet" disabled={busy} onClick={() => void checkSession()}>
              Check whether you are signed in</button>
          </div>
        )}
        <button type="submit" className="button" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
      <div className="muted shell-footnote">{footer ?? "The administrator of this server approves every account."}</div>
    </div>
  );
}
