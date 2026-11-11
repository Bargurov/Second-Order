// Registration (POST /api/public/registrations): an ordinary account that waits for an administrator's approval.
// The form follows registerForm.ts: it checks each field by the server's rules, sends exactly four fields once per
// submit, and after a refusal or an unconfirmed reply keeps what was typed except both password fields. After an
// unconfirmed reply the person may check by signing in, or type the password again and register. The password stays
// in this form's state only while it is typed; nothing is stored, replayed or retried.
import { useEffect, useMemo, useReducer, useRef, type FormEvent, type ReactNode } from "react";
import { PUBLIC_PATHS, REGISTRATION_RULES, onboardingApi } from "../contracts/onboarding.ts";
import { Link } from "../router";
import {
  emptyRegister, reduceRegister, toSend, type DraftField, type RegisterEvent,
} from "./registerForm.ts";
import { viewerZone } from "./RegistrationStatus";
import { statusView } from "./status.ts";
import { inZone } from "../client/time.ts";

const ORDER: DraftField[] = ["username", "display_name", "password", "repeat", "note"];

const NEXT = [
  "An administrator approves or declines each registration. Nothing can be used until then.",
  "Approval alone allocates nothing: the administrator then allocates credits and a daily allowance, separately.",
  "Sign in to see your registration's status. No e-mail is sent.",
  "There is no password reset here, so keep your password safe.",
];

