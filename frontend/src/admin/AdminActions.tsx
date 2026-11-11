// Actions: every evidence-first research request and attempt, the operator's and the users', with its type (a local
// preparation, a $0 local mock or a provider call), account, model, Effort, outcome, locally measured times, reported
// usage, the planning estimate and the usage-derived cost. The cost is a local calculation, not verified billing; a
// value the records do not hold is shown as missing, never as zero.
import { useAdmin, adminPaths, type ActionRow } from "./adminApi.ts";
import { ACTION_LABEL, credits, requester, seconds, usage, usd, when } from "./adminFormat.ts";

export function AdminActions() {
  const read = useAdmin<{ actions: ActionRow[]; note: string }>(adminPaths.actions, 0);
  if (read.state === "loading") return <p role="status">Loading the actions…</p>;
  if (read.state === "error") return <p className="admin-problem" role="alert">{read.message}</p>;
  return (
    <section className="admin-section">
      <p className="kicker">Actions · research analysis</p>
      <h1>Who ran what, with which model, and what it cost</h1>
      <p className="lede">{read.data.note}</p>
      <div className="admin-table-wrap">
        <table className="admin-table admin-actions">
          <thead>
            <tr><th>Prepared</th><th>Type</th><th>Account</th><th>Model · Effort</th><th>Outcome</th>
              <th>Timing (this server's clock)</th><th>Usage</th><th>Planning estimate</th><th>Usage-derived cost</th>
              <th>Credits</th></tr>
          </thead>
          <tbody>
            {read.data.actions.map((row) => row.action === "unreadable" ? (
              <tr key={row.request_id}><td colSpan={10}>{row.request_id}: {row.problem}</td></tr>
            ) : (
              <tr key={row.request_id} data-request={row.request_id} data-action={row.action}>
                <td>{when(row.timing?.prepared_at)}</td>
                <td>{ACTION_LABEL[row.action]}</td>
                <td>{requester(row)}</td>
                <td><code>{row.model}</code><br />{row.effort}</td>
                <td>{row.outcome ?? (row.attempt_state === "none" ? "Not run" : row.attempt_state)}</td>
                <td className="admin-timing">
                  reserved {when(row.timing?.reserved_at)}<br />sent {when(row.timing?.sent_at)}<br />
                  received {when(row.timing?.received_at)}<br />
                  <span data-field="elapsed">elapsed {seconds(row.timing?.elapsed_seconds)}</span><br />
                  <small>Unavailable: {row.timing?.unavailable.join(", ")}</small>
                </td>
                <td data-field="usage">{usage(row.usage)}</td>
                <td data-field="estimate">{usd(row.planning_estimate_usd)}</td>
                <td data-field="cost" title={row.usage_cost_basis ?? undefined}>{usd(row.usage_cost_usd)}
                  {row.usage_cost_usd !== null && row.action === "provider_call" &&
                    <><br /><small>local calculation, not verified billing</small></>}</td>
                <td data-field="credits">{credits(row)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
