// The News desk's economic relevance (news-relevance-0.1, relevance-batch-0.1): every current story's relevance with
// who or what decided it and why, counted by state so nothing is hidden; an editor's judgement with a reason; and a
// bounded assessment batch: a recorded preview naming each story and why it was selected, for the paid method each
// exact request's planning estimate and the total, one explicit approval that sends each saved request at most once.
// The assisted path's annotations are imported from the command line. Reading this panel requests nothing.
import { useEffect, useState } from "react";
import { adminGet, adminPost, newKey, type AdminWrite } from "./adminApi.ts";
import { usd, when } from "./adminFormat.ts";
import { newsPaths, type DeskStory, type RelevanceBatch, type RelevanceBatchStatus, type RelevanceQueue,
  type RelevanceRow } from "./newsDesk.ts";

export const RELEVANCE_LABEL: Record<string, string> = {
  relevant: "Relevant", outside_scope: "Outside the scope", insufficient: "Too little to tell",
  needs_review: "Needs an editor", unavailable: "Assessment failed", restricted: "Restricted (terms)",
  pending: "Not assessed",
};
const BASIS_LABEL: Record<string, string> = {
  editor: "editor", model: "AI model (paid, in this application)", assisted: "AI assistant (declared)",
  synthetic: "SYNTHETIC",
};
const VERDICTS: [string, string][] = [["relevant", "Relevant"], ["outside_scope", "Outside the scope"],
  ["insufficient_information", "Too little to tell"], ["cleared", "Clear the editor's judgement"]];

function Result({ result }: { result: AdminWrite<unknown> | null }) {
  if (!result) return null;
  return result.state === "saved" ? <p className="admin-ok" role="status">Done.</p>
    : <p className="admin-problem" role="alert">{result.message}</p>;
}

