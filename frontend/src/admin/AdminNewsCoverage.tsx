// The News desk's brief coverage and batch preparation (news-coverage-0.1, news-batch-0.1): whether each important
// story (Hot now, in its order) gives a reader a useful prepared brief, what this server is ready to do, and a bounded
// batch: a recorded preview with each story's material and, for a paid model draft, the exact total estimate; one
// explicit approval that sends each saved request at most once; publication as its own decision, with a review recorded
// only when the operator says they read the versions. The assisted path's drafts are imported from the command line.
import { useEffect, useState } from "react";
import { adminGet, adminPost, type AdminWrite } from "./adminApi.ts";
import { usd, when } from "./adminFormat.ts";
import { newsPaths, type Batch, type BatchStatus, type Coverage } from "./newsDesk.ts";

const STATE_LABEL: Record<string, string> = {
  ready: "Brief ready", update: "Brief of earlier material", drafted: "Drafted, awaiting publication",
  pending: "Awaiting a brief", insufficient: "Not enough material", withdrawn: "Brief withdrawn",
  restricted: "Headline only (publisher terms)",
};

function Result({ result }: { result: AdminWrite<unknown> | null }) {
  if (!result) return null;
  return result.state === "saved" ? <p className="admin-ok" role="status">Done.</p>
    : <p className="admin-problem" role="alert">{result.message}</p>;
}

