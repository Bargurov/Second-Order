import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { RatePath } from "../components/RatePath";
import { overviewHref } from "../eventOverview";
import { formatUtc } from "../format";
import { Link } from "../router";
import {
  BASIS_LABEL, INTERPRETATION_LABEL, MAX_NOTES, MOCK_OUTCOMES, MODE_LABEL, OUTCOME_LABEL, REVIEW_STATUSES,
  STATUS_LABEL, STATUS_NOTE, capturedText, fetchListing, fetchResearch, isCurrent, isUserRequest, latestReview,
  locator, markedSource, prepareResearch, requestEffort, reviewPayload, reviewProblems, saveReview, sendMock, sendPaid,
  statusLabel, type ListedRequest, type MockOutcome, type ResearchRequestView, type ResultView, type ReviewStatus,
} from "../researchAnalysis";
import "../eventContext.css";
import "../eventOverview.css";
import "../intake.css";
import "../research.css";

type Page =
  | { state: "loading" }
  | { state: "none"; others: number }
  | { state: "ready"; view: ResearchRequestView; others: number }
  | { state: "error"; message: string };
type Busy = null | "reading" | "preparing" | "sending" | "saving";
type Note = { text: string; tone: "done" | "error" } | null;

const order = (i: number) => ({ "--i": i }) as CSSProperties;
const UNCHANGED = "Nothing changed since the last saved version.";
const MOCK_CHOICE: Record<MockOutcome, string> = {
  analysis: "An analysis", no_additional_finding: "No additional finding", declined: "A decline",
};

/**
 * Evidence-first research analysis for one saved event: its separately versioned request, an explicit approval to
 * send it once, the recorded result with what the source establishes kept apart from the interpretation, and the
 * reviewer's own versions. The page only reads until the person acts; nothing is prepared, sent or saved on load.
 */
