import { useEffect, useRef, useState, type CSSProperties, type FormEvent } from "react";
import {
  captureEvent, dispatchMock, dispatchPaid, fetchAttemptState, fetchCaptures, publishRecorded, reopenCapture,
  type DispatchResult, type IntakePreview, type SavedCapture,
} from "../api";
import {
  edited, entryLink, kindNote, linkLabel, prefilledFields, suggestedFields, utcStamp, type InboxItem,
} from "../inbox";
import {
  UTC_OFFSETS, intakePayload, mayApprove, offsetLabel, outcomeText, requestPublishedAt, type AttemptState,
  type IntakeFields, type MockOutcome,
} from "../intake";
import { researchHref } from "../eventOverview";
import { Link } from "../router";
import "../intake.css";

const EMPTY: IntakeFields = {
  headline: "", sourceUrl: "", publishedDate: "", publishedTime: "", publishedOffset: "", sourceText: "",
};

type Phase = "idle" | "capturing" | "opening" | "ready" | "dispatching" | "checking" | "publishing";
type Source = "mock" | "paid";
/** Which analysis the operator chose for the saved event: this saved hypothesis request, or a separate research one. */
type AnalysisMode = "hypothesis" | "research";

/** The recorded state as the page knows it: null before any dispatch, "unreadable" when the read failed. */
type Known = AttemptState | "unreadable" | null;

type SavedList = { state: "loading" } | { state: "ready"; captures: SavedCapture[] } | { state: "error"; message: string };

const ATTEMPT_TEXT: Record<AttemptState["state"], string> = {
  none: "No attempt is recorded for this capture, so nothing was sent or run. You can approve it.",
  incomplete: "This attempt was interrupted after it was reserved. What was written is kept as recorded and blocks " +
    "another attempt for this capture. Start over to capture the event again.",
  awaiting_publication: "The response is recorded but not yet published for review. Publishing uses the " +
    "recorded request and response; nothing is sent or generated again.",
  ready: "The saved records show the result is ready for review.",
  invalid: "The recorded attempt does not verify, so it is not shown for review. It is reported, never repaired.",
};

/**
 * ``prefill`` is an Event Inbox entry the operator chose (a new ``nonce`` per choice). It fills only the headline and
 * official link; a feed timestamp is offered as a suggestion to be checked, and the published text stays empty.
 * Unsaved edits or a loaded preview are replaced only after the operator confirms; nothing is replaced while an
 * action is in flight. ``onBusyChange`` tells the inbox when choosing another entry must wait.
 */
