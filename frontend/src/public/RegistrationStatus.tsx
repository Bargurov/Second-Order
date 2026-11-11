// A registrant's own registration, shown after a sign-in with the right password is refused because the registration
// is waiting for approval or was not approved (docs/onboarding-contract.md section 4). There is no session behind this
// screen: it shows only what the refusal carried, and nothing is read or sent from here.
import { PUBLIC_PATHS } from "../contracts/onboarding.ts";
import type { RegistrationStatus } from "../contracts/user.ts";
import { Link } from "../router";
import { statusView } from "./status.ts";

/** The reader's own time zone, or UTC when the browser does not name one. */
export const viewerZone = () => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
};

export function RegistrationStatusView({ registration, onSignInAgain }: {
  registration: RegistrationStatus; onSignInAgain: () => void;
}) {
  const view = statusView(registration, viewerZone());
  return (
    <section className="public-panel" data-public="status" data-status={registration.status}
             aria-labelledby="status-title">
      <p className="kicker">Your registration</p>
      <h1 id="status-title" tabIndex={-1}>{view.title}</h1>
      <p className="public-status-detail">{view.detail}</p>
      <dl className="ledger public-facts">
        {view.facts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
      </dl>
      <ul className="public-points">{view.next.map((line) => <li key={line}>{line}</li>)}</ul>
      {registration.status === "rejected" &&
        <p><Link to={PUBLIC_PATHS.register}>Register under another username</Link></p>}
      <p className="public-actions">
        <button type="button" className="button button-quiet" onClick={onSignInAgain}>Sign in as someone else</button>
        <Link to={PUBLIC_PATHS.landing}>Back to the start</Link>
        <Link to={PUBLIC_PATHS.credits}>How credits work</Link>
      </p>
    </section>
  );
}
