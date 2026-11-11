// Registrations: public sign-ups waiting for a decision, and the decisions already made (docs/onboarding-contract.md).
// Each decision is one attributed POST with a reason, made once: approving activates the account and nothing else, so
// credits and a daily limit are still set under Users; rejecting keeps it closed for good. A decision that another
// administrator made first is reported as theirs, never as saved. Decisions name the administrator who made them, and
// an approved account with nothing allocated yet links to its panel under Users, where the allocation is made.
import { useState, type FormEvent } from "react";
import { Link } from "../router";
import { adminPaths, adminPost, useAdmin, type AdminUser, type AdminWrite } from "./adminApi.ts";
import { manageHref, nameOf, offersInitialAllocation, when } from "./adminFormat.ts";

const STATUS_LABEL: Record<AdminUser["status"], string> = {
  pending: "Waiting for a decision", rejected: "Rejected", active: "Approved · active", disabled: "Approved · deactivated",
};

function Decision({ user, done }: { user: AdminUser; done: () => void }) {
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<AdminWrite<unknown> | null>(null);
  const decide = async (event: FormEvent, decision: "approve" | "reject") => {
    event.preventDefault();
    const outcome = await adminPost(adminPaths.decision(user.user_id), { decision, reason });
    setResult(outcome);
    if (outcome.state === "saved") done();
  };
  return (
    <form className="admin-form" onSubmit={(event) => void decide(event, "approve")}
          aria-label={`Decision on ${user.username}`}>
      <label>Reason (recorded, not shown to the registrant)
        <input name="reason" value={reason} required maxLength={500} onChange={(event) => setReason(event.target.value)} />
      </label>
      <button type="submit" className="button">Approve (activates the account only)</button>
      <button type="button" className="button" disabled={!reason.trim()}
              onClick={(event) => void decide(event, "reject")}>Reject</button>
      {result && result.state !== "saved" && <p className="admin-problem" role="alert">{result.message}</p>}
    </form>
  );
}

export function AdminRegistrations() {
  const [version, setVersion] = useState(0);
  const read = useAdmin<{ registrations: AdminUser[] }>(adminPaths.registrations, version);
  // The users list names the deciding administrators and says what each approved account has been allocated.
  const accounts = useAdmin<{ users: AdminUser[] }>(adminPaths.users, version);
  const reload = () => setVersion((value) => value + 1);
  if (read.state === "loading") return <p role="status">Loading the registrations…</p>;
  if (read.state === "error") return <p className="admin-problem" role="alert">{read.message}</p>;
  const pending = read.data.registrations.filter((user) => user.status === "pending");
  const decided = read.data.registrations.filter((user) => user.status !== "pending");
  const users = accounts.state === "ready" ? accounts.data.users : [];
  return (
    <section className="admin-section">
      <p className="kicker">Accounts</p>
      <h1>Registrations</h1>
      <p className="lede">A registration is an ordinary user account that cannot sign in until it is approved. Approval
        grants no credits and sets no daily limit: allocate those under <Link to="/admin">Users</Link> afterwards.</p>
      {accounts.state === "error" && <p className="admin-problem" role="alert" data-accounts="unread">The accounts could
        not be read ({accounts.message}), so deciding administrators are named by their IDs and allocations are not
        shown.</p>}
      <h2>Waiting ({pending.length})</h2>
      {pending.length === 0 ? <p data-registrations="none">No registration is waiting.</p> : pending.map((user) => (
        <div className="admin-panel" key={user.user_id} data-registration={user.username}>
          <h3>{user.display_name} <code>{user.username}</code></h3>
          <p>Registered {when(user.registration?.submitted_at)}.{" "}
            {user.registration?.note ? <>Note: “{user.registration.note}”</> : "No note."}</p>
          <Decision user={user} done={reload} />
        </div>
      ))}
      <h2>Decided</h2>
      <ul>{decided.map((user) => {
        const account = users.find((row) => row.user_id === user.user_id);
        return (
          <li key={user.user_id} data-registration={user.username}>
            {user.display_name} (<code>{user.username}</code>) · {STATUS_LABEL[user.status]} ·{" "}
            {user.registration?.decision ? <>{user.registration.decision.decision} {when(user.registration.decision.decided_at)}
              {" "}by <span data-decided-by>{nameOf(user.registration.decision.decided_by, users)}</span> ·{" "}
              {user.registration.decision.reason}</> : null}
            {account && offersInitialAllocation(account) && <> · <span data-allocation="none">nothing allocated
              yet</span> · <Link to={manageHref(user.username)}>Allocate under Users</Link></>}
          </li>
        );
      })}</ul>
    </section>
  );
}
