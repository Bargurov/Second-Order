import { useCallback, useEffect, useState } from "react";
import type { Loaded } from "../api";
import { officialLink, utcStamp, type InboxItem } from "../inbox";
import {
  approveRequest, attemptLabel, currentEntry, feedDateNote, fetchRequests, fetchSelection, groupedSections, scopeNote,
  listedLabel, MAX_SELECTION, previewTriage, recheckLabel, recheckOutcome, recheckResponse, sameEntries, sendOutcome,
  statusLabel, triageRows, type Mode, type RequestsListing, type RequestView, type SelectionView, type TriageInput,
  type TriageRow,
} from "../triage";
import "../triage.css";

type Phase = "idle" | "previewing" | "reading" | "sending" | "checking";
type Message = { text: string; tone: "done" | "error"; reread?: boolean };

/**
 * Headline triage inside the Event Inbox. The operator selects up to 25 entries (current or retained); the server
 * resolves saved results first, so a preview shows what is reused, what still needs a result, which earlier entries
 * come along only as comparison context, and the one request (or none) the missing work needs, with its exact bytes and
 * a planning estimate. A response needs its own explicit approval. Nothing is refreshed, fetched, scheduled or sent in
 * the background, and a failed or uncertain entry is requested again only when the operator ticks it.
 */
