// Usage limits and today's use (docs/news-usage-contract.md, section 3). A usage policy version sets each account's
// daily searches, publication imports, new sources and prepared analyses, what an account may hold, the protective
// request limits, and the whole server's publication fetches and feed refreshes. Without one, counted work is refused
// and the feeds are not refreshed. Nothing is prefilled: every field starts empty, and the administrator types each
// value or copies the current version's, then publishes it as one explicit action with a reason. A repeated submission
// of the same intent publishes nothing more. Today's use is the server's own count of what it accepted and requested;
// it is not billing and verifies no cost.
import { useState, type FormEvent } from "react";
import {
  ACCOUNT_LIMITS, SERVER_LIMITS, adminPaths, adminPost, newKey, useAdmin, type AccountLimit, type AdminUser,
  type AdminWrite, type ServerLimit, type UsageOverview, type UsagePolicyView,
} from "./adminApi.ts";
import {
  LIMIT_LABEL, allowance, emptyUsageForm, nameOf, usageDraft, usageFormFrom, when, type UsageForm,
} from "./adminFormat.ts";

const NONE = "No usage limits are set, so searches, publication imports, new sources and prepared analyses are refused " +
  "for every user, and the feeds are not refreshed.";

function LimitField({ name, form, set, bound }: { name: AccountLimit | ServerLimit; form: UsageForm;
                                                  set: (name: AccountLimit | ServerLimit, value: string) => void;
                                                  bound: { min: number; max: number } }) {
  return (
    <label>{LIMIT_LABEL[name]} ({bound.min.toLocaleString("en-US")} to {bound.max.toLocaleString("en-US")})
      <input name={name} inputMode="numeric" pattern="[0-9]+" required value={form[name]}
             onChange={(event) => set(name, event.target.value)} />
    </label>
  );
}

function LimitsForm({ view, done }: { view: UsagePolicyView; done: () => void }) {
  const [form, setForm] = useState<UsageForm>(emptyUsageForm);
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<AdminWrite<unknown> | null>(null);
  // One key per intent: repeating unchanged values repeats the publication; any change starts a new intent.
  const [key, setKey] = useState(newKey);
  const [busy, setBusy] = useState(false);
  const set = (name: AccountLimit | ServerLimit, value: string) => {
    setForm((typed) => ({ ...typed, [name]: value }));
    setKey(newKey());
    setResult(null);
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    const outcome = await adminPost(adminPaths.usagePolicy, { policy: usageDraft(form), reason, idempotency_key: key });
    setBusy(false);
    setResult(outcome);
    if (outcome.state === "saved") {
      setKey(newKey());
      done();
    }
  };
  return (
    <form className="admin-form" onSubmit={(event) => void submit(event)} aria-label="New usage limits">
      {view.current && (
        <button type="button" className="button" onClick={() => {
          setForm(usageFormFrom(view.current!));
          setKey(newKey());
          setResult(null);
        }}>Start from the current version</button>
      )}
      <fieldset>
        <legend>Each account</legend>
        {ACCOUNT_LIMITS.map((name) => <LimitField key={name} name={name} form={form} set={set}
                                                  bound={view.bounds.account[name]} />)}
      </fieldset>
      <fieldset>
        <legend>The whole server</legend>
        {SERVER_LIMITS.map((name) => <LimitField key={name} name={name} form={form} set={set}
                                                 bound={view.bounds.server[name]} />)}
      </fieldset>
      <label>Reason<input name="reason" value={reason} required maxLength={500}
                          onChange={(event) => { setReason(event.target.value); setKey(newKey()); }} /></label>
      <button type="submit" className="button" disabled={busy}>Publish these usage limits</button>
      {result && (result.state === "saved" ? <p className="admin-ok" role="status">Published.</p>
        : <p className="admin-problem" role="alert">{result.message}</p>)}
    </form>
  );
}