export function Register({ onCheck }: { onCheck: (username: string) => void }) {
  const api = useMemo(() => onboardingApi(), []);
  const [state, dispatch] = useReducer(reduceRegister, emptyRegister);
  const busy = useRef(false);
  const focusNext = useRef<"errors" | "heading" | "unconfirmed" | null>(null);
  const fields = useRef<Partial<Record<DraftField, HTMLInputElement | HTMLTextAreaElement | null>>>({});
  const heading = useRef<HTMLHeadingElement>(null);
  const unsure = useRef<HTMLDivElement>(null);

  useEffect(() => { document.title = "Register · Second Order"; }, []);
  useEffect(() => {  // After a submit or a reply, focus goes where the person must look next.
    const target = focusNext.current;
    focusNext.current = null;
    if (target === "errors") fields.current[ORDER.find((field) => state.errors[field]) ?? "username"]?.focus();
    if (target === "heading") heading.current?.focus();
    if (target === "unconfirmed") unsure.current?.focus();
  }, [state]);

  /** Apply the person's submit, and send the one body it allows: one request, never repeated by itself. */
  const act = async () => {
    if (busy.current) return;  // Two presses delivered together still send once.
    const event: RegisterEvent = { type: "submit" };
    const next = reduceRegister(state, event);
    dispatch(event);
    const body = toSend(next);
    if (!body) {
      if (Object.keys(next.errors).length > 0) focusNext.current = "errors";
      return;
    }
    busy.current = true;
    const reply = await api.register(body);
    busy.current = false;
    const after = reduceRegister(next, { type: "reply", reply });
    focusNext.current = after.phase === "received" ? "heading" : after.unconfirmed ? "unconfirmed"
      : Object.keys(after.errors).length > 0 ? "errors" : null;
    dispatch({ type: "reply", reply });
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    void act();
  };

  if (state.phase === "received" && state.received) {
    const { registration, duplicate } = state.received;
    const view = statusView(registration, viewerZone());
    return (
      <section className="public-panel" data-public="registered" aria-labelledby="registered-title">
        <p className="kicker">Registration</p>
        <h1 id="registered-title" ref={heading} tabIndex={-1}>Registration received</h1>
        {duplicate && <p className="public-note">This registration had already been received on{" "}
          {inZone(registration.submitted_at, viewerZone())}. Nothing new was recorded.</p>}
        <p className="public-status-detail">{registration.detail}</p>
        <dl className="ledger public-facts">
          {view.facts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
        </dl>
        <h2>What happens next</h2>
        <ul className="public-points">{view.next.map((line) => <li key={line}>{line}</li>)}</ul>
        <p className="public-actions">
          <Link className="button" to={PUBLIC_PATHS.signIn}>Sign in to see the status</Link>
          <Link to={PUBLIC_PATHS.credits}>How credits work</Link>
          <Link to={PUBLIC_PATHS.landing}>Back to the start</Link>
        </p>
      </section>
    );
  }

  const locked = state.phase !== "editing";
  const field = (name: DraftField, label: string, hint: ReactNode, input: Record<string, unknown> = {}) => {
    const error = state.errors[name];
    const props = {
      id: `register-${name}`, name, value: state.draft[name], readOnly: locked,
      "aria-invalid": error ? true : undefined,
      "aria-describedby": `register-${name}-hint${error ? ` register-${name}-error` : ""}`,
      onChange: (event: { target: { value: string } }) => dispatch({ type: "edit", field: name, value: event.target.value }),
      ref: (element: HTMLInputElement | HTMLTextAreaElement | null) => { fields.current[name] = element; },
      ...input,
    };
    return (
      <div className="public-field">
        <label htmlFor={`register-${name}`}>{label}</label>
        {name === "note" ? <textarea rows={3} {...props} /> : <input {...props} />}
        <p id={`register-${name}-hint`} className="public-hint">{hint}</p>
        {error && <p id={`register-${name}-error`} className="public-field-error" data-field-error={name}>{error}</p>}
      </div>
    );
  };

  return (
    <div className="public-register-layout">
      <section className="public-panel" aria-labelledby="register-title">
        <p className="kicker">Registration</p>
        <h1 id="register-title" tabIndex={-1}>Register</h1>
        <p className="public-lede is-small">Ask for an account on this server. An administrator approves each one.</p>
        <form className="public-register shell-form" noValidate onSubmit={submit} aria-labelledby="register-title">
          {field("username", "Username", "3 to 40 lowercase letters, digits, dots, hyphens or underscores, starting " +
            "with a letter or digit. You sign in with it.",
            { autoComplete: "username", autoCapitalize: "none", spellCheck: false, maxLength: 40 })}
          {field("display_name", "Display name", "How your name appears on your reviews. Up to " +
            `${REGISTRATION_RULES.maxDisplayName} characters.`, { autoComplete: "name", maxLength: REGISTRATION_RULES.maxDisplayName })}
          {field("password", "Password", `${REGISTRATION_RULES.minPassword} to ${REGISTRATION_RULES.maxPassword} ` +
            "characters. It cannot be reset here.",
            { type: "password", autoComplete: "new-password", maxLength: REGISTRATION_RULES.maxPassword })}
          {field("repeat", "Password again", "The same password, to catch a typing mistake. It is not sent.",
            { type: "password", autoComplete: "new-password", maxLength: REGISTRATION_RULES.maxPassword })}
          {field("note", "Note for the administrator (optional)",
            <>One paragraph, up to {REGISTRATION_RULES.maxNote} characters; only the administrator reads it.{" "}
              <span className="public-count">{state.draft.note.length} of {REGISTRATION_RULES.maxNote}</span></>,
            { maxLength: REGISTRATION_RULES.maxNote })}

          {state.notice && state.notice.tone === "refused" && (
            <div className="public-notice" role="alert">
              <p className="public-notice-title">{state.notice.title}</p>
              <p>{state.notice.detail}</p>
            </div>
          )}

          {state.unconfirmed && state.notice && (
            <div className="public-notice is-unconfirmed" role="alert" tabIndex={-1} ref={unsure}
                 data-public="unconfirmed">
              <p className="public-notice-title">{state.notice.title}</p>
              <p>{state.notice.detail}</p>
              <p className="public-actions">
                <button type="button" className="button button-quiet" onClick={() => onCheck(state.draft.username)}>
                  Check by signing in</button>
              </p>
            </div>
          )}
          <button type="submit" className="button" disabled={state.phase === "sending"}>
            {state.phase === "sending" ? "Registering…" : state.unconfirmed ? "Register again" : "Register"}</button>
        </form>
      </section>
      <aside className="public-register-aside" aria-labelledby="register-next-title">
        <h2 id="register-next-title">What happens next</h2>
        <ol className="public-points">{NEXT.map((line) => <li key={line}>{line}</li>)}</ol>
        <p className="public-footnote">Already registered? <Link to={PUBLIC_PATHS.signIn}>Sign in</Link> to see your
          registration's status. <Link to={PUBLIC_PATHS.credits}>How credits work</Link></p>
      </aside>
    </div>
  );
}