export function EventIntake({ onPrepared, style, prefill = null, onBusyChange }: {
  onPrepared: (draftId: string) => void;
  style?: CSSProperties;
  prefill?: { nonce: number; item: InboxItem } | null;
  onBusyChange?: (busy: boolean) => void;
}) {
  const [fields, setFields] = useState(EMPTY);
  /** What was last filled in for the operator; the form has unsaved edits when it differs. */
  const [baseline, setBaseline] = useState(EMPTY);
  /** The inbox entry the form was filled from, if any. */
  const [origin, setOrigin] = useState<InboxItem | null>(null);
  /** An entry chosen while there was work to lose: it replaces the form only once the operator confirms. */
  const [pending, setPending] = useState<InboxItem | null>(null);
  const [suggestionUsed, setSuggestionUsed] = useState(false);
  const [timeVerified, setTimeVerified] = useState(false);
  const sectionRef = useRef<HTMLElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const appliedNonce = useRef(0);
  const [preview, setPreview] = useState<IntakePreview | null>(null);
  const [source, setSource] = useState<Source>("mock");
  const [mode, setMode] = useState<AnalysisMode>("hypothesis");
  const [outcome, setOutcome] = useState<MockOutcome>("draft");
  const [confirmed, setConfirmed] = useState(false);
  const [paidConfirmed, setPaidConfirmed] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [attempt, setAttempt] = useState<Known>(null);
  const [lostReply, setLostReply] = useState(false);
  const [message, setMessage] = useState<{ text: string; tone: "done" | "error" } | null>(null);
  const [saved, setSaved] = useState<SavedList>({ state: "loading" });
  /** Why the preview shown could not be refreshed; while set, nothing can be approved from it. */
  const [stale, setStale] = useState<string | null>(null);
  const busy = useRef(false);  // One action at a time, even for two clicks delivered in one task.
  const selection = useRef(0);  // The newest capture, open, refresh or start-over; an older reply is dropped.
  const listing = useRef(0);

  const loadSaved = async () => {
    const token = ++listing.current;
    setSaved({ state: "loading" });
    const read = await fetchCaptures();
    if (token === listing.current) setSaved(read.state === "ready" ? { state: "ready", captures: read.data } : read);
  };
  useEffect(() => { void loadSaved(); }, []);

  const clearApprovals = () => {
    setMode("hypothesis");
    setSource("mock");
    setOutcome("draft");
    setConfirmed(false);
    setPaidConfirmed(false);
    setLostReply(false);
  };

  /**
   * Open a saved capture, or refresh the one shown, with reads only: its verified saved request, this server's
   * current sending modes and what its attempt recorded. Approvals are cleared and the local mock is selected;
   * nothing can be approved until both reads verify. A refresh that fails keeps the old preview, marked stale.
   */
  const reopen = async (captureId: string, shownHash?: string) => {
    if (busy.current) return;
    const token = ++selection.current;
    clearApprovals();
    setMessage(null);
    setPhase("opening");
    const opened = await reopenCapture(captureId, shownHash);
    if (token !== selection.current) return;
    if (opened.state === "error") {
      if (shownHash === undefined) {
        setPhase("idle");
        setMessage({ text: `The saved event could not be opened: ${opened.message}`, tone: "error" });
      } else {
        setStale(opened.message);
        setPhase("ready");
      }
      return;
    }
    clearApprovals();
    setPreview(opened.preview);
    setAttempt(opened.attempt);
    setStale(null);
    setPhase("ready");
    if (opened.problem) {
      setMessage({ text: `What this capture recorded could not be read: ${opened.problem}`, tone: "error" });
    }
  };

  const change = (key: keyof IntakeFields, value: string) => {
    setFields((current) => ({ ...current, [key]: value }));
    setMessage(null);
  };

  /**
   * Start the form from an inbox entry. Any older capture or open reply is dropped, approvals are cleared and a shown
   * preview is closed; its saved capture and records stay, and it can be reopened from Saved events.
   */
  const accept = (item: InboxItem) => {
    selection.current++;
    clearApprovals();
    const next = prefilledFields(item, EMPTY);
    setFields(next);
    setBaseline(next);
    setOrigin(item);
    setPending(null);
    setSuggestionUsed(false);
    setTimeVerified(false);
    setPreview(null);
    setAttempt(null);
    setStale(null);
    setPhase("idle");
    setMessage(null);
    void loadSaved();  // A capture just left behind is listed, ready to reopen.
    sectionRef.current?.scrollIntoView({ block: "start" });
    window.setTimeout(() => textRef.current?.focus({ preventScroll: true }), 0);
  };

  const inFlight = phase === "capturing" || phase === "opening" || phase === "dispatching" || phase === "checking" ||
    phase === "publishing";
  useEffect(() => { onBusyChange?.(inFlight); }, [inFlight]);

  useEffect(() => {
    if (!prefill || prefill.nonce === appliedNonce.current) return;
    appliedNonce.current = prefill.nonce;
    if (busy.current || inFlight) {
      setMessage({ text: "Finish the current action before choosing another event; the form was not changed.",
                   tone: "error" });
    } else if (preview || edited(fields, baseline)) {
      setPending(prefill.item);
    } else {
      accept(prefill.item);
    }
  }, [prefill]);

  const applySuggestion = () => {
    const suggested = origin ? suggestedFields(origin.feed_timestamp) : null;
    if (!suggested) return;
    setFields((current) => ({ ...current, ...suggested }));
    setSuggestionUsed(true);
    setTimeVerified(false);
    setMessage(null);
  };

  const capture = async (event: FormEvent) => {
    event.preventDefault();
    if (origin && suggestionUsed && !timeVerified) {
      setMessage({ text: "Confirm that you checked the date, time and offset against the release itself before " +
                         "previewing: the feed timestamp is only a suggestion.", tone: "error" });
      return;
    }
    const planned = intakePayload(fields);
    if (!planned.payload) {
      setMessage({ text: planned.problem ?? "The event is incomplete.", tone: "error" });
      return;
    }
    const token = ++selection.current;
    setPhase("capturing");
    setMessage(null);
    // The entry version that filled the form is named so the server can record it beside the capture.
    const result = await captureEvent(origin ? { ...planned.payload, origin: { item_id: origin.id,
      content_sha256: origin.content_sha256 } } : planned.payload);
    if (token !== selection.current) {  // Another saved event was opened meanwhile; this one is listed instead.
      void loadSaved();
      return;
    }
    if (result.state !== "saved") {
      setPhase("idle");
      setMessage({ text: result.message, tone: "error" });
      return;
    }
    setPreview(result.preview);
    if (result.preview.origin && !result.preview.origin.recorded) {
      setMessage({ text: result.preview.origin.problem ?? "The Inbox origin was not recorded.", tone: "error" });
    }
    setSource("mock");
    setConfirmed(false);
    setPaidConfirmed(false);
    setAttempt(null);
    setLostReply(false);
    setStale(null);
    setPhase("ready");
  };

  // Learns what was recorded by reading it; nothing is ever sent again from here.
  const settle = async (captureId: string) => {
    const token = selection.current;
    setPhase("checking");
    const read = await fetchAttemptState(captureId);
    if (token !== selection.current) return;
    setPhase("ready");
    if (read.state !== "ready") {
      setAttempt("unreadable");
      setMessage((current) => ({ text: `${current?.text ?? ""} What was recorded could not be read: ${read.message}`,
                                 tone: "error" }));
      return;
    }
    setAttempt(read.data);
    if (read.data.state === "ready" && read.data.draft_id) onPrepared(read.data.draft_id);
  };

  /** Shared by the mock dispatch, the paid send and recovery: open a confirmed result, or read what was recorded. */
  const finish = async (result: DispatchResult, done: string) => {
    if (result.state === "saved") {
      const { draft_id: draftId, outcome: shown, recorded_outcome: recorded, mode } = result.result;
      setPhase("ready");
      setAttempt({ flow_version: result.result.flow_version, capture_id: result.result.capture_id, state: "ready",
                   files: [], detail: ATTEMPT_TEXT.ready, draft_id: draftId, outcome: shown,
                   recorded_outcome: recorded, mode, sent: mode === "paid", provider_called: false });
      setMessage({ text: `${done} ${outcomeText(recorded, mode)} Opening it for human review.`, tone: "done" });
      onPrepared(draftId);
    } else {
      setLostReply(result.state === "unconfirmed");
      setMessage({ text: result.message, tone: "error" });
      await settle(preview!.capture_id);
    }
  };

  const runMock = async () => {
    if (!preview || !confirmed || busy.current || !approvable || !timeConfirmed(preview)) return;
    busy.current = true;
    setPhase("dispatching");
    setMessage(null);
    setLostReply(false);
    await finish(await dispatchMock(preview.capture_id, preview.request_sha256, outcome), "Mock response recorded.");
    busy.current = false;
  };

  const runPaid = async () => {
    if (!preview || !paidConfirmed || !preview.modes.paid.enabled || busy.current || !approvable ||
        !timeConfirmed(preview)) return;
    busy.current = true;
    setPhase("dispatching");
    setMessage(null);
    setLostReply(false);
    const estimate = preview.cost_estimate.estimated_real_run_if_output_reaches_max_usd;
    await finish(await dispatchPaid(preview.capture_id, preview.request_sha256, estimate), "Paid request recorded.");
    busy.current = false;
  };

  const publish = async () => {
    if (!preview || busy.current || attempt === null || attempt === "unreadable" ||
        attempt.state !== "awaiting_publication") return;
    busy.current = true;
    setPhase("publishing");
    await finish(await publishRecorded(preview.capture_id, preview.request_sha256),
                 "The recorded response was published for review without sending anything.");
    busy.current = false;
  };

  const check = async () => {
    if (!preview || busy.current) return;
    busy.current = true;
    await settle(preview.capture_id);
    busy.current = false;
  };

  const reset = () => {
    selection.current++;
    setFields(EMPTY);
    setBaseline(EMPTY);
    setOrigin(null);
    setPending(null);
    setSuggestionUsed(false);
    setTimeVerified(false);
    setPreview(null);
    setSource("mock");
    setConfirmed(false);
    setPaidConfirmed(false);
    setOutcome("draft");
    setAttempt(null);
    setLostReply(false);
    setStale(null);
    setPhase("idle");
    setMessage(null);
    void loadSaved();
  };

  const working = phase === "dispatching" || phase === "checking" || phase === "publishing" || phase === "opening";
  // Approvable only from a verified, current preview whose recorded state allows an attempt.
  const approvable = mayApprove(attempt) && stale === null && phase !== "opening";
  return (
    <section ref={sectionRef} className="card tracker-section event-intake reveal" style={style}
      aria-labelledby="event-intake-title">
      <div className="tracker-section-head">
        <h2 id="event-intake-title">Analyze an event</h2>
        <span className="tracker-count">Local mock by default · $0</span>
      </div>
      <p className="card-note">
        Capture one published event, inspect the exact Sonnet request, then approve one response: a local mock ($0,
        the default) or, only where this server enables it, one paid Claude request. This does not reopen research
        intake, freeze a hypothesis or evaluate anything.
      </p>

      {pending && (
        <div className="intake-replace" role="alertdialog" aria-labelledby="intake-replace-text">
          <p id="intake-replace-text">
            {preview
              ? `A saved preview is open. Leave it and start the form from “${pending.title}”? Its saved capture and ` +
                "anything recorded for it are kept, and it can be reopened from Saved events; its approvals are cleared."
              : `The form has unsaved edits. Replace them with “${pending.title}”?`}
          </p>
          <div>
            <button type="button" className="button intake-replace-accept" disabled={inFlight}
              onClick={() => accept(pending)}>Replace with this event</button>
            <button type="button" className="button button-quiet intake-replace-keep"
              onClick={() => setPending(null)}>Keep my current work</button>
          </div>
        </div>
      )}

      {!preview ? (
        <>
          <form className="intake-form" onSubmit={capture}>
            {origin && <InboxOrigin item={origin} suggestionUsed={suggestionUsed} timeVerified={timeVerified}
              onUseSuggestion={applySuggestion} onVerified={setTimeVerified} />}
            <label><span>Headline</span><input required value={fields.headline}
              onChange={(event) => change("headline", event.target.value)} /></label>
            <label><span>Source URL</span><input required type="url" placeholder="https://…" value={fields.sourceUrl}
              onChange={(event) => change("sourceUrl", event.target.value)} /></label>
            <fieldset className="intake-time">
              <legend>Published at</legend>
              <label><span>Date</span><input required type="date" value={fields.publishedDate}
                onChange={(event) => change("publishedDate", event.target.value)} /></label>
              <label><span>Time</span><input required type="time" step={1} value={fields.publishedTime}
                onChange={(event) => change("publishedTime", event.target.value)} /></label>
              <label><span>UTC offset</span><select required value={fields.publishedOffset}
                onChange={(event) => change("publishedOffset", event.target.value)}>
                <option value="">Choose the offset</option>
                {UTC_OFFSETS.map((offset) => <option key={offset} value={offset}>{offsetLabel(offset)}</option>)}
              </select></label>
              <p className="intake-time-note">
                Enter the time as the publication states it, with its UTC offset (for example UTC−04:00 for US Eastern
                daylight time, or UTC+00:00 for UTC). This computer's time zone is never used.
              </p>
            </fieldset>
            <label className="intake-source"><span>Published text</span><textarea ref={textRef} required rows={10}
              value={fields.sourceText} onChange={(event) => change("sourceText", event.target.value)} /></label>
            <div className="intake-actions">
              <button className="button" type="submit" disabled={phase === "capturing"}>
                {phase === "capturing" ? "Saving exact request…" : "Preview exact request"}
              </button>
              <span>Nothing is sent by this step.</span>
            </div>
          </form>
          <SavedCaptures saved={saved} opening={phase === "opening"} onOpen={(captureId) => reopen(captureId)}
            onReload={() => void loadSaved()} />
        </>
      ) : (
        <div className="intake-preview">
          <div className="intake-refresh">
            <button className="button intake-refresh-button" type="button" disabled={working}
              onClick={() => reopen(preview.capture_id, preview.request_sha256)}>
              {phase === "opening" ? "Refreshing…" : "Refresh saved preview"}
            </button>
            <span>Reads the saved request, this server's sending modes and what was recorded again. Nothing is
              captured or sent, and approvals are cleared.</span>
          </div>
          {stale && (
            <p className="intake-stale" role="alert">
              This preview could not be refreshed and may be out of date, so nothing can be approved from it: {stale}
            </p>
          )}
          <fieldset className="intake-mode-choice" disabled={working}>
            <legend>Analysis mode</legend>
            <label><input type="radio" name="analysis-mode" checked={mode === "hypothesis"}
              onChange={() => setMode("hypothesis")} /> Market-hypothesis draft: this saved request, which asks for
              directional legs on the offered Treasury yields, or a decline</label>
            <label><input type="radio" name="analysis-mode" value="research" checked={mode === "research"}
              onChange={() => setMode("research")} /> Evidence-first research analysis: a separate request prepared from
              this saved event; what the source establishes, quoted, with any interpretation labelled apart</label>
          </fieldset>
          {mode === "research" ? (
            <div className="intake-mode-research" data-mode="research">
              <p>The research analysis has its own request, result and review, prepared and approved on its own page from
                this saved event (capture <code>{preview.capture_id}</code>). This saved request stays unchanged, and
                nothing is prepared or sent until you act there.</p>
              <Link className="button intake-open-research" to={researchHref(preview.capture_id)}>
                Open the research analysis</Link>
            </div>
          ) : (<>
          <div className="intake-preview-head">
            <div><span>Model</span><strong>{preview.model}</strong></div>
            <div><span>Effort</span><strong>{preview.effort}</strong></div>
            <div><span>Maximum output</span><strong>{preview.max_tokens.toLocaleString()} tokens</strong></div>
            <div><span>Mock cost</span><strong>$0.00</strong></div>
          </div>
          <PublicationTimes preview={preview} />
          <p className="intake-estimate">
            Planning estimate for one paid request if output reached the maximum: <strong>
              ${preview.cost_estimate.estimated_real_run_if_output_reaches_max_usd.toFixed(4)}
            </strong>. {preview.cost_estimate.caveat}
          </p>
          <dl className="draft-facts intake-facts">
            <div><dt>Capture</dt><dd><code className="draft-wrap">{preview.capture_id}</code></dd></div>
            <div><dt>Request SHA-256</dt><dd><code className="draft-wrap">{preview.request_sha256}</code></dd></div>
            <div><dt>Stored request</dt><dd>{preview.request_bytes.toLocaleString()} bytes · {preview.prompt_version}</dd></div>
            <div><dt>Current builder</dt><dd>{preview.current_code.comparison} · {preview.current_code.detail}</dd></div>
          </dl>
          <details className="intake-request">
            <summary>Exact saved request</summary>
            <pre>{JSON.stringify(preview.request, null, 2)}</pre>
          </details>

          <fieldset className="intake-source-choice" disabled={!approvable || working}>
            <legend>Response source</legend>
            <label><input type="radio" name="response-source" value="mock" checked={source === "mock"}
              onChange={() => setSource("mock")} /> Local mock: $0, no provider contacted</label>
            <label><input type="radio" name="response-source" value="paid" checked={source === "paid"}
              disabled={!preview.modes.paid.enabled} onChange={() => setSource("paid")} /> One paid {preview.model}
              {" "}request, estimated up to ${preview.cost_estimate.estimated_real_run_if_output_reaches_max_usd.toFixed(4)}</label>
            {!preview.modes.paid.enabled && <p className="intake-source-note">{preview.modes.paid.detail}</p>}
          </fieldset>

          {source === "mock" ? (
            <>
              <fieldset className="intake-mock-choice" disabled={!approvable}>
                <legend>Mock response to exercise</legend>
                <label><input type="radio" name="mock-outcome" checked={outcome === "draft"}
                  onChange={() => setOutcome("draft")} /> Draft</label>
                <label><input type="radio" name="mock-outcome" checked={outcome === "no_draft"}
                  onChange={() => setOutcome("no_draft")} /> Refusal to draft</label>
              </fieldset>
              <label className="intake-confirm">
                <input type="checkbox" checked={confirmed} disabled={!approvable}
                  onChange={(event) => setConfirmed(event.target.checked)} />
                <span>I approve one local mock attempt using request <code>{preview.request_sha256.slice(0, 12)}…</code>.
                  No provider will be contacted and there is no automatic retry.</span>
              </label>
              <div className="intake-actions">
                <button className="button" type="button"
                  disabled={!confirmed || working || !approvable || !timeConfirmed(preview)}
                  onClick={runMock}>{phase === "dispatching" ? "Recording mock response…" : "Approve mock response"}</button>
                <button className="button button-quiet" type="button" disabled={working} onClick={reset}>
                  Start over
                </button>
              </div>
            </>
          ) : (
            <>
              <PaidDecision preview={preview} />
              <label className="intake-confirm paid-confirm">
                <input type="checkbox" checked={paidConfirmed} disabled={!approvable}
                  onChange={(event) => setPaidConfirmed(event.target.checked)} />
                <span>I approve one paid request to Anthropic for request{" "}
                  <code>{preview.request_sha256.slice(0, 12)}…</code>, estimated at up to $
                  {preview.cost_estimate.estimated_real_run_if_output_reaches_max_usd.toFixed(4)}. This is a planning
                  estimate, not a billing ceiling. It is sent once, with no retry; if no reply arrives, it may still be
                  billed.</span>
              </label>
              <div className="intake-actions paid-actions">
                <button className="button button-paid intake-send-paid" type="button"
                  disabled={!paidConfirmed || working || !approvable || !timeConfirmed(preview)} onClick={runPaid}>
                  {phase === "dispatching" ? "Waiting for the paid response…" : "Send one paid request"}
                </button>
                <button className="button button-quiet" type="button" disabled={working} onClick={reset}>
                  Start over
                </button>
              </div>
            </>
          )}
          {attempt !== null && (
            <AttemptPanel attempt={attempt} lostReply={lostReply} phase={phase} onPublish={publish} onCheck={check}
              onOpen={(draftId) => onPrepared(draftId)} />
          )}
          </>)}
        </div>
      )}
      {message && <p className={`intake-message ${message.tone === "done" ? "is-done" : "is-error"}`}
        role={message.tone === "done" ? "status" : "alert"}>{message.text}</p>}
    </section>
  );
}

