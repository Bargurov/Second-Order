// The credit policy, the quota time zone and record ownership. A policy version enables Effort levels the configured
// model is verified to accept and sets whole-number credit rates, the administrator's per-request planning-estimate
// limit and how long a quote stays valid. Nothing is prefilled unless the administrator chooses a preset (the
// operator's selected pilot terms), which fills the draft's rates and Effort extras only: the per-request limit and the
// quote validity stay theirs, and publishing is the separate explicit action. A new version supersedes every quote
// issued under the previous one. A preview shows the quotes a draft would issue for the public synthetic examples and
// records nothing; any change to the form clears it.
import { useState, type FormEvent } from "react";
import {
  adminPaths, adminPost, newKey, useAdmin, type AdminUser, type AdminWrite, type PolicyPreset, type PolicyPreview,
  type PolicyView,
} from "./adminApi.ts";
import { presetDraft, presetPoints, usd, when } from "./adminFormat.ts";

function Saved({ result }: { result: AdminWrite<unknown> | null }) {
  if (!result) return null;
  return result.state === "saved" ? <p className="admin-ok" role="status">Saved.</p>
    : <p className="admin-problem" role="alert">{result.message}</p>;
}

function PolicyForm({ view, done }: { view: PolicyView; done: () => void }) {
  const models = Object.keys(view.verified_efforts);
  const [model, setModel] = useState(models[0] ?? "");
  const [enabled, setEnabled] = useState<Record<string, string>>({});
  const [rates, setRates] = useState({ base: "", per_1k_input_tokens: "", per_1k_output_tokens: "",
                                       max_request_usd: "", quote_valid_seconds: "" });
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<AdminWrite<unknown> | null>(null);
  const [preview, setPreview] = useState<AdminWrite<PolicyPreview> | null>(null);
  // One key per intent: repeating unchanged values (a double click, a lost reply submitted again) repeats it and
  // publishes nothing more; any change, or a saved publication, starts a new intent (QA-5).
  const [key, setKey] = useState(newKey);
  const [busy, setBusy] = useState(false);
  const rate = (field: keyof typeof rates) => (event: { target: { value: string } }) =>
    setRates((value) => ({ ...value, [field]: event.target.value }));
  const fill = (preset: PolicyPreset) => {
    const filled = presetDraft(preset, view.verified_efforts[model] ?? [], view.current, rates);
    setEnabled(filled.enabled);
    setRates(filled.rates);
    setPreview(null);
    setResult(null);
    setKey(newKey());
  };
  const draft = () => ({
      model, credits: { base: Number(rates.base), per_1k_input_tokens: Number(rates.per_1k_input_tokens),
                        per_1k_output_tokens: Number(rates.per_1k_output_tokens) },
      efforts: Object.fromEntries(Object.entries(enabled).map(([effort, extra]) => [effort,
        { extra_credits: Number(extra) }])),
      max_request_usd: Number(rates.max_request_usd), quote_valid_seconds: Number(rates.quote_valid_seconds),
  });
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    const outcome = await adminPost(adminPaths.policy, { policy: draft(), reason, idempotency_key: key });
    setBusy(false);
    setResult(outcome);
    if (outcome.state === "saved") {
      setKey(newKey());
      done();
    }
  };
  return (
    <form className="admin-form admin-policy-form" onSubmit={(event) => void submit(event)} aria-label="New policy version"
          onChange={() => { setPreview(null); setKey(newKey()); }}>
      {view.presets.map((preset) => (
        <div key={preset.preset} className="admin-panel" data-preset={preset.preset}>
          <p><strong>{preset.label}</strong> ({presetPoints(preset)} points). {preset.note}</p>
          <button type="button" className="button" onClick={() => fill(preset)}>Fill the draft with these terms</button>
        </div>
      ))}
      <label>Model
        <select name="model" value={model} onChange={(event) => { setModel(event.target.value); setEnabled({}); }}>
          {models.map((name) => <option key={name} value={name}>{name}</option>)}
        </select>
      </label>
      <fieldset>
        <legend>Effort levels offered (verified for this model) and their extra credits</legend>
        {(view.verified_efforts[model] ?? []).map((effort) => (
          <label key={effort} className="admin-effort">
            <input type="checkbox" name={`effort-${effort}`} checked={effort in enabled}
                   onChange={(event) => setEnabled((value) => {
                     const next = { ...value };
                     if (event.target.checked) next[effort] = "0"; else delete next[effort];
                     return next;
                   })} />
            {effort}
            {effort in enabled && (
              <input name={`extra-${effort}`} inputMode="numeric" aria-label={`Extra credits for ${effort}`}
                     value={enabled[effort]} pattern="[0-9]+" required
                     onChange={(event) => setEnabled((value) => ({ ...value, [effort]: event.target.value }))} />
            )}
          </label>
        ))}
      </fieldset>
      <label>Base credits (at least 1)<input name="base" inputMode="numeric" value={rates.base} required pattern="[0-9]+" onChange={rate("base")} /></label>
      <label>Credits per 1,000 input tokens<input name="per_1k_input_tokens" inputMode="numeric" value={rates.per_1k_input_tokens} required pattern="[0-9]+" onChange={rate("per_1k_input_tokens")} /></label>
      <label>Credits per 1,000 output tokens of the bound<input name="per_1k_output_tokens" inputMode="numeric" value={rates.per_1k_output_tokens} required pattern="[0-9]+" onChange={rate("per_1k_output_tokens")} /></label>
      <label>Largest planning estimate per request (USD)<input name="max_request_usd" inputMode="decimal" value={rates.max_request_usd} required onChange={rate("max_request_usd")} /></label>
      <label>Quote validity (seconds, 60 to 86,400)<input name="quote_valid_seconds" inputMode="numeric" value={rates.quote_valid_seconds} required pattern="[0-9]+" onChange={rate("quote_valid_seconds")} /></label>
      <label>Reason<input name="reason" value={reason} required maxLength={500} onChange={(event) => setReason(event.target.value)} /></label>
      <button type="button" className="button" onClick={() => void adminPost<PolicyPreview>(adminPaths.policyPreview,
        { policy: draft() }).then(setPreview)}>Preview the quotes (records nothing)</button>
      <button type="submit" className="button" disabled={busy}>Publish a new policy version</button>
      <Saved result={result} />
      {preview && (preview.state === "saved" ? <PreviewTable preview={preview.data} />
        : <p className="admin-problem" role="alert">{preview.message}</p>)}
    </form>
  );
}

