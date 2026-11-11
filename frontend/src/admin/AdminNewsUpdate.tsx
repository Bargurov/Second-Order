// An update run (news-update-0.1): the plan (what a refresh would request, what it would not and why, each step's
// limits and the paid state), a run's start, its explicit refresh, its arrivals and the stories they reached, the
// preparation steps for those stories only, the paid approvals and publications through the batches' own routes, and
// what completed, what needs attention and what failed. Reading requests, sends and writes nothing; nothing here acts
// on its own, and an approval is sent only after its own checkbox and button, repeating the batch's total.
import { useEffect, useState } from "react";
import { adminGet, adminPost, newKey, type AdminWrite } from "./adminApi.ts";
import { usd, when } from "./adminFormat.ts";
import { newsPaths } from "./newsDesk.ts";
import { arrivalsLine, paidLine, reportProblem, updatePaths, type PaidBatch, type UpdatePlan, type UpdateReport,
  type UpdateRunRow } from "./newsUpdate.ts";

function Result({ result }: { result: AdminWrite<unknown> | null }) {
  if (!result) return null;
  return result.state === "saved" ? <p className="admin-ok" role="status">Done.</p>
    : <p className="admin-problem" role="alert">{result.message}</p>;
}

function Plan({ plan }: { plan: UpdatePlan }) {
  const skipped = plan.sources.filter((row) => row.action !== "request");
  return (
    <div data-update-plan>
      <p>A refresh would request {plan.requests.feeds} sources, each once with no retry
        ({plan.sources.filter((row) => row.kind === "official" && row.action === "request").length} official feeds,
        {" "}{plan.sources.filter((row) => row.kind === "publisher" && row.action === "request").length} publisher feeds).
        A source requested in the last {plan.limits.cooldown_minutes} minutes is not requested again. At most
        {" "}{plan.limits.text_requests} publication texts per run; batches of at most {plan.limits.relevance_batch}
        {" "}(relevance) and {plan.limits.brief_batch} (briefs) stories.</p>
      {skipped.length > 0 && <ul data-update-skipped>{skipped.map((row) => (
        <li key={row.source}>{row.publisher}: {row.reason}</li>))}</ul>}
      <p className="muted">Arrivals are compared with {when(plan.reference.at)}: {plan.reference.statement}</p>
      <p className={plan.paid.enabled ? "admin-attention" : "muted"} data-update-paid={plan.paid.enabled}>
        {plan.paid.detail} A model request's output part at its limit: relevance {usd(plan.paid.relevance
          .output_at_max_usd)} ({plan.paid.relevance.max_tokens.toLocaleString()} tokens), brief and explanation{" "}
        {plan.paid.briefs.stages ? "in two requests: " + plan.paid.briefs.stages.map((row) => `stage ${row.stage} ` +
          `${usd(row.output_at_max_usd)} (${row.max_tokens.toLocaleString()} tokens)`).join(", ") :
          `${usd(plan.paid.briefs.output_at_max_usd)} (${plan.paid.briefs.max_tokens.toLocaleString()} tokens)`}; each
        request's input part is estimated from its exact bytes at its preview. {plan.paid.statement}</p>
    </div>
  );
}

function Approval({ batch, done }: { batch: PaidBatch; done: () => void }) {
  const [approve, setApprove] = useState(false);
  const [result, setResult] = useState<AdminWrite<unknown> | null>(null);
  const send = async () => {
    if (!approve) return;
    const path = batch.stage === "relevance" ? newsPaths.relevanceBatchAction(batch.batch_id, "approval")
      : newsPaths.batchAction(batch.batch_id, "approval");
    const outcome = await adminPost(path, { batch_id: batch.batch_id, approve_paid_requests: true,
                                            estimated_max_usd_total: batch.estimated_max_usd_total });
    setApprove(false);
    setResult(outcome);
    done();
  };
  return (
    <li data-update-approval={batch.batch_id}>
      {batch.stage} batch {batch.batch_id}: {batch.requests} saved requests, planning estimate{" "}
      {usd(batch.estimated_max_usd_total)} (not a billing ceiling){batch.approved ? " · approved" : ""}
      {!batch.approved && <span className="admin-form">
        <label className="admin-effort"><input type="checkbox" checked={approve}
          onChange={(event) => setApprove(event.target.checked)} /> I approve these billed requests at up to this
          total; each is sent once and never retried.</label>
        <button type="button" className="button" disabled={!approve} onClick={() => void send()}>Send</button>
      </span>}
      <Result result={result} />
    </li>
  );
}