export function HeadlineTriage({ current, selected, onSelect, onClear, onAnalyze, busy }: {
  current: InboxItem[];
  selected: string[];
  onSelect: (ids: string[]) => void;
  onClear: () => void;
  onAnalyze: (item: InboxItem) => void;
  busy: boolean;
}) {
  const [mode, setMode] = useState<Mode>("simulated");
  const [reprocess, setReprocess] = useState<string[]>([]);
  const [view, setView] = useState<SelectionView | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [message, setMessage] = useState<Message | null>(null);
  const [requests, setRequests] = useState<Loaded<RequestsListing>>({ state: "loading" });

  const loadRequests = useCallback(async (signal?: AbortSignal) => {
    const loaded = await fetchRequests(signal).catch(() => null);
    if (loaded) setRequests(loaded);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void loadRequests(controller.signal);
    return () => controller.abort();
  }, [loadRequests]);

  const paidEnabled = requests.state === "ready" && requests.data.modes.paid.enabled;
  const working = phase !== "idle";
  const chosen = reprocess.filter((id) => selected.includes(id));

  const preview = async () => {
    if (working || selected.length === 0) return;
    setPhase("previewing");
    setMessage(null);
    const result = await previewTriage(selected, mode, chosen);
    setPhase("idle");
    void loadRequests();
    if (result.state !== "done") {
      setMessage({ text: `Nothing was planned or saved: ${result.message}`, tone: "error" });
      return;
    }
    setView(result.value);
    const plan = result.value.plan;
    setMessage({ tone: "done", text: plan.requests === 0
      ? "Nothing to request: every selected entry has a saved result or an unresolved earlier attempt, and every candidate pair was compared. Nothing was written or sent."
      : result.value.prepared_now ? "The exact request for the missing work was saved locally. Nothing was sent."
        : "This exact request was already saved; nothing was written or sent." });
  };

  const reread = async () => {
    if (!view || working) return;
    setPhase("reading");
    const loaded = await fetchSelection(view.items.map((row) => row.input.id), view.mode, view.plan.reprocess);
    setPhase("idle");
    void loadRequests();
    if (loaded.state === "ready") setView(loaded.data);
    else setMessage({ text: `The selection could not be read again: ${loaded.state === "loading" ? "it did not load" : loaded.message}`, tone: "error" });
    return loaded.state === "ready" ? loaded.data : null;
  };

  const approve = async () => {
    if (!view || working) return;
    setPhase("sending");
    setMessage(null);
    const result = await approveRequest(view);
    setPhase("idle");
    if (result.state !== "done") {
      setMessage({ tone: "error", reread: result.state === "unconfirmed", text: result.state === "unconfirmed"
        ? `The outcome is not confirmed: ${result.message}` : `Nothing was reserved or sent: ${result.message}` });
      void loadRequests();
      return;
    }
    // The server's own record of this attempt decides the message: a plan with nothing left to request says nothing
    // about whether the response was accepted.
    const recorded = (result.value as RequestView).attempts?.[view.mode];
    const outcome = sendOutcome(view.mode, recorded);
    await reread();
    setMessage(outcome);
  };

  const recheck = async (row: RequestsListing["requests"][number], name: Mode) => {
    const attempt = row.attempts?.[name];
    if (working || !attempt?.attempt || !attempt.response_sha256) return;
    setPhase("checking");
    setMessage(null);
    const result = await recheckResponse(row.triage_id, attempt.attempt, attempt.response_sha256);
    setPhase("idle");
    void loadRequests();
    if (result.state !== "done") {
      setMessage({ tone: "error", text: `Nothing was re-checked: ${result.message}` });
      return;
    }
    const shown = result.value.attempts[name];
    setMessage(recheckOutcome(shown.state === "complete" ? shown.revalidation : null));
    if (view) await reread();
  };

  return (
    <div className="triage" aria-labelledby="triage-title">
      <div className="triage-bar">
        <h3 id="triage-title">Headline triage</h3>
        <span className="triage-count">{selected.length} of {MAX_SELECTION} selected</span>
        <fieldset className="triage-mode-choice" disabled={working}>
          <legend>Response</legend>
          <label><input type="radio" name="triage-mode" value="simulated" checked={mode === "simulated"}
            onChange={() => setMode("simulated")} /> Local simulation</label>
          <label><input type="radio" name="triage-mode" value="paid" checked={mode === "paid"} disabled={!paidEnabled}
            onChange={() => setMode("paid")} /> Paid</label>
        </fieldset>
        <button className="button triage-preview" type="button" disabled={working || selected.length === 0}
          onClick={preview}>{phase === "previewing" ? "Resolving saved results…" : "Preview triage"}</button>
        <button className="button button-quiet triage-clear" type="button" disabled={selected.length === 0}
          onClick={onClear}>Clear selection</button>
      </div>
      <p className="triage-note">
        Select entries below to see what each reports, in a few categories with a short summary (about 25 words), and
        which may describe the same event. Saved results are reused and never requested again; a preview plans one
        request for the missing work only, or none. Its groups are suggestions about the entries it compared, never a
        deduplication of the inbox, and every entry stays listed with its official release. Nothing is sent until you
        approve it, and a feed refresh never triages anything.
        {!paidEnabled && requests.state === "ready" && <> {requests.data.modes.paid.detail}</>}
      </p>
      {message && (
        <div className={`triage-message ${message.tone === "done" ? "is-done" : "is-error"}`}
          role={message.tone === "done" ? "status" : "alert"}>
          <p>{message.text}</p>
          {message.reread && <button className="button triage-reread" type="button" disabled={working}
            onClick={() => void reread()}>Read the selection again</button>}
        </div>
      )}
      {view && (
        <TriagePanel view={view} current={current} selected={selected} mode={mode} reprocess={chosen} phase={phase}
          busy={busy} onApprove={approve} onAnalyze={onAnalyze} onClose={() => setView(null)}
          onReprocess={(ids, on) => setReprocess((now) => on ? [...new Set([...now, ...ids])] : now.filter((id) => !ids.includes(id)))} />
      )}
      <SavedRequests requests={requests} working={working} onRecheck={recheck} onShow={(row) => {
        const held = (row.item_ids ?? []).filter((id) => current.some((item) => item.id === id));
        onSelect(held.slice(0, MAX_SELECTION));
        setMessage({ tone: "done", text: `Selected ${held.length} of the ${row.item_ids?.length ?? 0} entries of request ` +
          `${row.triage_id} that the inbox still holds. Preview triage to see their saved results; nothing is sent by that.` });
      }} />
    </div>
  );
}

