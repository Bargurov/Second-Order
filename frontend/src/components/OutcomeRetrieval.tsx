import { useEffect, useRef, useState } from "react";
import {
  approveRetrieval, checkRetrievalAttempt, previewRetrieval,
  type AttemptState, type JournalRow, type RetrievalPlan, type RetrievalResult,
} from "../assessment";
import { TableArea } from "./FrozenParts";

type Sent =
  | { state: "idle" }
  | { state: "pending" }
  | { state: "done"; result: RetrievalResult }
  | { state: "refused"; message: string }
  | { state: "unconfirmed"; message: string; planSha: string; attempt: number }
  | { state: "checked"; result: AttemptState };

const WAITING = new Set(["horizon_not_elapsed", "outcome_missing", "outcome_in_package", "outcome_held"]);

/**
 * Outcome data for frozen H.15 hypotheses: choose them explicitly, see the plan (what is held, what is missing, what is
 * still in the future), and approve at most one download of the Board's release package. Nothing is selected for you.
 */
export function OutcomeRetrieval({ rows, onChanged }: { rows: JournalRow[]; onChanged: () => void }) {
  const eligible = rows.filter((row) => row.provider === "board-h15" && row.state !== null && WAITING.has(row.state));
  const [selected, setSelected] = useState<string[]>([]);
  const [plan, setPlan] = useState<RetrievalPlan | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [approved, setApproved] = useState(false);
  const [sent, setSent] = useState<Sent>({ state: "idle" });
  const inflight = useRef(false);
  const key = selected.join(",");
  useEffect(() => {  // Another selection voids the plan and the approval.
    setPlan(null);
    setApproved(false);
    setProblem(null);
  }, [key]);
  const others = rows.filter((row) => row.provider === "fred");

  const preview = async () => {
    setPreviewing(true);
    setProblem(null);
    const result = await previewRetrieval(selected);
    setPreviewing(false);
    setApproved(false);
    if (result.state === "done") setPlan(result.data);
    else setProblem(result.message);
  };

  const send = async () => {
    if (!plan || !approved || inflight.current) return;
    inflight.current = true;
    setSent({ state: "pending" });
    const result = await approveRetrieval(plan);
    inflight.current = false;
    setApproved(false);
    if (result.state === "done") {
      setSent({ state: "done", result: result.data });
      setPlan(null);
      onChanged();
    } else if (result.state === "refused") setSent({ state: "refused", message: result.message });
    else setSent({ state: "unconfirmed", message: result.message, planSha: plan.plan_sha256, attempt: plan.next_attempt });
  };

  const check = async (planSha: string, attempt: number) => {
    const result = await checkRetrievalAttempt(planSha, attempt, new AbortController().signal);
    if (result.state === "ready") {
      setSent({ state: "checked", result: result.data });
      onChanged();
    } else {
      setSent({ state: "unconfirmed", planSha, attempt,
                message: `The attempt could not be read: ${"message" in result ? result.message : "no reply"}.` });
    }
  };

  return (
    <div className="retrieval-flow">
      {eligible.length === 0 ? (
        <p className="freeze-empty">No frozen H.15 hypothesis is waiting for outcome data.</p>
      ) : (
        <fieldset className="freeze-choice retrieval-choice">
          <legend>Hypotheses (choose; none is preselected)</legend>
          {eligible.map((row) => (
            <label key={row.hypothesis_id} data-hypothesis={row.hypothesis_id}>
              <input type="checkbox" name="retrieval-hypothesis" checked={selected.includes(row.hypothesis_id)}
                     onChange={(event) => setSelected((current) => event.target.checked
                       ? [...current, row.hypothesis_id].sort() : current.filter((id) => id !== row.hypothesis_id))} />
              <span>{row.headline} <small>({row.state_label}; expected target {row.expected_target ?? "unknown"})</small></span>
            </label>
          ))}
        </fieldset>
      )}
      {others.length > 0 && <p className="freeze-note">FRED-bound hypotheses are not listed: their outcome can come
        only from local FRED snapshots, and nothing here fetches FRED data or substitutes H.15.</p>}
      <button type="button" className="button retrieval-preview-button" disabled={selected.length === 0 || previewing}
              onClick={preview}>{previewing ? "Planning…" : "Preview the retrieval"}</button>
      {problem && <p className="freeze-problem" role="alert">{problem}</p>}
      {plan && <PlanPanel plan={plan} />}
      {plan && plan.requests === 1 && (
        <>
          {!plan.retrieval.enabled && <p className="freeze-problem" role="alert">{plan.retrieval.detail}</p>}
          <label className="freeze-confirm">
            <input type="checkbox" name="approve-retrieval" checked={approved} disabled={!plan.retrieval.enabled}
                   onChange={(event) => setApproved(event.target.checked)} />
            <span>I approve attempt {plan.next_attempt} of this plan: one request for the Board's complete release
              package, sent once, with no retry or redirect. It is kept privately and validated; nothing is imported or
              assessed by it.</span>
          </label>
          <button type="button" className="button button-freeze retrieval-send"
                  disabled={!plan.retrieval.enabled || !approved || sent.state === "pending"}
                  onClick={send}>{sent.state === "pending" ? "Downloading…" : "Download the release package once"}</button>
        </>
      )}
      <SentPanel sent={sent} onCheck={check} />
    </div>
  );
}