function Publication({ batchId, done }: { batchId: string; done: () => void }) {
  const [reason, setReason] = useState("");
  const [reviewed, setReviewed] = useState(false);
  const [result, setResult] = useState<AdminWrite<unknown> | null>(null);
  const publish = async () => {
    const outcome = await adminPost(newsPaths.batchAction(batchId, "publication"), { reason, reviewed });
    setReviewed(false);
    setResult(outcome);
    done();
  };
  return (
    <div className="admin-form" data-update-publication={batchId}>
      <label>Reason for publishing batch {batchId}<input value={reason} maxLength={300}
                                                          onChange={(event) => setReason(event.target.value)} /></label>
      <label className="admin-effort"><input type="checkbox" checked={reviewed}
        onChange={(event) => setReviewed(event.target.checked)} /> I read every version this publishes</label>
      <button type="button" className="button" disabled={!reason.trim()} onClick={() => void publish()}>Publish the
        publishable versions</button>
      <Result result={result} />
    </div>
  );
}

function Report({ report, done }: { report: UpdateReport; done: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [method, setMethod] = useState<"model" | "assisted">("model");
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<AdminWrite<unknown> | null>(null);
  const act = async (name: string, path: string, body: object) => {
    if (busy) return;
    setBusy(name);
    const outcome = await adminPost(path, body);
    setBusy(null);
    setResult(outcome);
    done();
  };
  const step = (name: "refresh" | "texts" | "relevance" | "context" | "briefs") => updatePaths.step(report.run_id, name);
  const refreshed = report.refresh_state === "done";
  const briefBatches = report.steps.filter((row) => row.step === "briefs" && row.batch_id).map((row) => row.batch_id!);
  return (
    <div data-update-run={report.run_id} data-refresh-state={report.refresh_state}>
      <p><strong>{report.label}</strong> · {report.run_id} · cutoff {when(report.started_at)} · arrivals compared with
        {" "}{when(report.reference.at)} ({report.reference.statement}) · baseline {report.baseline_id}</p>
      <div className="admin-form">
        <button type="button" className="button" disabled={busy !== null || report.refresh_state !== "not_started"}
                onClick={() => void act("refresh", step("refresh"), {})}>
          {busy === "refresh" ? "Refreshing…" : `Refresh ${report.plan.requests.feeds} sources and group`}</button>
        <button type="button" className="button" disabled={busy !== null || !refreshed ||
          report.steps.some((row) => row.step === "texts")} onClick={() => void act("texts", step("texts"), {})}>
          Retrieve publication texts</button>
        <label>Preparation<select value={method} onChange={(event) => setMethod(event.target.value as typeof method)}>
          <option value="model">AI model in this application (saved requests; paid only after approval)</option>
          <option value="assisted">AI assistant or editor outside it (packet and import)</option>
        </select></label>
        <button type="button" className="button" disabled={busy !== null || !refreshed}
                onClick={() => void act("relevance", step("relevance"), { method, limit: report.plan.limits
                  .relevance_batch })}>Preview a relevance batch</button>
        <button type="button" className="button" disabled={busy !== null || !refreshed}
                onClick={() => void act("context", step("context"), {})}>Gather structural context</button>
        <button type="button" className="button" disabled={busy !== null || !refreshed}
                onClick={() => void act("briefs", step("briefs"), { method, limit: report.plan.limits.brief_batch })}>
          Preview a brief batch</button>
      </div>
      <Result result={result} />
      <h3>Arrivals</h3>
      <p data-update-arrivals>{report.counts.run.arrivals} reports first held after the cutoff: {arrivalsLine(report)}.
        {report.counts.run.revised ? ` ${report.counts.run.revised} held report${report.counts.run.revised === 1
          ? " changed its" : "s changed their"} words.` : ""}
        {report.ungrouped ? ` ${report.ungrouped} are not in a story yet.` : ""}</p>
      {report.stories.length > 0 && <div className="admin-table-wrap"><table className="admin-table"
                                                                             data-news="update-stories">
        <thead><tr><th>Story</th><th>What it is</th><th>Relevance</th><th>Brief · explanation</th><th>Next</th></tr>
        </thead>
        <tbody>{report.stories.map((row) => (
          <tr key={row.story_id} data-update-story={row.story_id} data-kind={row.kind} data-tone={row.tone}>
            <td>{row.title}<br /><small>{row.publishers.join(", ")} · first reported {when(row.first_at)}
              {row.first_basis === "published" ? "" : row.first_basis === "dated" ? " (date only)" :
                " (first seen; no publication time stated)"}</small></td>
            <td><small>{row.kind_label}{row.topics.length ? ` · ${row.topics.map((topic) => topic.title).join(", ")}`
              : ""}</small></td>
            <td><small>{row.relevance.state.replaceAll("_", " ")}{row.relevance.basis ? ` (${row.relevance.basis})`
              : ""}</small></td>
            <td><small>{row.brief_state} · {row.explanation_state.replaceAll("_", " ")}{row.published_in_run
              ? " · published in this run" : ""}</small></td>
            <td><small>{row.next}</small></td>
          </tr>))}</tbody>
      </table></div>}
      {report.follow_ups.topics.length > 0 && <>
        <h3>Possible follow-ups to ongoing topics</h3>
        <label className="admin-form">Reason for relating<input value={reason} maxLength={300}
                                                              onChange={(event) => setReason(event.target.value)} />
        </label>
        <ul data-update-topics>{report.follow_ups.topics.map((row) => (
          <li key={`${row.story_id}|${row.topic_id}`}>“{row.title}” may be a further development of “{row.topic_title}”
            {" "}(with “{row.with_title}”; shared: {[...row.evidence.names, ...row.evidence.figures].join(", ")};
            {" "}{row.evidence.hours_after} h after it){" "}
            <button type="button" className="admin-link" disabled={!reason.trim() || busy !== null}
                    onClick={() => void act("relate", newsPaths.matches, {
                      story_a: row.story_id, story_b: row.with_story, decision: "related", reason,
                      topic_id: row.topic_id, topic_title: null, idempotency_key: newKey() })}>
              Relate to this topic</button></li>))}</ul>
      </>}
      {report.follow_ups.pairs.length > 0 && <p className="muted">{report.follow_ups.pairs.length === 1
        ? "1 pair that may report one development involves"
        : `${report.follow_ups.pairs.length} pairs that may report one development involve`} this run's stories;
        decide them under “Possibly the same development”.</p>}
      <h3>Paid preparation</h3>
      <p data-update-paid-line>{paidLine(report.paid)}</p>
      {report.paid.batches.length > 0 && <ul>{report.paid.batches.map((batch) => (
        <Approval key={batch.batch_id} batch={batch} done={done} />))}</ul>}
      {briefBatches.length > 0 && <>
        <h3>Publication</h3>
        {briefBatches.map((batchId) => <Publication key={batchId} batchId={batchId} done={done} />)}
      </>}
      <h3>Report</h3>
      <div className="admin-columns" data-update-report>
        <div><h4>Completed</h4><ul>{report.completed.map((row) => <li key={row}>{row}</li>)}</ul></div>
        <div><h4>Needs attention</h4>{report.attention.length ? <ul data-update-attention>{report.attention.map((row) =>
          <li key={row}>{row}</li>)}</ul> : <p className="muted">Nothing.</p>}</div>
        <div><h4>Failed</h4>{report.failed.length ? <ul data-update-failed>{report.failed.map((row) =>
          <li key={row}>{row}</li>)}</ul> : <p className="muted">Nothing failed.</p>}</div>
      </div>
      {report.next.length > 0 && <ol data-update-next>{report.next.map((row) => (
        <li key={`${row.step}|${row.command}`}>{row.text} <small><code>{row.command}</code></small></li>))}</ol>}
      <p className="muted" data-update-counts>Before this run: {report.counts.before.listed} listed stories of
        {" "}{report.counts.before.stories}. Now: {report.counts.after.listed} of {report.counts.after.stories}. This
        run: {report.counts.run.stories} stories reached, {report.counts.run.listed} listed,
        {" "}{report.counts.run.published_in_run} published in this run. {report.counts.statement}</p>
      <p className="muted">{report.statement}</p>
    </div>
  );
}

export function UpdatePanel({ version, done }: { version: number; done: () => void }) {
  const [plan, setPlan] = useState<UpdatePlan | null>(null);
  const [runs, setRuns] = useState<UpdateRunRow[]>([]);
  const [chosen, setChosen] = useState<string | null>(null);
  const [report, setReport] = useState<UpdateReport | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [label, setLabel] = useState("");
  const [official, setOfficial] = useState(true);
  const [result, setResult] = useState<AdminWrite<unknown> | null>(null);
  useEffect(() => {  // Read again after every desk action; reading requests, sends and writes nothing.
    const controller = new AbortController();
    void adminGet<{ plan: UpdatePlan; runs: UpdateRunRow[] }>(updatePaths.updates, controller.signal).then((read) => {
      if (read.state === "ready") {
        setPlan(read.data.plan);
        setRuns(read.data.runs);
        setChosen((current) => current ?? read.data.runs.at(-1)?.run_id ?? null);
      } else if (read.state === "error") setProblem(read.message);
    });
    return () => controller.abort();
  }, [version]);
  useEffect(() => {
    if (!chosen) return;
    const controller = new AbortController();
    void adminGet<{ report: unknown }>(updatePaths.run(chosen), controller.signal).then((read) => {
      if (read.state === "ready") {
        const found = reportProblem(read.data.report);
        if (found) setProblem(found);
        else setReport(read.data.report as UpdateReport);
      } else if (read.state === "error") setProblem(read.message);
    });
    return () => controller.abort();
  }, [chosen, version]);
  const start = async () => {
    const outcome = await adminPost<{ run: { run_id: string } }>(updatePaths.updates, {
      label, official, idempotency_key: newKey() });
    setResult(outcome);
    if (outcome.state === "saved") {
      setChosen(outcome.data.run.run_id);
      setLabel("");
      done();
    }
  };
  if (problem) return <p className="admin-problem" role="alert">{problem}</p>;
  if (!plan) return <p role="status">Reading the update plan…</p>;
  return (
    <div className="admin-panel" data-update-panel>
      <Plan plan={plan} />
      <div className="admin-form">
        <label>Label for a new run<input value={label} maxLength={200} onChange={(event) => setLabel(event.target.value)} />
        </label>
        <label className="admin-effort"><input type="checkbox" checked={official}
          onChange={(event) => setOfficial(event.target.checked)} /> Include the Event Inbox's official feeds</label>
        <button type="button" className="button" disabled={!label.trim() || plan.open_run !== null}
                onClick={() => void start()}>Start an update run</button>
        {plan.open_run && <small>Run {plan.open_run} has not refreshed yet; refresh it first.</small>}
      </div>
      <Result result={result} />
      {runs.length > 0 && <label className="admin-form">Run<select value={chosen ?? ""}
        onChange={(event) => setChosen(event.target.value)}>{runs.map((row) => (
          <option key={row.run_id} value={row.run_id}>{row.label} · {when(row.started_at)}</option>))}</select></label>}
      {report && report.run_id === chosen && <Report report={report} done={done} />}
    </div>
  );
}