function TriagePanel({ view, current, selected, mode, reprocess, phase, busy, onApprove, onAnalyze, onClose,
                       onReprocess }: {
  view: SelectionView;
  current: InboxItem[];
  selected: string[];
  mode: Mode;
  reprocess: string[];
  phase: Phase;
  busy: boolean;
  onApprove: () => void;
  onAnalyze: (item: InboxItem) => void;
  onClose: () => void;
  onReprocess: (ids: string[], on: boolean) => void;
}) {
  const [confirmed, setConfirmed] = useState(false);
  const plan = view.plan;
  useEffect(() => setConfirmed(false), [plan.triage_id, view.mode]);
  const working = phase !== "idle";
  const ids = view.items.map((row) => row.input.id);
  const otherSelection = !sameEntries(ids, selected);
  const stale = view.mode !== mode || !sameEntries(plan.reprocess, reprocess);
  const counts = { reuse: plan.reused.length, process: plan.entries.length, context: plan.context.length,
                   unresolved: plan.unresolved.length, earlier: plan.earlier_version.length };
  const estimate = plan.cost_estimate;
  const usd = estimate ? `$${estimate.estimated_paid_if_output_reaches_max_usd.toFixed(4)}` : "$0";
  const attempt = plan.attempts?.[view.mode];
  const blocked = !plan.requests ? null : otherSelection ? "the entries checked in the inbox differ from this preview"
    : stale ? "the response mode or your re-request choices changed since this preview; preview again"
      : !plan.prepared ? "the request is not saved yet; preview again"
        : attempt && attempt.state === "complete" && attempt.outcome === "triaged"
          ? "this request already has an accepted result"
          : attempt && attempt.state !== "none" && !plan.entries.every((id) => plan.reprocess.includes(id))
            ? `this request was already attempted (${attemptLabel(attempt).toLowerCase()}); it is requested again only for entries you tick Request again`
            : null;

  return (
    <section className="triage-panel" data-triage={plan.triage_id ?? ""} data-mode={view.mode} aria-label="Triage preview">
      <div className="triage-panel-head">
        <p><strong>{view.items.length} {view.items.length === 1 ? "entry" : "entries"}</strong> · {view.mode === "paid"
          ? "paid results" : "local simulation"} · {view.config.model}, effort {view.config.effort}, prompt{" "}
          {view.config.prompt_version}</p>
        <button className="button button-quiet triage-close" type="button" onClick={onClose}>Close</button>
      </div>
      {otherSelection && (
        <p className="triage-warning triage-other-selection" role="note">
          This preview covers {view.items.length} {view.items.length === 1 ? "entry" : "entries"}, not the{" "}
          {selected.length} now checked in the inbox. Its results and suggestions describe its own entries only. Preview
          the current selection to plan it.
        </p>
      )}
      {stale && !otherSelection && (
        <p className="triage-warning triage-stale" role="note">Your choices changed since this preview. Preview again to
          plan with them; nothing is sent from this one.</p>
      )}
      <div className="triage-plan" data-requests={plan.requests}>
        <p className="triage-plan-counts">
          <span><strong>{counts.reuse}</strong> saved results reused</span>
          <span><strong>{counts.process}</strong> need a result</span>
          <span><strong>{counts.context}</strong> earlier entries as comparison context only</span>
          <span><strong>{counts.unresolved}</strong> unresolved</span>
          <span><strong>{counts.earlier}</strong> from an earlier version</span>
        </p>
        <p className="triage-plan-requests">
          {plan.requests === 0
            ? "Planned requests: none. Nothing will be sent; the saved results below are the answer."
            : <>Planned requests: 1, with {counts.process} {counts.process === 1 ? "entry" : "entries"} to triage and{" "}
              {plan.pairs.needed.length} {plan.pairs.needed.length === 1 ? "pair" : "pairs"} to compare. Planning estimate if
              output reached the maximum: <strong>{usd}</strong>
              {estimate && estimate.comparison_context_tokens_assumed > 0 && <>; about{" "}
                {estimate.comparison_context_tokens_assumed.toLocaleString()} of its input tokens are comparison context, billed
                like the rest</>}.</>}
        </p>
        <p className="triage-plan-pairs">{plan.pairs.rule} {plan.pairs.compared} of {plan.pairs.candidates} candidate
          pairs here were already compared with these settings{plan.pairs.earlier.length > 0 && <>; {plan.pairs.earlier.length}
          only with an earlier version, which is not repeated unless you regenerate one of its entries</>}.</p>
        {plan.pairs.unresolved.length > 0 && (
          <label className="triage-reprocess triage-reprocess-pairs">
            <input type="checkbox" checked={plan.pairs.unresolved.flat().some((id) => reprocess.includes(id))}
              onChange={(event) => onReprocess([...new Set(plan.pairs.unresolved.flat())], event.target.checked)} />
            <span>{plan.pairs.unresolved.length} {plan.pairs.unresolved.length === 1 ? "comparison was" : "comparisons were"}{" "}
              attempted without an accepted result and are not queued again. Request again (then preview again).</span>
          </label>
        )}
      </div>

      {plan.requests === 1 && plan.request && estimate && (
        <>
          <div className="triage-facts">
            <div><span>Model</span><strong>{view.config.model}</strong></div>
            <div><span>Effort</span><strong>{view.config.effort}</strong></div>
            <div><span>Thinking</span><strong>{view.config.thinking.type}</strong></div>
            <div><span>Maximum output</span><strong>{(plan.max_tokens ?? 0).toLocaleString()} tokens</strong></div>
            <div><span>Simulated cost</span><strong>$0.00</strong></div>
          </div>
          <details className="triage-inputs">
            <summary>Sent: {counts.process} {counts.process === 1 ? "entry" : "entries"} in full and {counts.context}{" "}
              earlier {counts.context === 1 ? "entry" : "entries"} as comparison context (title, link and feed date only)</summary>
            <ol>
              {view.items.filter((row) => row.in_request).map((row) => (
                <InputRow key={row.input.id} item={row.input} context={row.in_request === "context"} />
              ))}
            </ol>
          </details>
          <details className="triage-request">
            <summary>Exact {plan.prepared ? "saved " : ""}request · {plan.request_bytes.toLocaleString()} bytes · SHA-256{" "}
              <code>{String(plan.request_sha256).slice(0, 12)}…</code></summary>
            <p className="triage-request-hash">SHA-256 <code>{plan.request_sha256}</code> · request <code>{plan.triage_id}</code></p>
            <pre>{JSON.stringify(plan.request, null, 2)}</pre>
          </details>
          <div className="triage-estimate">
            <p>Planning estimate for this one paid request if output reached the maximum: <strong>{usd}</strong>.{" "}
              {estimate.caveat}</p>
            <ul>{estimate.assumptions.map((assumption) => <li key={assumption}>{assumption}</li>)}</ul>
            <p>Prices read on {estimate.prices.read_on} from <a href={estimate.prices.source} target="_blank"
              rel="noreferrer">Anthropic's pricing page</a>.</p>
          </div>
          {plan.attempts && (
            <div className="triage-attempts">
              {(["simulated", "paid"] as const).map((name) => {
                const state = plan.attempts![name];
                return (
                  <p key={name} className={`triage-attempt is-${state.state}`} data-mode={name}>
                    <span>{name === "simulated" ? "Local simulated response" : "Paid request"}</span>{" "}
                    <strong>{attemptLabel(state)}</strong>
                    {state.state === "complete" && state.message && <> · {state.message}</>}
                    {(state.state === "incomplete" || state.state === "invalid") && <> · {state.detail}</>}
                  </p>
                );
              })}
            </div>
          )}
          {blocked ? (
            <p className="triage-blocked">No response can be approved here: {blocked}.</p>
          ) : (
            <>
              <label className={`triage-confirm${view.mode === "paid" ? " is-paid" : ""}`}>
                <input type="checkbox" checked={confirmed} disabled={working}
                  onChange={(event) => setConfirmed(event.target.checked)} />
                <span>{view.mode === "simulated"
                  ? <>I approve one local simulated response for request <code>{String(plan.request_sha256).slice(0, 12)}…</code>.
                    No provider is contacted and nothing is billed; it is requested once, with no retry.</>
                  : <>I approve one paid request to Anthropic ({view.config.model}) for request{" "}
                    <code>{String(plan.request_sha256).slice(0, 12)}…</code>, estimated at up to {usd}. This is a planning
                    estimate, not a billing ceiling. It is sent once, with no retry; if no reply arrives, it may still be
                    billed.</>}{plan.reprocess.length > 0 && <> It re-requests {plan.reprocess.length} {plan.reprocess.length === 1
                      ? "entry" : "entries"} you ticked.</>}</span>
              </label>
              <div className="triage-actions">
                <button className={`button triage-approve${view.mode === "paid" ? " button-paid" : ""}`} type="button"
                  disabled={!confirmed || working} onClick={onApprove}>
                  {phase === "sending" ? (view.mode === "paid" ? "Waiting for the paid response…" : "Recording simulated response…")
                    : view.mode === "paid" ? "Send one paid request" : "Approve simulated response"}
                </button>
              </div>
            </>
          )}
        </>
      )}

      <TriageResults view={view} current={current} busy={busy} reprocess={reprocess} onAnalyze={onAnalyze}
        onReprocess={onReprocess} />
    </section>
  );
}