function TodayTable({ overview, users }: { overview: UsageOverview; users: AdminUser[] }) {
  if (overview.accounts.length === 0) return <p className="muted">No user accounts yet.</p>;
  const operations = overview.accounts[0].operations;
  return (
    <div className="admin-table-wrap">
      <table className="admin-table" data-usage="accounts">
        <thead><tr><th>Account</th>{operations.map((row) => <th key={row.operation}>{row.label}</th>)}
          <th>Sources held</th><th>Source text held</th></tr></thead>
        <tbody>{overview.accounts.map((account) => (
          <tr key={account.user_id}
              data-usage-user={users.find((user) => user.user_id === account.user_id)?.username ?? account.user_id}>
            <td>{nameOf(account.user_id, users)}</td>
            {account.operations.map((row) => <td key={row.operation} className="admin-number"
                                                 data-operation={row.operation}>{allowance(row)}</td>)}
            <td className="admin-number" data-field="sources">{allowance(account.storage.sources)}</td>
            <td className="admin-number" data-field="source-bytes">{allowance(account.storage.source_bytes, " bytes")}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

export function AdminUsage() {
  const [version, setVersion] = useState(0);
  const policy = useAdmin<UsagePolicyView>(adminPaths.usagePolicy, version);
  const overview = useAdmin<UsageOverview>(adminPaths.usage, version);
  const users = useAdmin<{ users: AdminUser[] }>(adminPaths.users, version);
  const reload = () => setVersion((value) => value + 1);
  if (policy.state === "loading") return <p role="status">Loading the usage limits…</p>;
  if (policy.state === "error") return <p className="admin-problem" role="alert">{policy.message}</p>;
  const current = policy.data.current;
  return (
    <section className="admin-section">
      <p className="kicker">Usage</p>
      <h1>Usage limits and today's use</h1>
      <h2>Current limits</h2>
      {current === null ? <p data-usage-policy="none">{NONE}</p> : (
        <dl className="admin-facts" data-usage-policy={current.policy_version}>
          <dt>Version</dt><dd>{current.policy_version} · {when(current.created_at)} · {current.reason}</dd>
          {ACCOUNT_LIMITS.map((name) => (
            <div key={name} style={{ display: "contents" }}>
              <dt>{LIMIT_LABEL[name]}</dt><dd data-limit={name}>{current.account[name].toLocaleString("en-US")}</dd>
            </div>
          ))}
          {SERVER_LIMITS.map((name) => (
            <div key={name} style={{ display: "contents" }}>
              <dt>{LIMIT_LABEL[name]} (whole server)</dt>
              <dd data-limit={name}>{current.server[name].toLocaleString("en-US")}</dd>
            </div>
          ))}
        </dl>
      )}
      <p className="muted">Daily counts reset at midnight in the quota time zone. A refused request counts nothing and
        reopening an analysis is free. The protective limits answer with a wait and never charge.</p>
      <h2>Publish new usage limits</h2>
      <LimitsForm view={policy.data} done={reload} />
      <h2>Today's use</h2>
      {overview.state === "error" && <p className="admin-problem" role="alert">{overview.message}</p>}
      {overview.state === "ready" && (
        <>
          <p className="muted" data-usage-day={overview.data.day}>{overview.data.day} ({overview.data.timezone}); the
            counts reset {when(overview.data.resets_at)}. These are this server's own counts of what it accepted and
            requested. They are not billing and verify no cost.</p>
          <TodayTable overview={overview.data} users={users.state === "ready" ? users.data.users : []} />
          <h3>The whole server</h3>
          <dl className="admin-facts" data-usage="server">
            <dt>Publication page fetches</dt>
            <dd data-field="publication-fetches">{allowance(overview.data.server.publication_fetches)}</dd>
            <dt>Feed refreshes</dt><dd data-field="refreshes">{allowance(overview.data.server.refreshes)}</dd>
            <dt>Last refresh started</dt><dd>{overview.data.server.last_refresh_started_at
              ? when(overview.data.server.last_refresh_started_at) : "None yet"}</dd>
            <dt>Next refresh allowed</dt><dd>{overview.data.server.next_refresh_allowed_at
              ? when(overview.data.server.next_refresh_allowed_at) : "No wait"}</dd>
          </dl>
        </>
      )}
      <h2>Earlier versions</h2>
      <ul>{policy.data.versions.slice().reverse().map((row) => (
        <li key={row.policy_version}>{row.policy_version} · {when(row.created_at)} · {row.reason}</li>))}</ul>
    </section>
  );
}
