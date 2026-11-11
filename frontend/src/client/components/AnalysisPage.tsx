import { useEffect, useReducer, useRef } from "react";
import { Link } from "../../router";
import { accountOf, useClient, zoneOf } from "../context";
import { NOT_APPROVED, outcomeOf, runApproved, runEvents } from "../controller.ts";
import {
  advisories, allowanceBesideDecision, focusAfter, initialFlow, panel, reduce, type Busy, type FlowEvent, type FocusTarget,
} from "../flow.ts";
import { href } from "../paths.ts";
import {
  ATTEMPT_LINE, QUOTE_STATE_TEXT, RUNNING_NOTE, UNCERTAIN_NOTE, approvalSentence, chargeLine, effortLabel,
  headerState, quoteTimes,
} from "../present.ts";
import type { Notice } from "../refusals.ts";
import { Entitlements } from "./Entitlements";
import { NoticeView } from "./NoticeView";
import { ResearchChecks } from "./ResearchChecks";
import { ResultView } from "./ResultView";
import { ReviewEditor } from "./ReviewEditor";

/** One analysis: its state as the server records it, the quote and your approval while it is prepared, and the result
 * with your review once it is recorded. Opening it only reads; every write is your explicit action. */
export function AnalysisPage({ analysisId }: { analysisId: string }) {
  const { api, account, adoptAccount, endSession, mayAct, readAccount } = useClient();
  const [state, dispatch] = useReducer(reduce, initialFlow);
  const acting = useRef(false);
  const zone = zoneOf(account);
  const current = accountOf(account);

  const act = async (busy: Exclude<Busy, null>, work: () => Promise<void>) => {
    if (acting.current) return;  // One action at a time, even for two clicks delivered together.
    acting.current = true;
    dispatch({ type: "busy", busy });
    try {
      await work();
    } finally {
      acting.current = false;
    }
  };
  /** Where focus goes once an explicit action's outcome is shown (flow.ts focusAfter); applied by the effect below. */
  const pendingFocus = useRef<FocusTarget | null>(null);
  /** An explicit action's outcome: shown, and if the page now offers something new, focus is sent to it, so a keyboard
   * or screen-reader user is not left on a control that has gone. `state` is this render's, as the action began. */
  const settle = (event: FlowEvent) => {
    pendingFocus.current = focusAfter(panel(state), panel(reduce(state, event)));
    dispatch(event);
  };
  const fail = (notice: Notice) => dispatch({ type: "notice", notice });
  /** A refused quote or run: show it, and read the account again (a GET) so the figures beside the action are the
   * server's latest rather than those an earlier reply carried. */
  const refused = (notice: Notice) => {
    fail(notice);
    void readAccount();
  };

  /** Read the analysis. On opening the page this only shows it; as the person's own "Check again" it also sends focus
   * to whatever is new. */
  const read = (explicit = true) => act("reading", async () => {
    const outcome = outcomeOf(await api.analysis(analysisId), null, zone);
    if (outcome.kind === "ok") {
      const event: FlowEvent = { type: "read", analysis: outcome.data.analysis };
      if (explicit) settle(event);
      else dispatch(event);
    } else if (outcome.kind === "session") endSession(outcome.reason);
    else fail(outcome.notice);
  });

  useEffect(() => { void read(false); }, [analysisId]);  // A read: nothing is prepared, quoted or run on load.

  useEffect(() => {  // After an action's outcome is shown: focus its new step, unless the person has moved on.
    const target = pendingFocus.current;
    const element = target ? document.querySelector<HTMLElement>(`[data-focus-target="${target}"]`) : null;
    if (!element) return;  // Not shown yet (or nothing to go to): wait for the render that shows it.
    pendingFocus.current = null;
    // Moved on: focus is on something the person chose outside the state card, not on a place the page sent it to.
    const active = document.activeElement;
    const movedOn = active !== null && active !== document.body && active.isConnected &&
      !active.closest(".client-state") && !active.matches("h1.client-title, [data-focus-target]");
    if (!movedOn) element.focus();
  });

  const analysis = state.analysis;
  useEffect(() => {
    document.title = `${analysis ? analysis.source.headline : "Analysis"} · Second Order`;
  }, [analysis]);

  const quote = () => act("quoting", async () => {
    if (!analysis) return;
    const outcome = outcomeOf(await api.quote(analysis.analysis_id), null, zone);
    if (outcome.kind === "ok") {
      adoptAccount(outcome.data.account);
      settle({ type: "quoted", quote: outcome.data.quote });
    } else if (outcome.kind === "session") endSession(outcome.reason);
    else refused(outcome.notice);
  });

  const run = () => act("running", async () => {
    // `state` is this render's: the request is sent only when it allows a run (mayRun), and at most once.
    const outcome = await runApproved(api, state, zone);
    const event = runEvents(outcome);
    if (event.type === "session") return endSession(event.reason);
    if (outcome.kind === "ok") adoptAccount(outcome.data.account);
    settle(event);  // An unconfirmed reply gates the page until the analysis is read again.
    if (outcome.kind === "notice" && outcome.notice !== NOT_APPROVED) void readAccount();
  });

  if (!analysis) {
    if (state.notice) {
      return <section className="card client-card"><NoticeView notice={state.notice} onReadAgain={() => void read()}
                                                                 busy={state.busy !== null} /></section>;
    }
    return <p className="client-status" role="status">Reading the analysis…</p>;
  }

  const shown = panel(state);
  const allowanceFirst = allowanceBesideDecision(shown);
  const header = headerState(state)!;  // The analysis has been read, so there is a header.
  const charge = chargeLine(analysis.charge);
  const effort = `${effortLabel(analysis.effort, current)} Effort`;
  return (
    <>
      <header className="client-header">
        <p className="kicker">Research analysis · {effort}</p>
        <h1 className="client-title">{analysis.source.headline}</h1>
        <p className="client-chips">
          <span className="client-chip is-state" data-state={header.key}>{header.label}</span>
          {header.outcome && <span className="client-chip is-outcome" data-outcome={header.outcome.key}>
            {header.outcome.label}</span>}
        </p>
        <p className="client-sub"><Link to={href.source(analysis.source.source_id)}>The source and its other
          analyses</Link> · another Effort is a separate analysis and never changes this one.</p>
      </header>

      <section className="card client-card client-state" aria-label="This analysis's state" data-panel={shown.kind}
               data-focus-target="state" tabIndex={-1}>
        {/* While a run is uncertain, the last read is out of date: only the uncertainty is shown until a new read. */}
        {shown.kind !== "uncertain" && <p className="client-state-detail">{analysis.state_detail}</p>}
        {shown.kind !== "uncertain" && charge &&
          <p className="client-charge" data-charge={analysis.charge?.state}>{charge}</p>}
        {state.repeat && <p className="client-note" role="status">That approval had already been used, so nothing was
          reserved, charged or sent again. This is the analysis as it stands.</p>}
        {state.notice && (
          <NoticeView notice={state.notice} busy={state.busy !== null}
                      onNewQuote={shown.kind === "uncertain" ? undefined : () => void quote()}
                      onReadAgain={shown.kind === "uncertain" ? undefined : () => void read()}
                      effortHref={href.source(analysis.source.source_id)} />
        )}

        {shown.kind === "uncertain" && (
          <div className="client-held" data-uncertain="run">
            <p>{UNCERTAIN_NOTE}</p>
            <p className="client-actions">
              <button type="button" className="button client-check" disabled={state.busy !== null}
                      onClick={() => void read()}>{state.busy === "reading" ? "Reading…" : "Check again"}</button>
            </p>
          </div>
        )}

        {shown.kind === "quote" && (
          <div className="client-quote">
            {shown.previous && shown.previous.state !== "active" && (
              <p className="client-advisory">The last quote ({shown.previous.credits} credits):{" "}
                {QUOTE_STATE_TEXT[shown.previous.state]}</p>
            )}
            <p className="card-note">A quote states how many credits this analysis needs. Asking for one reserves
              nothing. <Link to={href.credits}>How credits work</Link></p>
            {advisories(current, null).map((line) => <p key={line} className="client-advisory">{line}</p>)}
            <p className="client-actions">
              <button type="button" className="button client-get-quote" disabled={!shown.canQuote}
                      onClick={() => void quote()}>{state.busy === "quoting" ? "Asking…" : "Get a credit quote"}</button>
            </p>
          </div>
        )}

        {shown.kind === "approve" && (
          <div className="client-quote is-approval" data-quote={shown.quote.quote_id} data-focus-target="quote"
               tabIndex={-1} role="group" aria-label="Credit quote: read it, then approve to run">
            <p className="client-label">Quote · approve it to run</p>
            <dl className="ledger client-ledger">
              <div><dt>Credits required</dt><dd data-quote-credits>{shown.quote.credits}</dd></div>
              <div><dt>Effort</dt><dd>{effortLabel(shown.quote.effort, current)}</dd></div>
              <div><dt>Valid until</dt><dd>{quoteTimes(shown.quote, zone).until}
                <span className="client-sub">{quoteTimes(shown.quote, zone).issued}</span></dd></div>
            </dl>
            {advisories(current, shown.quote).map((line) => <p key={line} className="client-advisory">{line}</p>)}
            <label className="client-approve">
              <input type="checkbox" checked={state.approved} disabled={state.busy !== null}
                     onChange={(event) => dispatch({ type: "approve", checked: event.target.checked })} />
              <span>{approvalSentence(analysis, shown.quote, current)}</span>
            </label>
            <p className="client-actions">
              <button type="button" className="button client-run" disabled={!shown.canRun} onClick={() => void run()}>
                {state.busy === "running" ? "Running…" : `Run the analysis (${shown.quote.credits} credits)`}</button>
            </p>
            {state.busy === "running" && <p className="client-note" role="status">{RUNNING_NOTE}</p>}
          </div>
        )}

        {(shown.kind === "running" || shown.kind === "held") && (
          <div className="client-held">
            {/* The attempt only; its credits are the charge line above, from the server's charge state. */}
            <p className="client-attempt">{ATTEMPT_LINE[analysis.state]}</p>
            <p className="client-actions">
              <button type="button" className="button button-quiet client-check" disabled={state.busy !== null}
                      onClick={() => void read()}>{state.busy === "reading" ? "Reading…" : "Check again"}</button>
            </p>
          </div>
        )}

        {shown.kind === "not_sent" && (
          <p>This prepared request cannot be run again. To analyse the source again,{" "}
            <Link to={href.source(analysis.source.source_id)}>choose another Effort</Link>.</p>
        )}
      </section>
      {allowanceFirst && <Entitlements compact />}

      {analysis.result && <ResultView analysis={analysis} />}
      {/* After the result, before the review: checks that ask for a look (a read), never a verdict. */}
      {analysis.result && analysis.result_sha256 && (
        <ResearchChecks analysisId={analysis.analysis_id} resultSha256={analysis.result_sha256} />
      )}
      {analysis.result && analysis.result_sha256 && (
        <ReviewEditor key={`${analysis.analysis_id}:${analysis.result_sha256}`} analysis={analysis}
                      onSaved={(next) => dispatch({ type: "read", analysis: next })} onReload={() => void read()} />
      )}
      {analysis.result && (
        <p className="client-sub client-export"><a href={api.exportHref(analysis.analysis_id)} download
          onClick={(event) => { if (!mayAct()) event.preventDefault(); }}>Download this analysis (JSON)</a> ·
          downloading reads the saved record and uses nothing.</p>
      )}
      {/* No decision left on this analysis: the allowance follows its result instead of standing before it. */}
      {!allowanceFirst && <Entitlements compact />}
    </>
  );
}