/** The quotes a draft would issue for the public synthetic examples, with the admin-only planning estimate. */
function PreviewTable({ preview }: { preview: PolicyPreview }) {
  return (
    <div className="admin-table-wrap" data-preview="policy">
      <p className="muted">Not recorded. Users would see the points only. {preview.size_note}</p>
      <table className="admin-table">
        <thead><tr><th>Synthetic source</th><th>Effort</th><th>Credits</th><th>Planning estimate</th><th /></tr></thead>
        <tbody>{preview.examples.flatMap((example) => example.quotes.map((quote) => (
          <tr key={`${example.example}-${quote.effort}`}>
            <td>{example.label} ({example.characters.toLocaleString("en-US")} characters)</td>
            <td>{quote.effort}</td><td>{quote.credits}</td><td>{usd(quote.planning_estimate_usd)}</td>
            <td>{quote.refused_over_budget ? "Refused: above the per-request limit" : ""}</td>
          </tr>
        )))}</tbody>
      </table>
    </div>
  );
}

function TimezoneForm({ current, fixed, done }: { current: string; fixed: boolean; done: () => void }) {
  const [zone, setZone] = useState(current);
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<AdminWrite<unknown> | null>(null);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const outcome = await adminPost(adminPaths.settings, { quota_timezone: zone, reason });
    setResult(outcome);
    if (outcome.state === "saved") done();
  };
  return (
    <form className="admin-form" onSubmit={(event) => void submit(event)} aria-label="Quota time zone">
      {fixed && <p className="muted" data-zone="fixed">Fixed at {current}: runs have been counted on its calendar
        days, so another zone would count the same hours again.</p>}
      <label>Quota time zone (IANA name)<input name="quota_timezone" value={zone} required onChange={(event) => setZone(event.target.value)} /></label>
      <label>Reason<input name="reason" value={reason} required maxLength={500} onChange={(event) => setReason(event.target.value)} /></label>
      <button type="submit" className="button">Save</button>
      <Saved result={result} />
    </form>
  );
}

