// Accounts: each user's balance, held credits, daily limit and today's use, with the administrator's explicit actions
// (grant or correct credits, set the daily limit, activate or deactivate) and a form for a new account. Every action
// is one attributed POST with a reason; a credit entry carries an idempotency key, so a repeated submission adds
// nothing. For an approved account with nothing allocated, the operator's selected initial allocation can fill the
// credit and limit forms; each is still submitted on its own, with its own reason. The screen first says what waits:
// registrations to decide and approved accounts with nothing allocated, read from the same list. /admin?manage=<username>
// opens that account's panel (the Registrations screen links there after an approval); opening it changes nothing.
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useLocation } from "../router";
import {
  adminPaths, adminPost, newKey, useAdmin, type AdminUser, type AdminWrite, type AllocationPreset,
} from "./adminApi.ts";
import {
  STATUS_LABEL, count, manageTarget, needsAttention, offersInitialAllocation, unapproved, when,
} from "./adminFormat.ts";

interface UsersView { users: AdminUser[]; quota_timezone: string; allocation_presets: AllocationPreset[] }

function Result({ result }: { result: AdminWrite<unknown> | null }) {
  if (!result) return null;
  return result.state === "saved" ? <p className="admin-ok" role="status">Saved.</p>
    : <p className="admin-problem" role="alert">{result.message}</p>;
}

function CreditForm({ user, done, initial = "" }: { user: AdminUser; done: () => void; initial?: string }) {
  const [kind, setKind] = useState<"grant" | "correction">("grant");
  const [amount, setAmount] = useState(initial);
  const [reason, setReason] = useState("");
  const [key, setKey] = useState(newKey);
  const [result, setResult] = useState<AdminWrite<unknown> | null>(null);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const outcome = await adminPost(adminPaths.user(user.user_id, "credits"),
                                    { kind, credits: Number(amount), reason, idempotency_key: key });
    setResult(outcome);
    if (outcome.state === "saved") {
      setKey(newKey());  // The next submission is a new entry.
      setAmount("");
      setReason("");
      done();
    }
  };
  return (
    <form className="admin-form" onSubmit={(event) => void submit(event)} aria-label={`Credits for ${user.username}`}>
      <label>Entry
        <select name="kind" value={kind} onChange={(event) => setKind(event.target.value as "grant" | "correction")}>
          <option value="grant">Grant (adds credits)</option>
          <option value="correction">Correction (adds or removes)</option>
        </select>
      </label>
      <label>Credits
        <input name="credits" inputMode="numeric" value={amount} required pattern="-?[0-9]+"
               onChange={(event) => setAmount(event.target.value)} />
      </label>
      <label>Reason
        <input name="reason" value={reason} required maxLength={500} onChange={(event) => setReason(event.target.value)} />
      </label>
      <button type="submit" className="button">Record entry</button>
      <Result result={result} />
    </form>
  );
}

function LimitForm({ user, done, initial }: { user: AdminUser; done: () => void; initial?: string }) {
  const [limit, setLimit] = useState(initial ??
    (user.daily?.limit === null || user.daily === undefined ? "" : String(user.daily.limit)));
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<AdminWrite<unknown> | null>(null);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const outcome = await adminPost(adminPaths.user(user.user_id, "daily-limit"), { limit: Number(limit), reason });
    setResult(outcome);
    if (outcome.state === "saved") done();
  };
  return (
    <form className="admin-form" onSubmit={(event) => void submit(event)} aria-label={`Daily limit for ${user.username}`}>
      <label>Analyses per day
        <input name="limit" inputMode="numeric" value={limit} required pattern="[0-9]+"
               onChange={(event) => setLimit(event.target.value)} />
      </label>
      <label>Reason
        <input name="reason" value={reason} required maxLength={500} onChange={(event) => setReason(event.target.value)} />
      </label>
      <button type="submit" className="button">Set daily limit</button>
      <Result result={result} />
    </form>
  );
}

/** Values the initial allocation filled in, per form, until that form is saved. */
interface Filled { credits?: string; limit?: string }

/** The credit and limit forms; for an approved account with nothing allocated, the selected initial allocation can
 * fill both. Each form is still submitted on its own, with its own reason, and a saved form is not filled again. */
