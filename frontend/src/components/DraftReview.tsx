import { useCallback, useEffect, useRef, useState, type CSSProperties, type RefObject } from "react";
import { returnLabel, returnPath } from "../analyses";
import { fetchDraft, fetchDrafts, fetchReviews, useLoad } from "../api";
import type { Loaded } from "../api";
import type { DraftIndex, DraftReviewView, LoadedDraft, ReviewHistory } from "../draftTypes";
import {
  OUTCOME_INFO, PREPARE_DRAFTS_COMMAND, REVIEW_CHECKLIST, draftRows, legRows, requestedDraft,
  viewProblems,
} from "../drafts";
import { formatDay, formatUtc } from "../format";
import { guardLeaving } from "../leave";
import { DISCARD_QUESTION } from "../review";
import { Link, navigate } from "../router";
import { DraftFreezeFlag } from "./DraftFreeze";
import { DraftMap } from "./DraftMap";
import { HumanReview } from "./HumanReview";
import "../drafts.css";

const PANEL_ID = "draft-review-panel";

/**
 * Saved model drafts awaiting human review: separate from frozen cases, never evaluated or scored.
 *
 * The last list that loaded stays on screen while a refresh is pending or after one fails, so the open review is
 * never unmounted by a refresh. A newly prepared draft is opened only through the same leave check as a manual
 * selection; if the reviewer keeps their unsaved edits, the new draft waits in the list.
 */