function OwnershipForm({ users }: { users: AdminUser[] }) {
  const [form, setForm] = useState({ record_id: "", user_id: "", reason: "" });
  const [result, setResult] = useState<AdminWrite<unknown> | null>(null);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setResult(await adminPost(adminPaths.ownership, { kind: "capture", ...form }));
  };
  return (
    <form className="admin-form" onSubmit={(event) => void submit(event)} aria-label="Assign a capture">
      <label>Capture ID<input name="record_id" value={form.record_id} required onChange={(event) => setForm({ ...form, record_id: event.target.value })} /></label>
      <label>User
        <select name="user_id" value={form.user_id} required onChange={(event) => setForm({ ...form, user_id: event.target.value })}>
          <option value="">Choose a user</option>
          {users.filter((user) => user.role === "user").map((user) => <option key={user.user_id} value={user.user_id}>{user.display_name}</option>)}
        </select>
      </label>
      <label>Reason<input name="reason" value={form.reason} required maxLength={500} onChange={(event) => setForm({ ...form, reason: event.target.value })} /></label>
      <button type="submit" className="button">Assign once</button>
      <Saved result={result} />
    </form>
  );
}

export function AdminPolicy() {
  const [version, setVersion] = useState(0);
  const policy = useAdmin<PolicyView>(adminPaths.policy, version);
  const settings = useAdmin<{ quota_timezone: string; fixed: boolean }>(adminPaths.settings, version);
  const users = useAdmin<{ users: AdminUser[] }>(adminPaths.users, version);
  const reload = () => setVersion((value) => value + 1);
  if (policy.state === "loading") return <p role="status">Loading the policy…</p>;
  if (policy.state === "error") return <p className="admin-problem" role="alert">{policy.message}</p>;
  const current = policy.data.current;
  return (
    <section className="admin-section">
      <p className="kicker">Policy</p>
      <h1>Credit policy, Effort and settings</h1>
      <h2>Current policy</h2>
      {current === null ? <p data-policy="none">No credit policy is set, so nothing can be quoted or run.</p> : (
        <dl className="admin-facts" data-policy={current.policy_version}>
          <dt>Version</dt><dd>{current.policy_version} · {when(current.created_at)} · {current.reason}</dd>
          <dt>Model</dt><dd><code>{current.model}</code></dd>
          <dt>Effort offered</dt><dd>{Object.entries(current.efforts).map(([effort, terms]) =>
            `${effort} (+${terms.extra_credits})`).join(", ") || "none"}</dd>
          <dt>Rates</dt><dd>{current.credits.base} base · {current.credits.per_1k_input_tokens} per 1,000 input tokens ·{" "}
            {current.credits.per_1k_output_tokens} per 1,000 output tokens of the {policy.data.output_bound_tokens.toLocaleString("en-US")}-token bound</dd>
          <dt>Per-request limit</dt><dd>{usd(current.max_request_usd)} planning estimate</dd>
          <dt>Quotes</dt><dd>valid {current.quote_valid_seconds} s · settlement {current.settlement}</dd>
        </dl>
      )}
      <p className="muted">{policy.data.formula}. {policy.data.effort_source}</p>
      <h2>Publish a new version</h2>
      <PolicyForm view={policy.data} done={reload} />
      <h2>Quota time zone</h2>
      {settings.state === "ready" && <TimezoneForm key={settings.data.quota_timezone}
                                                   current={settings.data.quota_timezone}
                                                   fixed={settings.data.fixed} done={reload} />}
      <h2>Assign an operator capture to a user</h2>
      <p className="muted">Operator records stay the administrator's unless assigned here, one capture at a time.
        Its existing analyses and reviews stay the operator's.</p>
      {users.state === "ready" && <OwnershipForm users={users.data.users} />}
      <h2>Earlier versions</h2>
      <ul>{policy.data.versions.slice().reverse().map((row) => (
        <li key={row.policy_version}>{row.policy_version} · {when(row.created_at)} · {row.reason}</li>))}</ul>
    </section>
  );
}
