// Credits and holds: the append-only ledger with each user's reconciling totals, and the attempts still holding
// credits. An attempt that cannot settle on its own (a provider error, a lost reply, a send without an outcome) is
// resolved here once, by charging part or all of its quote or returning it, with a reason. Nothing is refunded,
// cleared or retried automatically.
import { useState, type FormEvent } from "react";
import { adminPaths, adminPost, useAdmin, type AdminUser, type AdminWrite, type Balance, type Hold,
  type LedgerEntry } from "./adminApi.ts";
import { ENTITLEMENT_LABEL, seconds, signedCredits, usd, when } from "./adminFormat.ts";

interface LedgerView { entries: LedgerEntry[]; totals: Record<string, Balance>; identity: string }

function Resolve({ hold, done }: { hold: Hold; done: () => void }) {
  const [resolution, setResolution] = useState<"return" | "charge">("return");
  const [charged, setCharged] = useState(String(hold.credits));
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<AdminWrite<unknown> | null>(null);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const outcome = await adminPost(adminPaths.resolve(hold.attempt_id), {
      resolution, credits_charged: resolution === "return" ? 0 : Number(charged), reason, observed: hold.observed });
    setResult(outcome);
    if (outcome.state === "saved") done();
  };
  return (
    <form className="admin-form" onSubmit={(event) => void submit(event)} aria-label={`Resolve ${hold.attempt_id}`}>
      <label>Resolution
        <select name="resolution" value={resolution}
                onChange={(event) => setResolution(event.target.value as "return" | "charge")}>
          <option value="return">Return all {hold.credits} credits and the daily slot</option>
          <option value="charge">Charge credits (at most {hold.credits})</option>
        </select>
      </label>
      {resolution === "charge" && (
        <label>Credits charged
          <input name="credits_charged" inputMode="numeric" value={charged} required pattern="[0-9]+"
                 onChange={(event) => setCharged(event.target.value)} />
        </label>
      )}
      <label>Reason (for example what the provider's Console shows)
        <input name="reason" value={reason} required maxLength={500} onChange={(event) => setReason(event.target.value)} />
      </label>
      <button type="submit" className="button">Resolve once</button>
      {result && result.state !== "saved" && <p className="admin-problem" role="alert">{result.message}{" "}
        <button type="button" className="admin-link" onClick={done}>Reload</button></p>}
    </form>
  );
}

export function AdminLedger() {
  const [version, setVersion] = useState(0);
  const [user, setUser] = useState("");
  const users = useAdmin<{ users: AdminUser[] }>(adminPaths.users, version);
  const ledger = useAdmin<LedgerView>(adminPaths.ledger(user || undefined), version);
  const holds = useAdmin<{ holds: Hold[] }>(adminPaths.holds, version);
  const reload = () => setVersion((value) => value + 1);
  const names = users.state === "ready"
    ? Object.fromEntries(users.data.users.map((row) => [row.user_id, row.display_name])) : {};
  const name = (id: string) => names[id] ?? (id === "system" ? "System" : id);
  return (
    <section className="admin-section">
      <p className="kicker">Credits</p>
      <h1>Holds and the credit ledger</h1>
      <h2>Holds</h2>
      {holds.state === "loading" && <p role="status">Loading the holds…</p>}
      {holds.state === "error" && <p className="admin-problem" role="alert">{holds.message}</p>}
      {holds.state === "ready" && (holds.data.holds.length === 0 ? <p className="muted">No credits are held.</p> : (
        <ul className="admin-holds">
          {holds.data.holds.map((hold) => (
            <li key={hold.attempt_id} data-attempt={hold.attempt_id} data-state={hold.entitlement?.state}>
              <p><strong>{name(hold.user_id)}</strong> · {hold.credits} credits held since {when(hold.reserved_at)} ·{" "}
                {hold.effort} Effort · <span className="admin-state">{ENTITLEMENT_LABEL[hold.entitlement?.state ?? ""]
                  ?? "Held"}</span></p>
              <p className="muted">Attempt {hold.attempt_state}{hold.outcome ? `, outcome ${hold.outcome}` : ""} ·
                send recorded {when(hold.timing?.sent_at)} · elapsed {seconds(hold.timing?.elapsed_seconds)} ·
                provider HTTP status {hold.http_status ?? "none recorded"} · planning estimate{" "}
                {usd(hold.planning_estimate_usd)}</p>
              {hold.resolvable ? <Resolve hold={hold} done={reload} />
                : <p className="muted">{hold.worker_active
                  ? "A worker is still running this attempt; it cannot be resolved until that worker stops."
                  : "Not yet eligible: it can be resolved once an outcome is recorded or 15 minutes have passed."}</p>}
            </li>
          ))}
        </ul>
      ))}
      <h2>Ledger</h2>
      <label className="admin-filter">Account
        <select value={user} onChange={(event) => setUser(event.target.value)}>
          <option value="">All users</option>
          {users.state === "ready" && users.data.users.filter((row) => row.role === "user").map((row) => (
            <option key={row.user_id} value={row.user_id}>{row.display_name}</option>
          ))}
        </select>
      </label>
      {ledger.state === "loading" && <p role="status">Loading the ledger…</p>}
      {ledger.state === "error" && <p className="admin-problem" role="alert">{ledger.message}</p>}
      {ledger.state === "ready" && <>
        <p className="muted">Each total reconciles when {ledger.data.identity}.</p>
        <ul className="admin-totals">
          {Object.entries(ledger.data.totals).map(([id, balance]) => (
            <li key={id} data-user-total={id}>
              <strong>{name(id)}</strong>: {balance.granted} granted {signedCredits(balance.corrections)} corrected −{" "}
              {balance.charged} charged − {balance.held} held = {balance.available} available ·{" "}
              <span className={balance.reconciles ? "admin-ok" : "admin-problem"}>
                {balance.reconciles ? "reconciles" : "does not reconcile"}</span>
            </li>
          ))}
        </ul>
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead><tr><th>Time</th><th>Account</th><th>Entry</th><th>Credits</th><th>By</th><th>Reason</th></tr></thead>
            <tbody>
              {ledger.data.entries.slice().reverse().map((entry) => (
                <tr key={entry.entry_id} data-kind={entry.kind}>
                  <td>{when(entry.at)}</td><td>{name(entry.user_id)}</td><td>{entry.kind}</td>
                  <td className="admin-number">{signedCredits(entry.amount)}</td><td>{name(entry.actor)}</td>
                  <td>{entry.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </>}
    </section>
  );
}