function PlanPanel({ plan }: { plan: RetrievalPlan }) {
  return (
    <div className="freeze-preview retrieval-plan" data-plan={plan.plan_sha256}>
      <dl className="ledger freeze-ledger">
        <div><dt>Plan</dt><dd>{plan.plan_version} · {plan.plan_sha256}</dd></div>
        <div><dt>As of (New York date)</dt><dd>{plan.as_of}</dd></div>
        <div><dt>Requests</dt><dd data-requests={plan.requests}>{plan.requests === 1
          ? `One: the full release package (${plan.request?.missing_sessions} missing past sessions, ${plan.request?.missing_from} to ${plan.request?.missing_to})`
          : plan.awaiting_release.length > 0
            ? `None yet: ${plan.awaiting_release.length} ended session(s) await the Board's release, obtainable from ${plan.awaiting_release[0].obtainable_from}`
            : "None: every past session the selection needs is already held locally"}</dd></div>
        <div><dt>Key · charge</dt><dd>{plan.source.key} · {plan.source.charge}</dd></div>
      </dl>
      <TableArea label="The hypotheses this plan serves">
        <table className="freeze-legs retrieval-table">
          <thead><tr><th scope="col">Hypothesis</th><th scope="col">Needs</th><th scope="col">Held</th>
            <th scope="col">Missing (past)</th><th scope="col">Awaiting the Board's release</th>
            <th scope="col">Not ended yet</th></tr></thead>
          <tbody>{plan.hypotheses.map((row) => (
            <tr key={row.hypothesis_id} data-hypothesis={row.hypothesis_id}>
              <th scope="row">{row.headline}</th>
              <td>{row.required_from} to {row.required_through}</td>
              <td>{row.held_sessions} of {row.past_sessions}</td>
              <td>{row.missing_sessions.length ? row.missing_sessions.join(", ") : "none"}</td>
              <td data-awaiting={row.awaiting_release.length}>{row.awaiting_release.length
                ? row.awaiting_release.join(", ") : "none"}</td>
              <td>{row.future_sessions.length ? row.future_sessions.join(", ") : "none"}</td>
            </tr>
          ))}</tbody>
        </table>
      </TableArea>
      {(plan.reuse.snapshots.length > 0 || plan.reuse.packages.length > 0) && (
        <div className="freeze-block"><h4>Reused locally</h4><ul>
          {plan.reuse.snapshots.map((item) => <li key={item.snapshot_id}>Snapshot <code>{item.snapshot_id.slice(0, 12)}</code>
            {" "}(already in the store)</li>)}
          {plan.reuse.packages.map((item) => <li key={item.package_id}>Kept package <code>{item.package_id}</code>
            {" "}(needs only a local import on each hypothesis's page)</li>)}
        </ul></div>
      )}
      {plan.future_sessions.length > 0 && <p className="freeze-note">Sessions on or after {plan.as_of} are never
        requested: a date-only observation is complete only after its date ends.</p>}
      {plan.awaiting_release.length > 0 && <p className="freeze-note retrieval-awaiting">{plan.release_rule} Ended
        sessions it cannot state yet are not requested: {plan.awaiting_release.map((item) =>
          `${item.session} (from ${item.obtainable_from})`).join(", ")}. A download is planned only for sessions it can
        already state; held data decide, whatever the time.</p>}
      <p className="freeze-note">{plan.source.download}</p>
      <p className="freeze-note">{plan.note}</p>
      {plan.attempts.length > 0 && <div className="freeze-block"><h4>Earlier attempts of this plan</h4><ul>
        {plan.attempts.map((item) => <li key={item.number}>Attempt {item.number}: {String(item.outcome?.outcome ??
          "started, no outcome recorded")}{item.problem ? ` (${item.problem})` : ""}</li>)}</ul></div>}
    </div>
  );
}

function SentPanel({ sent, onCheck }: { sent: Sent; onCheck: (planSha: string, attempt: number) => void }) {
  if (sent.state === "done") {
    const { result } = sent;
    return (
      <div className={`freeze-outcome ${result.outcome === "saved" ? "is-frozen" : "is-unconfirmed"}`} role="status"
           data-outcome={result.outcome}>
        <p className="freeze-status">Attempt {result.attempt}: {result.outcome.replace(/_/g, " ")}</p>
        {result.detail && <p>{result.detail}</p>}
        {result.package_id && <p>Kept as package <code>{result.package_id}</code>. Import it as an outcome on each
          hypothesis's page; nothing was imported or assessed.</p>}
        {result.outcome !== "saved" && <p>Nothing is retried. Another attempt needs its own preview and approval.</p>}
      </div>
    );
  }
  if (sent.state === "refused") return <p className="freeze-problem" role="alert">{sent.message}</p>;
  if (sent.state === "unconfirmed") {
    return (
      <div className="freeze-outcome is-unconfirmed" role="alert">
        <p>{sent.message}</p>
        <p>The approval is not sent again. Read what this attempt recorded:</p>
        <button type="button" className="button" onClick={() => onCheck(sent.planSha, sent.attempt)}>Check the outcome</button>
      </div>
    );
  }
  if (sent.state === "checked") {
    return <div className="freeze-outcome" role="status"><p>Attempt {sent.result.attempt}: {sent.result.state.replace(/_/g, " ")}.
      {" "}{sent.result.detail}</p></div>;
  }
  return null;
}