export function ResearchAnalysisPage({ captureId }: { captureId: string }) {
  const [page, setPage] = useState<Page>({ state: "loading" });
  const [busy, setBusy] = useState<Busy>(null);
  const [note, setNote] = useState<Note>(null);
  const [accountRows, setAccountRows] = useState<ListedRequest[]>([]);
  const acting = useRef(false);  // One action at a time, even for two clicks delivered in one task.

  const load = async (signal?: AbortSignal) => {
    const listed = await fetchListing(captureId, signal);
    if (listed.state !== "ready") return setPage({ state: "error", message: listed.message });
    // Users' requests run and are reviewed only through their accounts: this page lists them, read-only.
    setAccountRows(listed.data.requests.filter((row) => isUserRequest(row.request_id)));
    const rows = listed.data.requests.filter((row) => !isUserRequest(row.request_id));
    const latest = rows.at(-1);
    if (!latest) return setPage({ state: "none", others: 0 });
    if (latest.state !== "verified") {
      return setPage({ state: "error", message: `${latest.request_id} does not verify: ${latest.problem}` });
    }
    const read = await fetchResearch(latest.request_id, signal);
    setPage(read.state === "ready" ? { state: "ready", view: read.data, others: rows.length - 1 }
      : { state: "error", message: read.message });
  };

  useEffect(() => {
    document.title = "Research analysis · Second Order";
    const controller = new AbortController();
    load(controller.signal).catch(() => undefined);
    return () => controller.abort();
  }, [captureId]);

  /** Run one explicit action, then read what the records now say. Nothing is retried. */
  const run = async (kind: Exclude<Busy, null | "reading">, action: () => Promise<Note>) => {
    if (acting.current) return;
    acting.current = true;
    setBusy(kind);
    setNote(null);
    try {
      const result = await action();
      setBusy("reading");
      await load();
      setNote(result);
    } finally {
      acting.current = false;
      setBusy(null);
    }
  };

  /** Read the saved records again: a GET only, safe to repeat. */
  const reread = async () => {
    if (acting.current) return;
    acting.current = true;
    setBusy("reading");
    setNote(null);
    try {
      await load();
    } finally {
      acting.current = false;
      setBusy(null);
    }
  };

  const prepare = () => run("preparing", async () => {
    const done = await prepareResearch(captureId);
    return done.state === "saved"
      ? { text: done.data.created ? "The research request was prepared. Nothing was sent." :
          "This saved event already has its research request; it is shown unchanged.", tone: "done" }
      : { text: `The research request was not prepared: ${done.message}`, tone: "error" };
  });

  const ready = page.state === "ready" ? page.view : null;
  return (
    <article className="event-context research" data-capture={captureId}>
      <header className="event-context-header reveal" style={order(0)}>
        <p className="kicker">Evidence-first research analysis · Saved event</p>
        <h1>{ready?.event.headline ?? "Research analysis"}</h1>
        <p className="event-context-meaning">
          A separate analysis mode beside the market-hypothesis draft: what the source establishes, quoted and located
          in the captured text; any interpretation labelled apart from it; its assumptions, competing explanations,
          missing information and tests. It asks for no direction, horizon, forecast or trade.
        </p>
        <p className="research-back"><Link to={overviewHref("capture", captureId)}>Back to the event overview</Link></p>
      </header>
      {page.state === "loading" && <p className="event-context-state" role="status">Reading the saved records…</p>}
      {page.state === "error" && (
        <section className="card" role="alert">
          <p className="event-context-error">The research analysis could not be shown: {page.message}</p>
          <p><button className="button" type="button" disabled={busy !== null}
            onClick={() => void reread()}>Read it again</button></p>
        </section>
      )}
      {page.state === "none" && <PrepareCard busy={busy} onPrepare={prepare} />}
      {ready && (
        <>
          <RequestCard view={ready} others={page.state === "ready" ? page.others : 0} />
          {ready.attempt.state === "none" && <SendCard key={ready.request_sha256} view={ready} busy={busy}
            onMock={(outcome) => run("sending", async () => {
              const done = await sendMock(ready.request_id, ready.request_sha256, outcome);
              return done.state === "saved" ? { text: "The local mock response was recorded ($0, no provider contacted).",
                                                tone: "done" }
                : { text: `${done.state === "failed" ? "Refused" : "Not confirmed"}: ${done.message}`, tone: "error" };
            })}
            onPaid={() => run("sending", async () => {
              const done = await sendPaid(ready.request_id, ready.request_sha256,
                                          ready.cost_estimate.estimated_real_run_if_output_reaches_max_usd);
              return done.state === "saved" ? { text: "The paid response was recorded.", tone: "done" }
                : { text: `${done.state === "failed" ? "Refused" : "Not confirmed"}: ${done.message}`, tone: "error" };
            })} />}
          {ready.attempt.state !== "none" && !ready.result && (
            <AttemptCard view={ready} busy={busy} onCheck={() => void reread()} />
          )}
          {ready.result && <ResultSections view={ready} result={ready.result} />}
          <SourceCard view={ready} />
          {ready.result && <ReviewCard key={`${ready.result_view_sha256}:${ready.reviews.records.length}`}
            view={ready} busy={busy} onSave={(status, notes) => run("saving", async () => {
              const done = await saveReview(ready.request_id, reviewPayload(ready, status, notes));
              return done.state === "saved" ? { text: `Review version ${done.data.sequence} was saved.`, tone: "done" }
                : { text: `${done.state === "failed" ? "Not saved" : "Not confirmed"}: ${done.message}`, tone: "error" };
            })} />}
        </>
      )}
      {accountRows.length > 0 && <AccountRequests rows={accountRows} />}
      {note && <p className={`intake-message ${note.tone === "done" ? "is-done" : "is-error"}`}
        role={note.tone === "done" ? "status" : "alert"}>{note.text}</p>}
      {page.state !== "loading" && <RatePath captureId={captureId} variant="research"
        analysisSentAt={ready?.attempt.sent_at ?? null} />}
    </article>
  );
}