function InputRow({ item, context }: { item: TriageInput; context: boolean }) {
  const stamp = item.feed_timestamp;
  return (
    <li className={`triage-input${context ? " is-context" : ""}`} data-entry={item.id}>
      <p className="triage-input-title">{context && <em>Comparison context · </em>}{item.title}
        {item.title_truncated && <em> (title shortened by the inbox)</em>}</p>
      <p className="triage-input-meta">
        {item.publisher} · feed category {item.feed_category} · {stamp.raw
          ? <>feed timestamp ({stamp.element}) <code>{stamp.raw}</code>, feed metadata, not a verified publication time</>
          : "no feed timestamp"} · {officialLink(item.link)
          ? <a href={item.link} target="_blank" rel="noreferrer">Official release</a> : "no usable link"}
      </p>
      {!context && <p className="triage-input-excerpt">{item.excerpt
        ? <>Feed excerpt{item.excerpt_truncated ? " (shortened by the inbox)" : ""}: {item.excerpt}</>
        : "No feed excerpt beyond the title."}</p>}
    </li>
  );
}

function TriageResults({ view, current, busy, reprocess, onAnalyze, onReprocess }: {
  view: SelectionView;
  current: InboxItem[];
  busy: boolean;
  reprocess: string[];
  onAnalyze: (item: InboxItem) => void;
  onReprocess: (ids: string[], on: boolean) => void;
}) {
  const [layout, setLayout] = useState<"grouped" | "all">("grouped");
  const sections = groupedSections(view);
  const groups = sections.filter((section) => section.kind === "group").length;
  const withResults = view.items.filter((row) => row.result).length;
  const row = (entry: TriageRow) => (
    <ResultRow key={entry.input.id} row={entry} mode={view.mode} current={current} busy={busy}
      ticked={reprocess.includes(entry.input.id)} onAnalyze={onAnalyze} onReprocess={onReprocess} />
  );
  return (
    <section className="triage-results" aria-label="Triage results">
      <div className="triage-results-head">
        <h4>{view.mode === "paid" ? `${view.config.model} results` : "Simulated results"}</h4>
        <fieldset className="triage-layout">
          <legend>Show</legend>
          <label><input type="radio" name="triage-layout" checked={layout === "grouped"}
            onChange={() => setLayout("grouped")} /> Grouped suggestions</label>
          <label><input type="radio" name="triage-layout" checked={layout === "all"}
            onChange={() => setLayout("all")} /> Every entry, ungrouped</label>
        </fieldset>
      </div>
      <p className={`triage-provenance is-${view.mode}`}>
        {view.mode === "paid"
          ? <>Results from paid {view.config.model} responses, each labelled with the request it came from. </>
          : <>Simulated results come from this server's local simulation: no model read these entries, and nothing was
            sent to a provider. </>}
        Categories, summaries and groups are suggestions to check against each official release, not findings.{" "}
        {withResults} of {view.items.length} entries have a saved result ·{" "}
        {groups === 0 ? "no groups suggested" : `${groups} possible ${groups === 1 ? "group" : "groups"}`}.
      </p>
      {view.unreadable_requests.length > 0 && (
        <p className="triage-warning" role="note">{view.unreadable_requests.length} saved{" "}
          {view.unreadable_requests.length === 1 ? "request does" : "requests do"} not verify and{" "}
          {view.unreadable_requests.length === 1 ? "is" : "are"} left as recorded; nothing from{" "}
          {view.unreadable_requests.length === 1 ? "it" : "them"} is used.</p>
      )}
      {layout === "grouped" ? (
        <ol className="triage-list">
          {sections.map((section) => section.kind === "entry" ? row(section.row) : (
            <li key={section.relation.item_ids.join(" ")} className="triage-group-item">
              <details className="triage-group">
                <summary><span className="triage-group-label">{section.relation.label}</span> · {section.rows.length} entries
                  {" "}<span className="triage-group-reason">{section.relation.reason}</span></summary>
                <p className="triage-group-dates">{feedDateNote(section.relation)} A suggestion from request{" "}
                  <code>{section.relation.provenance.triage_id}</code>, not an identity: each entry stays separate and keeps
                  its own source.{scopeNote(section.relation)}</p>
                <ol className="triage-list">{section.rows.map((member) => row(member))}</ol>
              </details>
            </li>
          ))}
        </ol>
      ) : (
        <ol className="triage-list">{triageRows(view).map((entry) => row(entry))}</ol>
      )}
    </section>
  );
}