export function CoveragePanel({ version }: { version: number }) {
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  useEffect(() => {  // Read again after every desk action; the last coverage read stays shown meanwhile.
    const controller = new AbortController();
    void adminGet<{ coverage: Coverage }>(newsPaths.coverage, controller.signal).then((read) => {
      if (read.state === "ready") setCoverage(read.data.coverage);
      else if (read.state === "error") setProblem(read.message);
    });
    return () => controller.abort();
  }, [version]);
  if (problem) return <p className="admin-problem" role="alert">{problem}</p>;
  if (!coverage) return <p role="status">Reading the coverage…</p>;
  const important = coverage.important;
  const ready = coverage.readiness;
  return (
    <div className="admin-panel" data-coverage-panel>
      <p data-coverage-summary>{important.counts.ready} of {important.eligible} important stories with summarisable
        material have a current brief ({important.stories} in Hot now, each assessed as an economic development or
        marked major; {important.counts.restricted} are headlines only under their publishers' terms). Every story:
        {" "}{coverage.all.counts.ready} ready of {coverage.all.stories}.</p>
      <p className="muted" data-coverage-relevance>{coverage.current_relevance.stories} current stories by relevance:
        {" "}{Object.entries(coverage.current_relevance.counts).filter(([, value]) => value > 0)
          .map(([state, value]) => `${value} ${state.replaceAll("_", " ")}`).join(", ")}.</p>
      {coverage.explanations && <p className="muted" data-coverage-explanations>Economic explanations, all{" "}
        {coverage.explanations.listed.stories} listed stories: {Object.entries(coverage.explanations.listed.counts)
          .filter(([, value]) => value > 0).map(([state, value]) => `${value} ${state.replaceAll("_", " ")}`)
          .join(", ")}. {coverage.explanations.statement}</p>}
      <ul className="admin-readiness" data-readiness>
        <li data-ready="newsroom">Newsroom store {ready.newsroom.schema ?? "not created yet"}{ready.newsroom.needs_upgrade
          ? ": run `python -m second_order news upgrade` (after `news backup`) before preparing" : ""}</li>
        <li data-ready="paid">{ready.paid_drafting.detail}</li>
        {ready.credit_policy && <li data-ready="credits">{ready.credit_policy.detail}</li>}
      </ul>
      <div className="admin-table-wrap">
        <table className="admin-table" data-news="coverage">
          <thead><tr><th>Story (Hot now order)</th><th>State</th><th>Explanation</th><th>Material</th><th>Texts</th></tr></thead>
          <tbody>{important.rows.map((row) => (
            <tr key={row.story_id} data-coverage-story={row.story_id} data-state={row.state}>
              <td>{row.title}<br /><small>{row.publishers.join(", ")} · {when(row.latest_at)}</small></td>
              <td>{STATE_LABEL[row.state] ?? row.state}{row.insufficient ? <><br /><small>{row.insufficient}</small></>
                : null}</td>
              <td data-explanation={row.explanation}><small>{(row.explanation ?? "–").replaceAll("_", " ")}</small></td>
              <td><small>{row.material.coverage.replaceAll("_", " ")} · {row.material.reports} reports</small></td>
              <td><small>{row.material.texts} held{row.material.texts_open ? `, ${row.material.texts_open} could be ` +
                "retrieved" : ""}</small></td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </div>
  );
}

export function BatchPanel({ done }: { done: () => void }) {
  const [method, setMethod] = useState<"model" | "assisted">("model");
  const [limit, setLimit] = useState(10);
  const [batch, setBatch] = useState<Batch | null>(null);
  const [status, setStatus] = useState<BatchStatus | null>(null);
  const [approve, setApprove] = useState(false);
  const [reason, setReason] = useState("");
  const [reviewed, setReviewed] = useState(false);
  const [result, setResult] = useState<AdminWrite<unknown> | null>(null);
  const reread = async (id: string) => {
    const read = await adminGet<{ batch: Batch; status: BatchStatus }>(newsPaths.batch(id));
    if (read.state === "ready") {
      setBatch(read.data.batch);
      setStatus(read.data.status);
    }
  };
  const preview = async () => {
    const outcome = await adminPost<{ batch: Batch }>(newsPaths.batches, { method, limit, story_ids: null });
    setResult(outcome);
    if (outcome.state === "saved") await reread(outcome.data.batch.batch_id);
  };
  const send = async () => {
    if (!batch || !approve) return;
    const outcome = await adminPost(newsPaths.batchAction(batch.batch_id, "approval"), {
      batch_id: batch.batch_id, approve_paid_requests: true, estimated_max_usd_total: batch.estimated_max_usd_total });
    setApprove(false);
    setResult(outcome);
    await reread(batch.batch_id);
    done();
  };
  const publish = async () => {
    if (!batch) return;
    const outcome = await adminPost(newsPaths.batchAction(batch.batch_id, "publication"), { reason, reviewed });
    setReviewed(false);
    setResult(outcome);
    await reread(batch.batch_id);
    done();
  };
  return (
    <div className="admin-panel" data-batch-panel>
      <p>A batch prepares the important stories that need a brief, in Hot now's order, before readers open them. The
        preview records the selection and sends nothing.</p>
      <div className="admin-form">
        <label>Method<select value={method} onChange={(event) => setMethod(event.target.value as "model" | "assisted")}>
          <option value="model">AI model in this application (paid, after approval)</option>
          <option value="assisted">AI assistant or editor outside it (packet and import, $0 here)</option>
        </select></label>
        <label>Stories<input type="number" min={1} max={25} value={limit}
                             onChange={(event) => setLimit(Number(event.target.value))} /></label>
        <button type="button" className="button" onClick={() => void preview()}>Preview the batch</button>
      </div>
      <Result result={result} />
      {batch && (
        <div data-batch={batch.batch_id}>
          <p><strong>{batch.batch_id}</strong> · {batch.method} · {batch.items.length} stories · created
            {" "}{when(batch.created_at)}{batch.texts_open ? ` · ${batch.texts_open} publication texts could still be ` +
            "retrieved first (they would make better material)" : ""}</p>
          <ol>{batch.items.map((item) => {
            const now = status?.items.find((row) => row.story_id === item.story_id);
            return (
              <li key={item.story_id} data-batch-item={item.story_id}>
                {item.title} <small>· {item.action} · {item.material.coverage.replaceAll("_", " ")}
                  {item.draft ? `${item.draft.stage ? ` · stage ${item.draft.stage}` : ""} · estimate ` +
                    usd(item.draft.estimated_max_usd) : ""}
                  {now ? ` · ${now.attempt ? `attempt ${now.attempt.state}` : ""}${now.version ? ` · version ` +
                    `${now.version}${now.published ? " published" : ""}` : ""}${now.material_changed ? " · material " +
                    "changed since the preview" : ""}${now.insufficient ? ` · insufficient: ${now.insufficient}` : ""}`
                    : ""}</small>
              </li>
            );
          })}</ol>
          {batch.method === "model" ? (
            <div className="admin-attention">
              <p>Planning estimate for the whole batch: {usd(batch.estimated_max_usd_total ?? 0)} (each saved request
                once, at most; not a billing ceiling).{batch.followup_estimated_max_usd_total ? " Stage 2 of its " +
                  `stage-1 stories is planned at about ${usd(batch.followup_estimated_max_usd_total)} more: ` +
                  "prepared from each checked stage 1 and approved in a later batch, not by this one." : ""}</p>
              <label className="admin-effort"><input type="checkbox" checked={approve}
                onChange={(event) => setApprove(event.target.checked)} /> I approve these billed requests at up to this
                total; each is sent once and never retried.</label>
              <button type="button" className="button" disabled={!approve} onClick={() => void send()}>Send</button>
            </div>
          ) : <p className="muted">Write the drafts from the packet (GET {newsPaths.batchAction(batch.batch_id,
            "packet")} or `python -m second_order news batch packet {batch.batch_id}`), then import them with `news
            batch import {batch.batch_id} --drafts FILE --assistant-tool NAME`.</p>}
          <div className="admin-form">
            <label>Reason for publishing<input value={reason} maxLength={300}
                                               onChange={(event) => setReason(event.target.value)} /></label>
            <label className="admin-effort"><input type="checkbox" checked={reviewed}
              onChange={(event) => setReviewed(event.target.checked)} /> I read every version this publishes</label>
            <button type="button" className="button" disabled={!reason.trim()} onClick={() => void publish()}>Publish
              the publishable versions</button>
          </div>
        </div>
      )}
    </div>
  );
}