/**
 * The inbox entry the form started from: where it came from, the feed's own timestamp with a suggestion only when it
 * was unambiguous, and the feed's excerpt shown apart from the published text, which the operator supplies.
 */
function InboxOrigin({ item, suggestionUsed, timeVerified, onUseSuggestion, onVerified }: {
  item: InboxItem;
  suggestionUsed: boolean;
  timeVerified: boolean;
  onUseSuggestion: () => void;
  onVerified: (verified: boolean) => void;
}) {
  const stamp = item.feed_timestamp;
  const suggestion = stamp.suggestion;
  return (
    <div className="intake-origin" data-item={item.id}>
      <p className="intake-origin-head">
        From the event inbox: {item.publisher} · {item.category}
        {entryLink(item) && <> · <a href={item.link} target="_blank" rel="noreferrer">{linkLabel(item.kind)}</a></>}
      </p>
      <p className="intake-origin-kind">
        {kindNote(item.kind)}.{item.attribution && ` Credit the publisher as “${item.attribution}”.`}
      </p>
      <p>
        <span className="intake-origin-label">Feed timestamp ({stamp.origin})</span>{" "}
        <code className="intake-origin-raw">{stamp.raw ?? "none"}</code>
        {stamp.instant_utc ? ` = ${utcStamp(stamp.instant_utc)}` : ""}. A feed's timestamp is not a verified release
        time; check the release itself.
      </p>
      {suggestion ? (
        <p className="intake-origin-suggestion">
          Suggestion: {suggestion.date} {suggestion.time} UTC{suggestion.offset.replace("-", "−")}, as the feed states it
          {suggestion.dropped_fraction ? ` (the feed's ${suggestion.dropped_fraction} s is dropped: the form takes whole seconds)` : ""}.{" "}
          <button type="button" className="button button-quiet intake-use-suggestion" onClick={onUseSuggestion}>
            {suggestionUsed ? "Fill again from the feed timestamp" : "Fill date, time and offset from the feed timestamp"}
          </button>
        </p>
      ) : (
        <p className="intake-origin-suggestion is-none">
          No suggestion: {stamp.problem ?? "the feed timestamp cannot be used."} Enter the release's own date, time and
          UTC offset.
        </p>
      )}
      {suggestionUsed && (
        <label className="intake-confirm intake-time-verified">
          <input type="checkbox" checked={timeVerified} onChange={(event) => onVerified(event.target.checked)} />
          <span>I checked this date, time and offset against the release itself, and corrected them if needed.</span>
        </label>
      )}
      <div className="intake-origin-excerpt">
        <p><span className="intake-origin-label">Feed excerpt, not the published text</span></p>
        <p>{item.excerpt && !item.excerpt_repeats_title ? item.excerpt
          : item.excerpt ? "The feed's description only repeats the headline." : "The feed gives no excerpt."}</p>
        <p>Paste the release's published text into Published text below yourself; the excerpt is never used as the
          text.</p>
      </div>
    </div>
  );
}