function ResultRow({ row, mode, current, busy, ticked, onAnalyze, onReprocess }: {
  row: TriageRow;
  mode: Mode;
  current: InboxItem[];
  busy: boolean;
  ticked: boolean;
  onAnalyze: (item: InboxItem) => void;
  onReprocess: (ids: string[], on: boolean) => void;
}) {
  const { input, result, provenance } = row;
  const now = currentEntry(input, current);
  const pending = row.status === "process" ? (row.reprocess ? "Requested again: included in the planned request."
    : "Pending: no saved result yet; included in the planned request.") : null;
  return (
    <li className={`triage-row is-${row.status}`} data-entry={input.id} data-status={row.status}>
      <p className="triage-row-head">
        <span className={`triage-status is-${row.status}`}>{statusLabel(row)}</span>
        {row.location === "retained" && <span className="triage-location">Retained history</span>}
        {result && <span className="triage-category">{result.category}</span>}
        {result?.event_type && <span className="triage-event-type">{result.event_type}</span>}
      </p>
      <p className="triage-row-title">{input.title}</p>
      {result ? <p className="triage-summary">{result.summary}</p> : <p className="triage-pending">{pending ??
        "No saved result."}</p>}
      {result && result.figures_not_in_inputs.length > 0 && (
        <p className="triage-figures">States {result.figures_not_in_inputs.join(", ")}, which this entry's title and excerpt
          do not; check it against the official release.</p>
      )}
      {provenance && (
        <p className="triage-row-provenance">
          {provenance.mode === "simulated" ? "Simulated" : `Triaged by ${provenance.config.model}`} {utcStamp(provenance.received_at)} ·
          prompt {provenance.config.prompt_version}{provenance.current_config ? "" : ", an earlier version"} · request{" "}
          <code>{provenance.triage_id}</code>{recheckLabel(provenance)}
        </p>
      )}
      {row.status === "unresolved" && row.claim && (
        <p className="triage-claim">Earlier {mode} attempt: {row.claim.state.replace(/_/g, " ")}
          {row.claim.detail ? ` · ${row.claim.detail}` : ""}. It is not requested again on its own.</p>
      )}
      {(row.status === "unresolved" || row.status === "earlier_version" || (row.status === "process" && row.reprocess)) && (
        <label className="triage-reprocess">
          <input type="checkbox" checked={ticked} onChange={(event) => onReprocess([input.id], event.target.checked)} />
          <span>{row.status === "earlier_version" ? "Regenerate with the current version" : "Request again"} (then preview
            again)</span>
        </label>
      )}
      {row.other_versions_with_results > 0 && (
        <p className="triage-versions">{row.other_versions_with_results} earlier{" "}
          {row.other_versions_with_results === 1 ? "version" : "versions"} of this entry, with different text, already{" "}
          {row.other_versions_with_results === 1 ? "has" : "have"} a saved result; this version does not reuse it.</p>
      )}
      {row.notes.map((note) => (
        <p key={note.relation.provenance.triage_id + note.relation.relation + note.relation.item_ids.join(" ")}
          className={`triage-note-row is-${note.relation.relation}`}>
          <span>{note.relation.label}</span>{note.unmerged ? " (another response's suggestion; not merged)" : ""} with{" "}
          {note.others.map((other) => `“${other.title}” (${other.feed_timestamp.utc
            ? `feed date ${other.feed_timestamp.utc.slice(0, 10)}` : "no feed timestamp"})`).join(", ")}: {note.relation.reason}
          {scopeNote(note.relation)}
        </p>
      ))}
      <p className="triage-row-meta">
        {input.publisher} · feed category {input.feed_category} · {input.feed_timestamp.raw
          ? <>feed timestamp <code>{input.feed_timestamp.raw}</code> (feed metadata)</> : "no feed timestamp"} ·{" "}
        {officialLink(input.link) ? <a href={input.link} target="_blank" rel="noreferrer">Official release</a>
          : "no usable link"}
      </p>
      {!now && <p className="triage-row-gone">No longer held in the inbox or its archive, so it cannot be analyzed from here.</p>}
      <button type="button" className="button triage-analyze" disabled={busy || !now}
        onClick={() => now && onAnalyze(now)}>Analyze this event</button>
    </li>
  );
}