/** An editor's judgement of one story's relevance, with a reason; repeated submissions record nothing new. */
export function JudgeForm({ storyId, done }: { storyId: string; done: () => void }) {
  const [verdict, setVerdict] = useState("outside_scope");
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<AdminWrite<unknown> | null>(null);
  const judge = async () => {
    const outcome = await adminPost(newsPaths.story(storyId, "relevance"),
                                    { verdict, reason, idempotency_key: newKey() });
    setResult(outcome);
    if (outcome.state === "saved") {
      setReason("");
      done();
    }
  };
  return (
    <div className="admin-form" data-judge={storyId}>
      <label>Editor's judgement<select value={verdict} onChange={(event) => setVerdict(event.target.value)}>
        {VERDICTS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>Reason<input value={reason} maxLength={300} onChange={(event) => setReason(event.target.value)} /></label>
      <button type="button" className="button" disabled={!reason.trim()} onClick={() => void judge()}>Record</button>
      <Result result={result} />
    </div>
  );
}

function QueueRow({ row, done }: { row: RelevanceRow; done: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <tr data-relevance-story={row.story_id} data-relevance={row.state}>
      <td>{row.title}<br /><small>{row.publishers.join(", ")} · {when(row.latest_at)} · {row.material.coverage
        .replaceAll("_", " ")}{row.hot ? " · in Hot now" : ""}</small></td>
      <td>{RELEVANCE_LABEL[row.state] ?? row.state}{row.basis ? <><br /><small>{BASIS_LABEL[row.basis] ?? row.basis}
        {row.current === false ? " · of earlier material" : ""}</small></> : null}
        {row.importance ? <><br /><small>importance {row.importance.level} ({row.importance.points})</small></> : null}</td>
      <td><small>{row.explanation}{row.decision && row.decision.state !== row.state && row.basis === "editor"
        ? ` (the assessment said: ${RELEVANCE_LABEL[row.decision.state]})` : ""}{row.next ? ` Next batch: ${row.next}`
        : ""}</small>
        {open ? <JudgeForm storyId={row.story_id} done={done} />
          : <><br /><button type="button" className="admin-link" onClick={() => setOpen(true)}>Judge</button></>}</td>
    </tr>
  );
}

export function RelevancePanel({ version, done }: { version: number; done: () => void }) {
  const [queue, setQueue] = useState<RelevanceQueue | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [filter, setFilter] = useState("all");
  useEffect(() => {
    const controller = new AbortController();
    void adminGet<{ relevance: RelevanceQueue }>(newsPaths.relevance, controller.signal).then((read) => {
      if (read.state === "ready") setQueue(read.data.relevance);
      else if (read.state === "error") setProblem(read.message);
    });
    return () => controller.abort();
  }, [version]);
  if (problem) return <p className="admin-problem" role="alert">{problem}</p>;
  if (!queue) return <p role="status">Reading the relevance queue…</p>;
  const rows = filter === "all" ? queue.rows : queue.rows.filter((row) => row.state === filter);
  return (
    <div className="admin-panel" data-relevance-panel>
      <p className="muted">{queue.statement}</p>
      <p data-relevance-counts>Current stories ({queue.window_hours / 24} days): {Object.entries(queue.counts)
        .filter(([, value]) => value > 0).map(([state, value]) => `${value} ${RELEVANCE_LABEL[state].toLowerCase()}`)
        .join(" · ")}. {queue.candidates} would be assessed by the next batch. Decision {queue.decision_version},
        importance {queue.importance_version}, prompt {queue.versions.prompt_version}.</p>
      <div className="admin-form">
        <label>Show<select value={filter} onChange={(event) => setFilter(event.target.value)}>
          <option value="all">every current story</option>
          {Object.keys(RELEVANCE_LABEL).map((state) => <option key={state} value={state}>{RELEVANCE_LABEL[state]}
            ({queue.counts[state] ?? 0})</option>)}</select></label>
      </div>
      <div className="admin-table-wrap">
        <table className="admin-table" data-news="relevance">
          <thead><tr><th>Story (newest first)</th><th>Relevance</th><th>Why, and the editor's judgement</th></tr></thead>
          <tbody>{rows.map((row) => <QueueRow key={row.story_id} row={row} done={done} />)}</tbody>
        </table>
      </div>
      <AssessmentBatch sending={queue.sending} done={done} />
    </div>
  );
}

function AssessmentBatch({ sending, done }: { sending: RelevanceQueue["sending"]; done: () => void }) {
  const [method, setMethod] = useState<"model" | "assisted">("model");
  const [limit, setLimit] = useState(20);
  const [retry, setRetry] = useState(false);
  const [batch, setBatch] = useState<RelevanceBatch | null>(null);
  const [status, setStatus] = useState<RelevanceBatchStatus | null>(null);
  const [approve, setApprove] = useState(false);
  const [result, setResult] = useState<AdminWrite<unknown> | null>(null);
  const reread = async (id: string) => {
    const read = await adminGet<{ batch: RelevanceBatch; status: RelevanceBatchStatus }>(newsPaths.relevanceBatch(id));
    if (read.state === "ready") {
      setBatch(read.data.batch);
      setStatus(read.data.status);
    }
  };
  const preview = async () => {
    const outcome = await adminPost<{ batch: RelevanceBatch }>(newsPaths.relevanceBatches,
                                                               { method, limit, story_ids: null, retry_failed: retry });
    setResult(outcome);
    if (outcome.state === "saved") await reread(outcome.data.batch.batch_id);
  };
  const send = async () => {
    if (!batch || !approve) return;
    const outcome = await adminPost(newsPaths.relevanceBatchAction(batch.batch_id, "approval"), {
      batch_id: batch.batch_id, approve_paid_requests: true, estimated_max_usd_total: batch.estimated_max_usd_total });
    setApprove(false);
    setResult(outcome);
    await reread(batch.batch_id);
    done();
  };
  return (
    <div data-relevance-batch-panel>
      <h3>Assess current stories</h3>
      <p className="muted">Only reports whose publishers allow their use by a model are ever sent; restricted stories
        wait for an editor. The preview records the selection and sends nothing. {sending.detail}</p>
      <div className="admin-form">
        <label>Method<select value={method} onChange={(event) => setMethod(event.target.value as "model" | "assisted")}>
          <option value="model">AI model in this application ({sending.model}; paid, after approval)</option>
          <option value="assisted">AI assistant or editor outside it (packet and import, $0 here)</option>
        </select></label>
        <label>Stories<input type="number" min={1} max={40} value={limit}
                             onChange={(event) => setLimit(Number(event.target.value))} /></label>
        <label className="admin-effort"><input type="checkbox" checked={retry}
          onChange={(event) => setRetry(event.target.checked)} /> Also failed ones (a new attempt)</label>
        <button type="button" className="button" onClick={() => void preview()}>Preview the batch</button>
      </div>
      <Result result={result} />
      {batch && (
        <div data-relevance-batch={batch.batch_id}>
          <p><strong>{batch.batch_id}</strong> · {batch.method}{batch.model ? ` · ${batch.model}` : ""} ·{" "}
            {batch.items.length} stories · created {when(batch.created_at)}</p>
          <ol>{batch.items.map((item) => {
            const now = status?.items.find((row) => row.story_id === item.story_id);
            return (
              <li key={item.story_id} data-relevance-item={item.story_id}>
                {item.title} <small>· {item.reason} · {item.material.coverage.replaceAll("_", " ")}
                  {item.request ? ` · estimate ${usd(item.request.estimated_max_usd)}` : ""}
                  {item.attempt > 1 ? ` · attempt ${item.attempt}` : ""}
                  {now?.attempt ? ` · ${now.attempt.state}` : ""}{now?.state ? ` · now ${RELEVANCE_LABEL[now.state] ??
                    now.state}` : ""}{now?.material_changed ? " · material changed since the preview" : ""}</small>
              </li>
            );
          })}</ol>
          {batch.left.length > 0 && <p className="muted">Left out: {batch.left.map((row) => `${row.title} (${row.why})`)
            .join("; ")}</p>}
          {batch.method === "model" ? (
            <div className="admin-attention">
              <p>Planning estimate for the whole batch: {usd(batch.estimated_max_usd_total ?? 0)} (each saved request
                once, at most; an estimate at each request's output limit, not a billing ceiling).</p>
              <label className="admin-effort"><input type="checkbox" checked={approve}
                onChange={(event) => setApprove(event.target.checked)} /> I approve these billed requests at up to this
                total; each is sent once and never retried.</label>
              <button type="button" className="button" disabled={!approve} onClick={() => void send()}>Send</button>
            </div>
          ) : <p className="muted">Annotate from the packet (`python -m second_order news relevance packet
            {" "}{batch.batch_id}`), then import with `news relevance import {batch.batch_id} --annotations FILE
            --assistant-tool NAME`. Each annotation is checked against the schema and its quotes against the
            material.</p>}
        </div>
      )}
    </div>
  );
}

/** One story's relevance on its desk: the decision, the annotation with its evidence check, every earlier one, the
 * editors' judgements, and the form to record one. */
export function StoryRelevance({ story, done }: { story: DeskStory; done: () => void }) {
  const relevance = story.relevance;
  const latest = story.relevance_history.filter((row) => row.outcome === "annotated").at(-1);
  return (
    <div data-story-relevance={relevance.state}>
      <h3>Economic relevance</h3>
      <p>{RELEVANCE_LABEL[relevance.state]}{relevance.basis ? ` · ${BASIS_LABEL[relevance.basis] ?? relevance.basis}`
        : ""}{relevance.current === false ? " · assessed on earlier material" : ""}: {relevance.explanation}</p>
      {latest?.annotation && (
        <details>
          <summary>The latest annotation ({latest.method}, {when(latest.at)}; quotes found {latest.evidence.found},
            not found {latest.evidence.not_found})</summary>
          <p><small>{latest.annotation.report_kind}{latest.annotation.event_type ? ` · ${latest.annotation.event_type}`
            : ""} · reach {latest.annotation.scope.reach} · verdict {latest.annotation.verdict} · decision
            {" "}{latest.decision?.state}: {latest.decision?.reasons.join(" ")}</small></p>
          <p>{latest.annotation.change}</p>
          <ul>{latest.annotation.dimensions.map((row) => (
            <li key={row.dimension}><small>{row.dimension}{latest.evidence.supported_dimensions.includes(row.dimension)
              ? "" : " (no quote found)"}: {row.how}</small></li>))}</ul>
          <ul>{latest.evidence.quotes.map((row) => (
            <li key={row.where}><small>{row.where}: {row.found ? `found in the ${row.field}` : row.problem}</small></li>
          ))}</ul>
          <p><small>Missing: {latest.annotation.missing.join(" ") || "nothing stated"} · versions{" "}
            {Object.values(latest.versions).join(", ")}</small></p>
        </details>
      )}
      {story.relevance_history.length > 1 && <p><small>{story.relevance_history.length} annotations and attempts
        recorded; the latest of the current material decides.</small></p>}
      {story.relevance_reviews.length > 0 && <ul>{story.relevance_reviews.map((row, index) => (
        <li key={index}><small>{row.verdict} · {row.actor} · {when(row.at)} · {row.reason}</small></li>))}</ul>}
      <JudgeForm storyId={story.story_id} done={done} />
    </div>
  );
}