function Card({ id, title, children, className = "" }: { id: string; title: string; children: ReactNode;
                                                          className?: string }) {
  return (
    <section id={id} className={`card event-context-section overview-section research-card ${className}`}
      aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`}>{title}</h2>
      {children}
    </section>
  );
}

/** Analyses that user accounts prepared from this event: listed read-only; their runs, credits and reviews belong to
 * those accounts and are audited on the Admin screens. */
function AccountRequests({ rows }: { rows: ListedRequest[] }) {
  return (
    <Card id="research-account-requests" title="Analyses by user accounts">
      <ul className="research-account-requests">
        {rows.map((row) => (
          <li key={row.request_id} data-request={row.request_id}>
            <code>{row.request_id}</code> · Effort {requestEffort(row.request_id)} ·{" "}
            {row.state !== "verified" ? `does not verify: ${row.problem}`
              : row.result ? `recorded: ${row.result.outcome}` : `attempt ${row.attempt?.state ?? "none"}`}
          </li>
        ))}
      </ul>
      <p className="overview-note">Prepared, run and reviewed only by their accounts, under their approved credit quotes;
        nothing here sends or reviews them. See <Link to="/admin/actions">Actions</Link> for models, timing, usage and
        costs.</p>
    </Card>
  );
}

function PrepareCard({ busy, onPrepare }: { busy: Busy; onPrepare: () => void }) {
  return (
    <Card id="research-prepare" title="No research request yet">
      <p className="overview-gap" data-gap="none">This saved event has no research request, so there is no analysis.
        Preparing one writes a separate request beside the event's own saved request, which is not changed. Nothing is
        sent: a send needs its own explicit approval.</p>
      <p><button className="button research-prepare" type="button" disabled={busy !== null} onClick={onPrepare}>
        {busy === "preparing" ? "Preparing…" : "Prepare the research request"}</button></p>
    </Card>
  );
}

function RequestCard({ view, others }: { view: ResearchRequestView; others: number }) {
  const origin = view.origin;
  return (
    <Card id="research-request" title="Research request">
      <p className={`research-status is-${view.attempt.state}`} data-attempt={view.attempt.state}>
        <strong>{view.status}</strong>{view.attempt.state === "none" && <> · {view.not_an_analysis}</>}</p>
      <div className="intake-preview-head">
        <div><span>Model</span><strong>{view.model}</strong></div>
        <div><span>Effort</span><strong>{view.effort}</strong></div>
        <div><span>Maximum output</span><strong>{view.max_tokens.toLocaleString("en-US")} tokens</strong></div>
        <div><span>Planning estimate</span><strong>${view.cost_estimate.estimated_real_run_if_output_reaches_max_usd
          .toFixed(4)}</strong></div>
      </div>
      <dl className="draft-facts intake-facts research-facts">
        <div><dt>Request SHA-256</dt><dd><code className="draft-wrap research-sha">{view.request_sha256}</code></dd></div>
        <div><dt>Contract</dt><dd>{view.request_version} · {view.prompt_version} ·{" "}
          {view.reply_format ?? `strict tool ${view.tool}`} ·{" "}
          {view.request_bytes.toLocaleString("en-US")} bytes</dd></div>
        <div><dt>Prepared</dt><dd>{formatUtc(view.prepared_at)}</dd></div>
        <div><dt>Bound to</dt><dd>Capture <code>{view.capture_id}</code> (its own request{" "}
          <code>{view.capture.request_sha256.slice(0, 12)}…</code>, {view.capture.request_prompt_version}, unchanged;
          captured text <code>{view.capture.source_sha256.slice(0, 12)}…</code>, {view.capture.source_bytes} bytes)</dd></div>
        <div><dt>Inbox origin</dt><dd>{origin.state === "verified"
          ? <>Entry <code>{origin.item_id}</code>, version {origin.version} of {origin.versions}; origin record SHA-256{" "}
              <code>{origin.link_sha256?.slice(0, 12)}…</code>, checked on every read</>
          : origin.note ?? "None recorded."}</dd></div>
        <div><dt>Current builder</dt><dd>{view.current_code.comparison} · {view.current_code.detail}</dd></div>
      </dl>
      <p className="overview-note">{view.baseline.note} {view.retrospective}</p>
      {others > 0 && <p className="overview-note">{others} earlier research {others === 1 ? "request" : "requests"} of
        this event under another prompt version {others === 1 ? "is" : "are"} kept unchanged and not shown here.</p>}
      <details className="intake-request">
        <summary>Exact saved request (what a send posts, byte for byte)</summary>
        <pre>{JSON.stringify(view.request, null, 2)}</pre>
      </details>
    </Card>
  );
}

function CostDecision({ view }: { view: ResearchRequestView }) {
  const estimate = view.cost_estimate;
  return (
    <div className="paid-decision" role="note">
      <p className="paid-estimate">Planning estimate: <strong>
        ${estimate.estimated_real_run_if_output_reaches_max_usd.toFixed(4)}</strong> for one request to {view.model} at
        {" "}{view.effort} effort, if output reaches {view.max_tokens.toLocaleString("en-US")} tokens. Not a guaranteed
        billing ceiling.</p>
      <ul className="paid-assumptions">
        {estimate.assumptions.map((assumption) => <li key={assumption}>{assumption}</li>)}
      </ul>
      <p className="paid-source">Prices read on {estimate.prices.read_on} from <a href={estimate.prices.source}
        target="_blank" rel="noreferrer">Anthropic's pricing page</a>. {estimate.caveat}</p>
    </div>
  );
}

function SendCard({ view, busy, onMock, onPaid }: { view: ResearchRequestView; busy: Busy;
                                                    onMock: (outcome: MockOutcome) => void; onPaid: () => void }) {
  const [source, setSource] = useState<"mock" | "paid">("mock");
  const [outcome, setOutcome] = useState<MockOutcome>("analysis");
  const [confirmed, setConfirmed] = useState(false);
  const [paidConfirmed, setPaidConfirmed] = useState(false);
  const estimate = view.cost_estimate.estimated_real_run_if_output_reaches_max_usd.toFixed(4);
  const short = `${view.request_sha256.slice(0, 12)}…`;
  return (
    <Card id="research-send" title="Send it once">
      <p className="overview-note">One attempt per research request, ever, in either mode. Nothing is sent until you
        approve it here, and nothing is retried, regenerated or sent on load.</p>
      <fieldset className="intake-source-choice" disabled={busy !== null}>
        <legend>Response source</legend>
        <label><input type="radio" name="research-source" checked={source === "mock"}
          onChange={() => setSource("mock")} /> Local mock: $0, no provider contacted; synthetic content for testing the
          workflow</label>
        <label><input type="radio" name="research-source" checked={source === "paid"} disabled={!view.modes.paid.enabled}
          onChange={() => setSource("paid")} /> One paid {view.model} request, estimated up to ${estimate}</label>
        {!view.modes.paid.enabled && <p className="intake-source-note">{view.modes.paid.detail}</p>}
      </fieldset>
      {source === "mock" ? (
        <>
          <fieldset className="intake-mock-choice" disabled={busy !== null}>
            <legend>Mock response to exercise</legend>
            {MOCK_OUTCOMES.map((value) => (
              <label key={value}><input type="radio" name="research-mock" checked={outcome === value}
                onChange={() => setOutcome(value)} /> {MOCK_CHOICE[value]}</label>
            ))}
          </fieldset>
          <label className="intake-confirm">
            <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
            <span>I approve one local mock attempt using request <code>{short}</code>. No provider will be contacted,
              the content is synthetic, and this request cannot be attempted again afterwards.</span>
          </label>
          <div className="intake-actions">
            <button className="button research-send-mock" type="button" disabled={!confirmed || busy !== null}
              onClick={() => onMock(outcome)}>{busy === "sending" ? "Recording the mock response…"
                : "Approve mock response"}</button>
          </div>
        </>
      ) : (
        <>
          <CostDecision view={view} />
          <label className="intake-confirm paid-confirm">
            <input type="checkbox" checked={paidConfirmed} onChange={(event) => setPaidConfirmed(event.target.checked)} />
            <span>I approve one paid request to Anthropic for request <code>{short}</code>, estimated at up to $
              {estimate}. This is a planning estimate, not a billing ceiling. It is sent once, with no retry; if no
              reply arrives, it may still be billed.</span>
          </label>
          <div className="intake-actions paid-actions">
            <button className="button button-paid research-send-paid" type="button"
              disabled={!paidConfirmed || busy !== null || !view.modes.paid.enabled} onClick={onPaid}>
              {busy === "sending" ? "Waiting for the paid response…" : "Send one paid request"}</button>
          </div>
        </>
      )}
    </Card>
  );
}

function AttemptCard({ view, busy, onCheck }: { view: ResearchRequestView; busy: Busy; onCheck: () => void }) {
  return (
    <Card id="research-attempt" title="Recorded attempt">
      <div className={`intake-attempt is-${view.attempt.state}`} data-state={view.attempt.state} role="alert">
        <p>{view.attempt.detail}</p>
        {view.attempt.files.length > 0 && <p className="intake-attempt-detail">Recorded so far:{" "}
          {view.attempt.files.join(", ")}.</p>}
        <button type="button" className="button intake-check" disabled={busy !== null} onClick={onCheck}>
          {busy ? "Reading…" : "Read the recorded state again (nothing is sent)"}</button>
      </div>
    </Card>
  );
}

function List({ items, empty }: { items: ReactNode[]; empty: string }) {
  return items.length === 0 ? <p className="overview-note">{empty}</p>
    : <ul className="research-list">{items.map((item, index) => <li key={index}>{item}</li>)}</ul>;
}

function ResultSections({ view, result }: { view: ResearchRequestView; result: ResultView }) {
  const analysis = result.analysis;
  const usage = result.provenance.usage;
  return (
    <>
      <Card id="research-result" title="Recorded result">
        <div className="research-chips">
          <span className={`research-outcome is-${result.outcome}`} data-outcome={result.outcome}>
            {OUTCOME_LABEL[result.outcome]}</span>
          <span className={`research-mode is-${result.mode}`}>{MODE_LABEL[result.mode]}</span>
          <span className="research-mode">Not frozen · not evaluated</span>
        </div>
        {result.synthetic && <p className="research-synthetic" role="note">Synthetic: written by a local fixture to
          test the workflow. No model read the source, and none of it is research.</p>}
        <p className="overview-note">{result.outcome_note}</p>
        {result.problem && <p className="overview-gap" data-gap="problem">{result.problem}</p>}
        {result.model_text && (
          <blockquote className="research-model-text"><span className="overview-label">The model's own words: not an
            analysis</span>{result.model_text}</blockquote>
        )}
        <details className="overview-text research-provenance">
          <summary>Provenance of this result</summary>
          <dl className="draft-facts intake-facts">
            <div><dt>Response SHA-256</dt><dd><code className="draft-wrap">{result.provenance.response_sha256 ?? "no response kept"}</code></dd></div>
            <div><dt>Sent · received</dt><dd>{result.provenance.sent_at ? formatUtc(result.provenance.sent_at) : "not recorded"}
              {" · "}{result.provenance.received_at ? formatUtc(result.provenance.received_at) : "not recorded"}</dd></div>
            <div><dt>Response</dt><dd>{result.provenance.response_id ?? "none"} · {result.provenance.model ?? "no model"} · stop{" "}
              {result.provenance.stop_reason ?? "none"}{result.provenance.provider_request_id
                ? ` · provider request ${result.provenance.provider_request_id}` : ""}</dd></div>
            <div><dt>Cost</dt><dd>{result.mode === "mock" ? "$0: local mock, nothing billed." : <>
              {usage ? `${usage.input_tokens ?? "?"} input and ${usage.output_tokens ?? "?"} output tokens; ` : ""}
              usage-derived {result.provenance.usage_cost_usd !== null ? `$${result.provenance.usage_cost_usd.toFixed(4)}`
                : "unknown"}; planning estimate ${result.provenance.planning_estimate_usd?.toFixed(4) ?? "?"}. Billing is not
              verified here; the Console is authoritative.</>}</dd></div>
          </dl>
        </details>
      </Card>
      {analysis && (
        <>
          <Card id="research-established" title="What the source establishes" className="research-evidence">
            <p className="overview-label">The publisher's own words, found in the captured text by code</p>
            <ol className="research-established">
              {analysis.established.map((item) => (
                <li key={item.number} className={`research-statement is-${item.basis}`} data-basis={item.basis}>
                  <p className="research-basis"><span>{item.number}</span> {BASIS_LABEL[item.basis]}</p>
                  {item.quotes.map((quote, index) => (
                    <figure key={index} className="research-quote">
                      <blockquote>{quote.source_passage}</blockquote>
                      <figcaption>{locator(quote)}</figcaption>
                    </figure>
                  ))}
                  <p className="research-restated"><span className="overview-label">Restated</span>{item.statement}</p>
                </li>
              ))}
            </ol>
          </Card>
          <Card id="research-interpretation" title="Interpretation" className="research-reading">
            <p className="overview-label">{INTERPRETATION_LABEL}</p>
            {analysis.interpretation.kind === "finding" ? (
              <p className="research-reading-text" data-kind="finding">{analysis.interpretation.text}</p>
            ) : (
              <p className="research-reading-text" data-kind="no_additional_finding"><strong>No additional finding.</strong>{" "}
                {analysis.interpretation.text}</p>
            )}
            {analysis.interpretation.based_on.length > 0 && (
              <p className="overview-note">Relies on established {analysis.interpretation.based_on.length === 1
                ? "statement" : "statements"} {analysis.interpretation.based_on.join(", ")}.</p>
            )}
          </Card>
          <Card id="research-unknowns" title="What it rests on, and what is unknown" className="research-unknowns">
            <h3>Assumptions</h3>
            <List items={analysis.assumptions} empty="None stated." />
            <h3>Competing explanations</h3>
            <List items={analysis.competing_explanations.map((item) => <>{item.explanation} <span
              className="research-aside">Would be told apart by: {item.would_distinguish}</span></>)} empty="None stated." />
            <h3>Missing information</h3>
            <List items={analysis.missing_information} empty="None stated." />
            <h3>What would test it</h3>
            <List items={analysis.tests.map((item) => <>{item.check} <span className="research-aside">Counts against it
              if: {item.counts_against_if}</span></>)} empty="None stated." />
            <h3>Earlier baseline</h3>
            <p className="overview-note">{result.baseline.note}</p>
          </Card>
        </>
      )}
      <p className="overview-note research-retrospective">{result.retrospective} Request{" "}
        <code>{view.request_sha256.slice(0, 12)}…</code>.</p>
    </>
  );
}

function SourceCard({ view }: { view: ResearchRequestView }) {
  const source = capturedText(view.request) ?? "";
  const pieces = markedSource(source, view.result?.analysis ?? null);
  const marked = pieces.some((piece) => piece.statements.length > 0);
  return (
    <Card id="research-source" title="Captured text">
      <p className="overview-note">The text the saved request carries, as captured ({Array.from(source).length.toLocaleString(
        "en-US")} characters; nothing was downloaded).{marked ? " Quoted passages are marked with their statement numbers." : ""}</p>
      <details className="overview-text research-source" open={marked}>
        <summary>{marked ? "Captured text with the quoted passages marked" : "Captured text"}</summary>
        <pre>{pieces.map((piece, index) => piece.statements.length > 0
          ? <mark key={index} title={`Quoted in statement ${piece.statements.join(", ")}`}>{piece.text}<sup>
              {piece.statements.join(",")}</sup></mark>
          : <span key={index}>{piece.text}</span>)}</pre>
      </details>
    </Card>
  );
}

function ReviewCard({ view, busy, onSave }: { view: ResearchRequestView; busy: Busy;
                                              onSave: (status: ReviewStatus | null, notes: string) => void }) {
  const latest = latestReview(view);
  const current = latest && isCurrent(latest, view) ? latest : null;
  const [status, setStatus] = useState<ReviewStatus | null>(current?.status ?? null);
  const [notes, setNotes] = useState(current?.notes ?? "");
  if (view.reviews.state !== "verified") {
    return (
      <Card id="research-review" title="Your review">
        <p className="event-context-error" role="alert">{view.reviews.problem} Saving is not offered until the saved
          versions verify.</p>
      </Card>
    );
  }
  const problems = reviewProblems(view, status, notes);
  const unchanged = problems.includes(UNCHANGED);  // Not an error: the form still shows the saved version.
  const shown = problems.filter((problem) => problem !== UNCHANGED);
  return (
    <Card id="research-review" title="Your review" className="research-review">
      <p className="overview-note">Saved as a new version each time, attributed to you, the local reviewer, and bound to
        the result shown (result view SHA-256 <code>{view.result_view_sha256?.slice(0, 12)}…</code>). A review never
        changes the recorded result.</p>
      {view.reviews.records.length > 0 && (
        <ol className="research-versions">
          {view.reviews.records.map((record) => (
            <li key={record.review_id} data-current={isCurrent(record, view) ? "true" : "false"}>
              <strong>Version {record.sequence} · {statusLabel(record.status)}</strong>{" "}
              <span>saved {formatUtc(record.saved_at)}{isCurrent(record, view) ? "" :
                " against an earlier result view, so it is not the current judgment"}</span>
              {record.notes && <blockquote className="analysis-note">{record.notes}</blockquote>}
            </li>
          ))}
        </ol>
      )}
      <fieldset className="intake-source-choice research-status-choice" disabled={busy !== null}>
        <legend>Your judgment</legend>
        {[null, ...REVIEW_STATUSES].map((value) => (
          <label key={value ?? "none"}><input type="radio" name="research-review-status" checked={status === value}
            onChange={() => setStatus(value)} /> {value ? STATUS_LABEL[value] : "No judgment, notes only"}</label>
        ))}
        <p className="intake-source-note">{STATUS_NOTE}</p>
      </fieldset>
      <label className="research-notes">
        <span>Notes</span>
        <textarea rows={6} maxLength={MAX_NOTES} value={notes} disabled={busy !== null}
          onChange={(event) => setNotes(event.target.value)} />
      </label>
      {shown.length > 0 && (notes || status) && <ul className="review-problems">{shown.map((problem) =>
        <li key={problem}>{problem}</li>)}</ul>}
      {unchanged && <p className="overview-note research-saved-note">The form shows the latest saved version. Change the
        judgment or the notes to save a new one.</p>}
      <div className="intake-actions">
        <button className="button research-save-review" type="button" disabled={problems.length > 0 || busy !== null}
          onClick={() => onSave(status, notes)}>{busy === "saving" ? "Saving…" : "Save review version"}</button>
      </div>
    </Card>
  );
}