function SavedRequests({ requests, working, onShow, onRecheck }: {
  requests: Loaded<RequestsListing>;
  working: boolean;
  onShow: (row: RequestsListing["requests"][number]) => void;
  onRecheck: (row: RequestsListing["requests"][number], mode: Mode) => void;
}) {
  if (requests.state === "loading") return null;
  if (requests.state !== "ready") return <p className="triage-saved-error" role="alert">Saved requests could not be read: {requests.message}</p>;
  const rows = requests.data.requests;
  if (rows.length === 0) return null;
  const failed = rows.filter((row) => row.attempts && Object.values(row.attempts).some((attempt) =>
    attempt.state === "incomplete" || attempt.state === "invalid" || (attempt.state === "complete" && attempt.outcome !== "triaged"))).length;
  return (
    <details className="triage-saved">
      <summary>Saved requests ({rows.length}{failed ? `, ${failed} with a failed or uncertain attempt` : ""})</summary>
      <ul>
        {rows.map((row) => (
          <li key={row.triage_id} data-triage={row.triage_id} className={row.state === "ready" ? "" : "is-unreadable"}>
            {row.state === "ready" ? (
              <p>
                <strong>{row.entry_count} to triage, {row.context_count} as context</strong> · prepared {utcStamp(row.prepared_at)}
                {row.current_config ? "" : " · an earlier version"} · simulated: {listedLabel(row.attempts?.simulated)}
                {" "}· paid: {listedLabel(row.attempts?.paid)}
                <span className="triage-saved-titles">{row.titles?.join(" · ")}</span>
                {row.attempts && Object.entries(row.attempts).filter(([, attempt]) => attempt.detail &&
                  attempt.state !== "none" && !(attempt.state === "complete" && attempt.outcome === "triaged"))
                  .map(([name, attempt]) => <span key={name} className="triage-saved-detail">{name}: {attempt.detail}</span>)}
                {row.attempts && Object.entries(row.attempts).filter(([, attempt]) => attempt.revalidation)
                  .map(([name, attempt]) => (
                    <span key={`${name}-recheck`} className="triage-saved-recheck" data-mode={name}>
                      {name}: local re-check under {attempt.revalidation!.validation_policy}:{" "}
                      {attempt.revalidation!.outcome === "accepted" ? "accepted, with no request sent; the original "
                        + "record still says not accepted" : attempt.revalidation!.outcome === "not_accepted"
                        ? `still not accepted (${attempt.revalidation!.message})` : "does not verify"}
                    </span>))}
              </p>
            ) : <p><code>{row.triage_id}</code> · {row.detail}</p>}
            {row.state === "ready" && row.attempts && (Object.keys(row.attempts) as Mode[])
              .filter((name) => row.attempts![name].revalidatable).map((name) => (
                <button key={name} className="button button-quiet triage-recheck" type="button" disabled={working}
                  data-mode={name} title="Parses the saved response again under the current rules. Nothing is sent."
                  onClick={() => onRecheck(row, name)}>Re-check the {name} response locally</button>))}
            {row.state === "ready" && (
              <button className="button button-quiet triage-open" type="button" disabled={working}
                onClick={() => onShow(row)}>Select its entries</button>
            )}
          </li>
        ))}
      </ul>
    </details>
  );
}