function Allocation({ user, presets, filled, fill, done }: {
  user: AdminUser; presets: AllocationPreset[]; filled: Filled; fill: (next: Filled) => void; done: () => void;
}) {
  return <>
    {offersInitialAllocation(user) && presets.map((preset) => (
      <div key={preset.preset} className="admin-panel" data-preset={preset.preset}>
        <p><strong>{preset.label}</strong>. {preset.note}</p>
        <button type="button" className="button"
                onClick={() => fill({ credits: String(preset.credits), limit: String(preset.daily_limit) })}>
          Fill both forms ({preset.credits} credits, {preset.daily_limit} a day)</button>
      </div>
    ))}
    <h3>Credits</h3>
    <CreditForm key={`credits-${filled.credits ?? ""}`} user={user} initial={filled.credits ?? ""}
                done={() => { fill({ ...filled, credits: undefined }); done(); }} />
    <h3>Daily analysis limit</h3>
    <LimitForm key={`limit-${filled.limit ?? ""}`} user={user} initial={filled.limit}
               done={() => { fill({ ...filled, limit: undefined }); done(); }} />
  </>;
}

function StatusForm({ user, done }: { user: AdminUser; done: () => void }) {
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<AdminWrite<unknown> | null>(null);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const outcome = await adminPost(adminPaths.user(user.user_id, "status"), { active: !user.active, reason });
    setResult(outcome);
    if (outcome.state === "saved") done();
  };
  return (
    <form className="admin-form" onSubmit={(event) => void submit(event)} aria-label={`Status of ${user.username}`}>
      <label>Reason
        <input name="reason" value={reason} required maxLength={500} onChange={(event) => setReason(event.target.value)} />
      </label>
      <button type="submit" className="button">{user.active ? "Deactivate (ends sessions)" : "Activate"}</button>
      <Result result={result} />
    </form>
  );
}

function NewAccount({ done }: { done: () => void }) {
  const [form, setForm] = useState({ username: "", display_name: "", role: "user", password: "" });
  const [result, setResult] = useState<AdminWrite<unknown> | null>(null);
  const set = (field: keyof typeof form) => (event: { target: { value: string } }) =>
    setForm((value) => ({ ...value, [field]: event.target.value }));
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const outcome = await adminPost(adminPaths.users, form);
    setResult(outcome);
    if (outcome.state === "saved") {
      setForm({ username: "", display_name: "", role: "user", password: "" });
      done();
    }
  };
  return (
    <form className="admin-form admin-new-account" onSubmit={(event) => void submit(event)} aria-label="New account">
      <label>Username<input name="username" value={form.username} required onChange={set("username")} /></label>
      <label>Display name<input name="display_name" value={form.display_name} required onChange={set("display_name")} /></label>
      <label>Role
        <select name="role" value={form.role} onChange={set("role")}>
          <option value="user">User</option>
          <option value="admin">Administrator</option>
        </select>
      </label>
      <label>Initial password
        <input name="password" type="password" autoComplete="new-password" value={form.password} required
               minLength={10} onChange={set("password")} />
      </label>
      <button type="submit" className="button">Create account</button>
      <Result result={result} />
    </form>
  );
}

/** What waits for the administrator, read from the users list: registrations to decide (on Registrations) and active
 * accounts with nothing allocated yet (each name opens its panel). Pointing them out changes nothing. */
function Attention({ users, manage }: { users: AdminUser[]; manage: (user: AdminUser) => void }) {
  const { waiting, unallocated } = needsAttention(users);
  if (waiting.length === 0 && unallocated.length === 0) {
    return <p className="admin-attention muted" data-attention="none">No registration is waiting for a decision, and no
      active account is waiting for its first allocation.</p>;
  }
  return (
    <div className="admin-attention" aria-label="Needs attention">
      {waiting.length > 0 && (
        <p data-attention="waiting">{count(waiting.length, "registration is", "registrations are")} waiting for a
          decision: {waiting.map((user) => user.display_name).join(", ")}.{" "}
          <Link to="/admin/registrations">Decide under Registrations</Link></p>
      )}
      {unallocated.length > 0 && (
        <p data-attention="unallocated">{count(unallocated.length, "active account has", "active accounts have")}{" "}
          nothing allocated yet:{" "}
          {unallocated.map((user, index) => <span key={user.user_id}>{index > 0 && ", "}
            <button type="button" className="admin-link" data-manage={user.username}
                    onClick={() => manage(user)}>{user.display_name}</button></span>)}.
          {" "}Approval grants nothing: credits and a daily limit are each set in the account's panel.</p>
      )}
    </div>
  );
}