/** Saved events, newest first, each reopened with reads only. One that does not verify cannot be opened. */
function SavedCaptures({ saved, opening, onOpen, onReload }: {
  saved: SavedList;
  opening: boolean;
  onOpen: (captureId: string) => void;
  onReload: () => void;
}) {
  return (
    <div className="intake-saved">
      <div className="intake-saved-head">
        <h3>Saved events</h3>
        <button type="button" className="button button-quiet intake-saved-reload" onClick={onReload}>Refresh list</button>
      </div>
      <p className="intake-saved-note">
        Open a saved event to see its exact saved request again, with this server's sending modes and what was recorded
        for it. Opening reads only: nothing is captured, sent or approved.
      </p>
      {saved.state === "loading" && <p className="intake-saved-state">Loading saved events…</p>}
      {saved.state === "error" && (
        <p className="intake-saved-state is-error" role="alert">The saved events could not be read: {saved.message}</p>
      )}
      {saved.state === "ready" && saved.captures.length === 0 && <p className="intake-saved-state">No saved events yet.</p>}
      {saved.state === "ready" && saved.captures.length > 0 && (
        <ul className="intake-saved-list">
          {[...saved.captures].reverse().map((row) => (
            <li key={row.capture_id} className={row.state === "refused" ? "is-refused" : ""} data-capture={row.capture_id}>
              {row.state === "refused" ? (
                <>
                  <span className="intake-saved-headline">Cannot be verified, so it cannot be opened</span>
                  <span className="intake-saved-meta"><code className="draft-wrap">{row.capture_id}</code> · {row.problem}</span>
                </>
              ) : (
                <>
                  <span className="intake-saved-headline">{row.headline}</span>
                  <span className="intake-saved-meta">Published {row.published_at} · captured {row.captured_at} ·
                    request <code>{row.request_sha256?.slice(0, 12)}…</code></span>
                  <button type="button" className="button intake-reopen" onClick={() => onOpen(row.capture_id)}>Open</button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      {opening && <p className="intake-saved-state" role="status">Opening the saved event (reads only)…</p>}
    </div>
  );
}

/** The cost decision for one paid request: the estimate, what it assumes, when the prices were read. */
function PaidDecision({ preview }: { preview: IntakePreview }) {
  const estimate = preview.cost_estimate;
  return (
    <div className="paid-decision" role="note">
      <p className="paid-estimate">
        Planning estimate: <strong>${estimate.estimated_real_run_if_output_reaches_max_usd.toFixed(4)}</strong> for
        one request to {preview.model} at {preview.effort} effort, if output reaches {preview.max_tokens.toLocaleString()}
        {" "}tokens. Not a guaranteed billing ceiling.
      </p>
      <ul className="paid-assumptions">
        {estimate.assumptions.map((assumption) => <li key={assumption}>{assumption}</li>)}
      </ul>
      <p className="paid-source">
        Prices read on {estimate.prices.read_on} from <a href={estimate.prices.source} target="_blank"
          rel="noreferrer">Anthropic's pricing page</a>. {estimate.caveat}
      </p>
    </div>
  );
}

/** The saved request's own publication instant agrees with the capture's normalized time. */
const timeConfirmed = (preview: IntakePreview) => requestPublishedAt(preview.request) === preview.times.published_at;

/** The publication time exactly as supplied, beside the UTC instant the saved request holds; both are shown as text. */
function PublicationTimes({ preview }: { preview: IntakePreview }) {
  const saved = requestPublishedAt(preview.request);
  return (
    <div className="intake-times">
      <div className="intake-time-supplied">
        <span>Publication time as supplied</span>
        <strong>{preview.times.published_at_as_supplied}</strong>
      </div>
      <div className="intake-time-utc">
        <span>In the saved request (UTC)</span>
        <strong>{saved ?? "not found in the saved request"}</strong>
      </div>
      {!timeConfirmed(preview) && (
        <p className="intake-time-warning" role="alert">
          The saved request's publication time could not be confirmed, so this request cannot be approved.
        </p>
      )}
    </div>
  );
}

/** What the saved records show after an unconfirmed or refused action, and the one action that state allows. */
function AttemptPanel({ attempt, lostReply, phase, onPublish, onCheck, onOpen }: {
  attempt: Exclude<Known, null>;
  lostReply: boolean;
  phase: Phase;
  onPublish: () => void;
  onCheck: () => void;
  onOpen: (draftId: string) => void;
}) {
  if (attempt === "unreadable") {
    return (
      <div className="intake-attempt is-unknown" data-state="unreadable" role="alert">
        <p>What this capture recorded is unknown, so approving again is not offered. Nothing is sent by checking.</p>
        <button type="button" className="button intake-check" disabled={phase !== "ready"} onClick={onCheck}>
          {phase === "checking" ? "Checking…" : "Check what was recorded"}
        </button>
      </div>
    );
  }
  const lead = attempt.state === "ready"
    ? `${lostReply ? "The reply was lost or could not be confirmed, but the saved records show the result: " : ""}` +
      `${outcomeText(attempt.recorded_outcome, attempt.mode)} It is ready for review.`
    : attempt.state === "incomplete" && attempt.mode === "paid" ? attempt.detail : ATTEMPT_TEXT[attempt.state];
  const stillSending = attempt.state === "incomplete" && attempt.mode === "paid" && attempt.sent;
  return (
    <div className={`intake-attempt is-${attempt.state}`} data-state={attempt.state} data-mode={attempt.mode ?? ""}
      role={attempt.state === "ready" ? "status" : "alert"}>
      <p>{lead}</p>
      {attempt.state === "invalid" && <p className="intake-attempt-detail">{attempt.detail}</p>}
      {attempt.state === "incomplete" && attempt.files.length > 0 && (
        <p className="intake-attempt-detail">Recorded so far: {attempt.files.join(", ")}.</p>
      )}
      {stillSending && (
        <button type="button" className="button intake-check" disabled={phase !== "ready"} onClick={onCheck}>
          {phase === "checking" ? "Checking…" : "Check again (reads only; nothing is sent)"}
        </button>
      )}
      {attempt.state === "awaiting_publication" && (
        <button type="button" className="button intake-publish" disabled={phase !== "ready"} onClick={onPublish}>
          {phase === "publishing" ? "Publishing the recorded response…" : "Publish the recorded response"}
        </button>
      )}
      {attempt.state === "ready" && attempt.draft_id && (
        <button type="button" className="button button-quiet intake-open" onClick={() => onOpen(attempt.draft_id!)}>
          Open it for review
        </button>
      )}
    </div>
  );
}