export function DraftsSection({ search, prepared, style }: {
  search: string;
  prepared?: { id: string; revision: number } | null;
  style?: CSSProperties;
}) {
  const [drafts, retry] = useLoad(fetchDrafts, `drafts-${prepared?.revision ?? 0}`);
  const [known, setKnown] = useState<DraftIndex | null>(null);
  const [selected, setSelected] = useState<string | null>(() => requestedDraft(search));
  const [waiting, setWaiting] = useState<string | null>(null);  // A new draft to open once it is listed.
  const [notice, setNotice] = useState<string | null>(null);
  const [moveFocus, setMoveFocus] = useState(false);
  const panel = useRef<HTMLElement>(null);
  const unsaved = useRef(false);
  // The draft a ?draft= link opened: its panel is brought into view once it has loaded, then never again.
  const [arrival, setArrival] = useState<string | null>(() => requestedDraft(search));
  const onDirtyChange = useCallback((dirty: boolean) => {
    unsaved.current = dirty;
  }, []);
  // Leaving the Tracker (a link, Back or Forward) would discard an unsaved review; changing ?draft= does not.
  useEffect(() => guardLeaving((pathname) => (unsaved.current && pathname !== "/" ? DISCARD_QUESTION : null)), []);

  useEffect(() => {
    if (drafts.state === "ready") setKnown(drafts.data);
  }, [drafts]);
  const list = drafts.state === "ready" ? drafts.data : known;

  useEffect(() => {
    if (moveFocus) {
      panel.current?.focus();
      setMoveFocus(false);
    }
  }, [moveFocus, selected]);

  /** Show a draft, asking first if that would discard an unsaved review. Returns whether it is shown. */
  const show = (id: string): boolean => {
    if (id !== selected) {
      if (unsaved.current && !window.confirm(DISCARD_QUESTION)) return false;
      setSelected(id);  // The review being left reports itself clean as it unmounts.
      navigate(`/?draft=${id}`, { replace: true });
    }
    setNotice(null);
    setMoveFocus(true);
    return true;
  };

  useEffect(() => {
    if (prepared) setWaiting(prepared.id);
  }, [prepared]);

  useEffect(() => {
    const row = waiting ? list?.drafts.find((item) => item.id === waiting) : undefined;
    if (!row) return;
    setWaiting(null);
    if (!show(row.id)) {
      setNotice(`A new draft, "${row.headline}", is ready in the list. Select it after saving or discarding this ` +
                "review.");
    }
  }, [waiting, list]);  // `show` reads the current selection and unsaved state when the new draft is listed.

  const rows = list ? draftRows(list) : [];
  const refreshFailed = list !== null && drafts.state !== "ready" && drafts.state !== "loading";
  const back = returnPath(search);  // Only an address of My analyses or an event overview, never another one.
  return (
    <section className="card tracker-section drafts-section reveal" style={style} aria-labelledby="drafts-title">
      <div className="tracker-section-head">
        <h2 id="drafts-title">Drafts for review</h2>
        {list && (
          <span className="tracker-count">{rows.length === 1 ? "1 saved attempt" : `${rows.length} saved attempts`}</span>
        )}
      </div>
      <p className="card-note">
        Saved model drafts from offline pilot runs and from Analyze an event. A draft is not itself a frozen
        hypothesis and is never evaluated; each requires human review. A reviewed draft frozen on the Hypotheses page
        shows that freeze, read from its freeze record.
      </p>

      {!list && drafts.state === "loading" && <p className="draft-state" role="status">Loading saved drafts…</p>}
      {!list && drafts.state === "not-prepared" && (
        <div className="draft-state" role="status">
          <p>No drafts have been prepared for review. {drafts.message}</p>
          <pre><code>{PREPARE_DRAFTS_COMMAND}</code></pre>
        </div>
      )}
      {!list && (drafts.state === "error" || drafts.state === "missing") && (
        <div className="draft-state" role="alert">
          <p>The saved drafts could not be loaded. {drafts.message}</p>
          <button type="button" className="button" onClick={retry}>Try again</button>
        </div>
      )}
      {list && drafts.state === "loading" && <p className="drafts-refreshing" role="status">Refreshing the list…</p>}
      {refreshFailed && (
        <div className="draft-state drafts-refresh-error" role="alert">
          <p>
            The draft list could not be refreshed. {"message" in drafts ? drafts.message : ""} The drafts shown are from
            the last successful load, and the open review is unchanged.
          </p>
          <button type="button" className="button" onClick={retry}>Try again</button>
        </div>
      )}
      {notice && <p className="drafts-notice" role="status">{notice}</p>}
      {list && rows.length === 0 && <p className="empty">No saved draft has been prepared.</p>}

      {rows.length > 0 && (
        <>
          <ul className="draft-list" aria-label="Saved drafts">
            {rows.map((row) => {
              const outcome = OUTCOME_INFO[row.outcome];
              return (
                <li key={row.id}>
                  <button
                    type="button"
                    className="draft-choice"
                    aria-pressed={row.id === selected}
                    aria-controls={PANEL_ID}
                    onClick={() => show(row.id)}
                  >
                    <span className="draft-choice-headline">{row.headline}</span>
                    <span className="draft-choice-meta">
                      {row.case} · {row.pilot} · sent {formatDay(row.sent_at)}
                    </span>
                    <span className={`outcome-chip ${outcome?.className ?? "outcome-unknown"}`}>
                      {outcome?.label ?? "Unknown outcome"}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          {selected === null ? (
            <p className="draft-hint">Select a saved draft to review it beside its source.</p>
          ) : rows.some((row) => row.id === selected) ? (
            <DraftPanel key={selected} id={selected} panel={panel} onDirtyChange={onDirtyChange} back={back}
                        arrive={arrival === selected} onArrived={() => setArrival(null)} />
          ) : (
            <p className="draft-state" role="alert">The requested draft is not among the prepared drafts.</p>
          )}
        </>
      )}
    </section>
  );
}

function DraftPanel({ id, panel, onDirtyChange, back, arrive, onArrived }: {
  id: string;
  panel: RefObject<HTMLElement>;
  onDirtyChange: (dirty: boolean) => void;
  back: string | null;
  arrive: boolean;
  onArrived: () => void;
}) {
  const [view, retry] = useLoad((signal) => fetchDraft(id, signal), id);
  const [history, reloadHistory] = useLoad((signal) => fetchReviews(id, signal), `reviews-${id}`);
  useEffect(() => {  // Opened by a link: once the view has loaded, the page is tall enough to bring it to the top.
    if (arrive && view.state !== "loading") {
      panel.current?.focus({ preventScroll: true });
      panel.current?.scrollIntoView({ block: "start" });
      onArrived();
    }
  }, [arrive, view.state]);  // `panel` and `onArrived` are stable for this panel's lifetime.
  const reload = () => {  // The view and its saved versions together, so a review starts from both afresh.
    retry();
    reloadHistory();
  };
  return (
    <section id={PANEL_ID} ref={panel} tabIndex={-1} className="draft-panel" aria-labelledby="draft-panel-title"
             aria-busy={view.state === "loading"}>
      {back && <p className="drafts-return"><Link to={back}>{returnLabel(back)}</Link></p>}
      {view.state === "loading" && <p className="draft-state" role="status" id="draft-panel-title">Loading the draft…</p>}
      {view.state === "ready" && (
        <DraftReviewBody draft={view.data} history={history} onReload={reload} onDirtyChange={onDirtyChange} />
      )}
      {view.state !== "loading" && view.state !== "ready" && (
        <div className="draft-state" role="alert">
          <h3 id="draft-panel-title">The draft could not be loaded</h3>
          <p>{view.message}</p>
          {view.state === "error" && <button type="button" className="button" onClick={retry}>Try again</button>}
        </div>
      )}
    </section>
  );
}

function DraftReviewBody({ draft, history, onReload, onDirtyChange }: {
  draft: LoadedDraft;
  history: Loaded<ReviewHistory>;
  onReload: () => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { view, fingerprint } = draft;
  const problems = viewProblems(view);
  if (problems.length > 0) {
    return (
      <div className="draft-state" role="alert">
        <h3 id="draft-panel-title">This prepared view is inconsistent and is not shown</h3>
        <ul>{problems.map((problem) => <li key={problem}>{problem}</li>)}</ul>
        <p>Prepare the drafts again from their saved records.</p>
      </div>
    );
  }
  const outcome = OUTCOME_INFO[view.outcome];
  const { provenance, source } = view;
  return (
    <>
      <header className="draft-panel-head">
          <p className="kicker">Draft for review · {provenance.case}</p>
        <h3 id="draft-panel-title">{source.headline}</h3>
        <DraftFreezeFlag draftId={view.id} fingerprint={fingerprint} history={history} />
        <p className="draft-outcome">
          <span className={`outcome-chip ${outcome.className}`}>{outcome.label}</span> {outcome.meaning}
        </p>
      </header>

      <div className="draft-columns">
        <section className="draft-column draft-source" aria-labelledby="draft-source-title">
          <h4 id="draft-source-title">Source, as recorded in the request</h4>
          <p className="draft-note">Untrusted input that was sent to the model, shown as plain text.</p>
          <dl className="draft-facts">
            <div><dt>Headline</dt><dd>{source.headline}</dd></div>
            <div><dt>Source URL</dt><dd><code className="draft-wrap">{source.source_url}</code></dd></div>
            <div><dt>Published</dt><dd>{formatUtc(source.published_at)}</dd></div>
          </dl>
          <pre className="draft-source-text">{source.text}</pre>
        </section>

        <section className="draft-column draft-model" aria-labelledby="draft-model-title">
          <h4 id="draft-model-title">The model's proposed interpretation</h4>
          <p className="draft-note">
            {provenance.synthetic_case && provenance.pilot === "tracker-mock-1"
              ? `Generated by a local mock shaped as ${provenance.model} under ${provenance.prompt_version}; no provider was contacted. `
              : `Written by ${provenance.model} under ${provenance.prompt_version}. `}
            Everything in this column is a proposal, not a finding; checks on its structure do not verify its reasoning.
            Your corrections are saved separately under Your review.
          </p>
          <ModelContent view={view} />
        </section>
      </div>

      <section className="review-checklist" aria-labelledby="draft-checklist-title">
        <h4 id="draft-checklist-title">Human review checklist</h4>
        <ol>
          {REVIEW_CHECKLIST.map((item) => (
            <li key={item.topic}><strong>{item.topic}.</strong> {item.question}</li>
          ))}
        </ol>
        <p className="draft-note">A prompt for your judgment. The page scores nothing and approves nothing; it records only
          what you choose to save below.</p>
      </section>

      <HumanReview view={view} fingerprint={fingerprint} history={history} onReload={onReload}
                   onDirtyChange={onDirtyChange} />

      <details className="draft-provenance">
        <summary>Recorded provenance</summary>
        <dl className="draft-facts">
          {provenanceFacts(view, fingerprint).map(([term, value, code]) => (
            <div key={term}><dt>{term}</dt><dd>{code ? <code className="draft-wrap">{value}</code> : value}</dd></div>
          ))}
        </dl>
      </details>
    </>
  );
}

/** Recorded provenance as [term, value, shown as code]. */
function provenanceFacts({ provenance: p }: DraftReviewView, fingerprint: string): [string, string, boolean][] {
  const unrecorded = (value: string | number | null) => (value === null ? "not recorded" : String(value));
  return [
    ["Run · case", `${p.pilot} · ${p.case}`, false],
    ["Model", `${p.model}, effort ${unrecorded(p.effort)}, max_tokens ${unrecorded(p.max_tokens)}`, false],
    ["Prompt version", p.prompt_version, false],
    ["Prompt hash (SHA-256 of the exact request)", p.prompt_hash, true],
    ["Request ID", unrecorded(p.request_id), true],
    ["Sent · received", `${formatUtc(p.sent_at)} · ${formatUtc(p.received_at)}`, false],
    ["HTTP status · recorded outcome", `${unrecorded(p.http_status)} · ${p.recorded_outcome}`, false],
    ["Response SHA-256", p.response_sha256 ?? "no response recorded", true],
    ["Prepared view SHA-256 (as loaded; reviews are bound to it)", fingerprint, true],
  ];
}

function ModelContent({ view }: { view: DraftReviewView }) {
  if (view.draft) {
    const draft = view.draft;
    return (
      <>
        <h5>Summary <span className="draft-attribution">(the model's words)</span></h5>
        <p className="draft-summary">{draft.summary}</p>
        <h5>Proposed map</h5>
        <DraftMap nodes={draft.nodes} edges={draft.edges} legs={draft.legs} />
        <h5>Proposed legs</h5>
        <ol className="draft-legs">
          {legRows(draft).map((leg) => (
            <li key={leg.id} className="draft-leg">
              <p className="draft-leg-title">{leg.role} · {leg.node} <code>{leg.observable}</code></p>
              <dl className="draft-facts">
                <div><dt>Proposed direction</dt><dd>{leg.direction}</dd></div>
                <div><dt>Horizon</dt><dd>{leg.horizon}</dd></div>
                <div><dt>Link</dt><dd>{leg.link}</dd></div>
                <div><dt>Channel</dt><dd>{leg.channel}</dd></div>
                <div><dt>Move already reported?</dt><dd>{leg.reportsMove}</dd></div>
                <div><dt>Reasoning</dt><dd>{leg.rationale}</dd></div>
                <div><dt>Falsifier</dt><dd>{leg.falsifier}</dd></div>
              </dl>
            </li>
          ))}
        </ol>
      </>
    );
  }
  if (view.explanation) {
    const { text, category, provider_explanation: said } = view.explanation;
    return (
      <>
        <h5>No draft <span className="draft-attribution">(the model's public explanation)</span></h5>
        {text.length > 0
          ? text.map((paragraph, i) => <p key={i} className="draft-plain">{paragraph}</p>)
          : <p className="empty">The model gave no explanation.</p>}
        {(category || said) && (
          <p className="draft-note">
            Declined with stop reason {view.explanation.stop_reason}
            {category ? `, category ${category}` : ""}{said ? `: ${said}` : "."}
          </p>
        )}
      </>
    );
  }
  return (
    <>
      <h5>{OUTCOME_INFO[view.outcome].label}</h5>
      <p className="draft-plain">{view.problem}</p>
      <p className="draft-note">No model content is shown for this attempt.</p>
    </>
  );
}