export function AdminUsers() {
  const [version, setVersion] = useState(0);
  const [open, setOpen] = useState<string | null>(null);
  const [reveal, setReveal] = useState(0);  // Bumped when a link or a name opens a panel, to bring it into view.
  const [missing, setMissing] = useState<string | null>(null);
  const [filled, setFilled] = useState<Record<string, Filled>>({});  // Kept across the reload after each save.
  const read = useAdmin<UsersView>(adminPaths.users, version);
  const reload = () => setVersion((value) => value + 1);
  const panel = useRef<HTMLDivElement>(null);
  const { search } = useLocation();
  const applied = useRef<string | null>(null);
  const manage = (user: AdminUser) => {
    setOpen(user.user_id);
    setReveal((value) => value + 1);
  };
  useEffect(() => {  // /admin?manage=<username>: open that account's panel once per address.
    const wanted = manageTarget(search);
    if (read.state !== "ready" || wanted === null || applied.current === search) return;
    applied.current = search;
    const user = read.data.users.find((row) => row.username === wanted);
    setMissing(user ? null : wanted);
    if (user) manage(user);
  }, [read, search]);
  useEffect(() => {
    if (reveal > 0) panel.current?.scrollIntoView({ block: "start" });
  }, [reveal]);
  if (read.state === "loading") return <p role="status">Loading the accounts…</p>;
  if (read.state === "error") return <p className="admin-problem" role="alert">{read.message}</p>;
  return (
    <section className="admin-section">
      <p className="kicker">Accounts</p>
      <h1>Users, credits and daily limits</h1>
      <p className="lede">Daily allowances count new analysis runs per calendar day in {read.data.quota_timezone}.
        Credits and limits are this application's controls, not a verified billing ceiling.</p>
      <Attention users={read.data.users} manage={manage} />
      {missing !== null && <p className="admin-problem" role="alert" data-manage-missing>No account is named
        “{missing}”, so no panel was opened.</p>}
      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead>
            <tr><th>Account</th><th>Role</th><th>Status</th><th>Credits</th><th>Today</th><th /></tr>
          </thead>
          <tbody>
            {read.data.users.map((user) => (
              <tr key={user.user_id} data-user={user.username}>
                <td><strong>{user.display_name}</strong><br /><code>{user.username}</code></td>
                <td>{user.role === "admin" ? "Administrator" : "User"}</td>
                <td data-status={user.status}>{STATUS_LABEL[user.status]}
                  {offersInitialAllocation(user) && <><br /><small data-allocation="none">Nothing allocated yet</small></>}
                </td>
                <td className="admin-credits">
                  {unapproved(user) ? <span data-unapproved>Not approved<br />
                    <small>no credits or daily limit can be recorded</small></span> : user.credits ? <>
                    <span data-field="available">{user.credits.available}</span> available ·{" "}
                    <span data-field="held">{user.credits.held}</span> held<br />
                    <small>{user.credits.granted} granted · {user.credits.corrections} corrected ·{" "}
                      {user.credits.charged} charged · {user.credits.reconciles ? "reconciles" : "DOES NOT RECONCILE"}</small>
                  </> : "—"}
                </td>
                <td className="admin-daily">
                  {unapproved(user) ? "—" : user.daily ? <>
                    {user.daily.limit === null ? "No limit set" : <><span data-field="used">{user.daily.used}</span> of{" "}
                      <span data-field="limit">{user.daily.limit}</span> used</>}
                    <br /><small>{user.daily.day} · resets {when(user.daily.resets_at)}</small>
                  </> : "—"}
                </td>
                <td>
                  <button type="button" className="admin-link"
                          onClick={() => setOpen(open === user.user_id ? null : user.user_id)}>
                    {open === user.user_id ? "Close" : "Manage"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {read.data.users.filter((user) => user.user_id === open).map((user) => (
        <div className="admin-panel" key={user.user_id} aria-label={`Manage ${user.username}`} ref={panel}>
          <h2>{user.display_name}</h2>
          {user.status === "pending" ? (
            <p data-status-note="pending">This registration is waiting for a decision. Until it is approved it has no
              credits, daily limit or status actions here: <Link to="/admin/registrations">decide it under
              Registrations</Link>.</p>
          ) : user.status === "rejected" ? (
            <p data-status-note="rejected">This registration was rejected, and a rejection is final. It has no credits,
              daily limit or status actions.</p>
          ) : <>
            {user.role === "user" &&
              <Allocation user={user} presets={read.data.allocation_presets} filled={filled[user.user_id] ?? {}}
                          fill={(next) => setFilled((all) => ({ ...all, [user.user_id]: next }))} done={reload} />}
            <h3>Status</h3><StatusForm user={user} done={reload} />
          </>}
        </div>
      ))}
      <h2>New account</h2>
      <NewAccount done={reload} />
    </section>
  );
}
