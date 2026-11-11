import type { ReactNode } from "react";
import { formatUtc } from "../format";
import type { ChainView, ReadingRecordView, ReviewRecordView, Step } from "../eventChains";
import { eventLines, mechanismMark, priceChanges, priceContext, reviewBlockedBy, reviewNoteSentence }
  from "../eventChainText";
import { JUDGMENT_LABEL, LONG_TERM, ReadingForm, ReviewForm, SHORT_TERM, useReadingDraft, useReviewDraft, useSave,
  useUnsavedGuard } from "./EventChainForms";

export const SOURCE_WORDING_NOTE =
  "A paraphrase, or fewer than six words of a source, cannot be detected; it is shown as the owner's own wording.";
const STEP_JOIN = "and if so";
const CHAIN_STATE: Record<ChainView["state"], string> = {
  unavailable: "Unavailable", needs_revalidation: "Needs revalidation", evidence_changed: "Evidence changed",
  thesis_newer: "A newer thesis version exists", available: "Available",
};
const DOCUMENT_STATE: Record<string, string> = {
  verified: "matches its acquisition record", changed: "differs from its acquisition record",
  missing: "is missing", superseded: "has been superseded", unreadable: "cannot be read",
};
const STEP_STATE: Record<string, string> = {
  verified: "Quote verified in the retained document", not_found: "The quote is not found in the retained document",
  record_changed: "The record's wording or place changed since it was pinned",
  record_gone: "The record is no longer in the evidence",
};
const REVIEW_STATE: Record<ReviewRecordView["state"], string> = {
  needs_revision: "Needs revision", approved: "Approved, current", approved_earlier_basis: "Approved on an earlier basis",
};
const READING_STATE: Record<ReadingRecordView["state"], string> = { current: "Current reading", earlier_basis: "Earlier basis" };

const text = (value: unknown): string | null => (typeof value === "string" && value !== "" ? value : null);
const record = (value: unknown): Record<string, unknown> | null =>
  typeof value === "object" && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : null;

function Part({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section className="ec-part" data-part={id} aria-label={title}>
      <h3>{title}</h3>
      {children}
    </section>
  );
}

function Joined({ children }: { children: ReactNode }) {
  return <p className="ec-join" data-join="">{children}</p>;
}

function Quote({ words, where }: { words: string; where: string }) {
  return (
    <blockquote className="ec-quote"><p>{words}</p><footer>{where}</footer></blockquote>
  );
}

function StatedStep({ step, number }: { step: Extract<Step, { kind: "stated" }>; number: number }) {
  const changed = step.state === "record_changed";
  return (
    <div className="ec-step" data-step={number} data-step-state={step.state}>
      <p className="ec-step-head"><span className="ec-step-no">Step {number}</span>{" "}
        {step.label !== null && <strong>{step.label}</strong>}</p>
      {step.quote !== null && <Quote words={step.quote} where={step.where} />}
      {changed && (
        <div className="ec-sides" data-sides="">
          <div data-side="pinned"><h4>Pinned wording</h4>
            {step.pinned_quote !== null && <Quote words={step.pinned_quote} where={step.pinned_where ?? step.where} />}</div>
          <div data-side="current"><h4>The record's current wording</h4>
            {step.current_quote !== null
              ? <Quote words={step.current_quote} where={step.current_where ?? step.where} />
              : <p className="ec-withheld">Withheld.</p>}</div>
        </div>)}
      {step.state === "record_gone" && step.pinned_quote !== null && (
        <Quote words={step.pinned_quote} where={step.pinned_where ?? step.where} />)}
      <p className="ec-source-line">
        {step.document.name} {DOCUMENT_STATE[step.document.state] ?? step.document.state}.
        {" "}{STEP_STATE[step.state] ?? step.state}.</p>
      {step.problem !== null && <p className="ec-withheld">{step.problem}</p>}
    </div>
  );
}

function Basis({ item }: { item: ReviewRecordView | ReadingRecordView }) {
  return (
    <details className="ec-basis">
      <summary>Basis: chain version {item.basis.chain.version}, thesis version {item.basis.thesis.version}</summary>
      <ul>{item.basis_documents.map((doc) => (
        <li key={doc.ref} data-document-state={doc.state}>{doc.name} {DOCUMENT_STATE[doc.state] ?? doc.state}.</li>))}</ul>
      {item.masked && item.mask_reason !== null && <p className="ec-withheld">Figures withheld: {item.mask_reason}</p>}
      {item.differs.length > 0 && (
        <p>What differs now: {item.differs.join("; ")}</p>)}
    </details>
  );
}

function Signed({ account, at }: { account: { username: string }; at: string }) {
  return <span className="ec-signed">{account.username}, {formatUtc(at)}</span>;
}

function Reading({ chain }: { chain: ChainView }) {
  const now = chain.reading;
  return now === null ? <p className="ec-none" data-reading="none">No reading is current for this version.</p> : (
    <div className="ec-owner" data-reading="current">
      <p className="ec-voice">You wrote, signed <Signed account={now.account} at={now.saved_at} />:</p>
      <dl className="ec-judgments">
        <dt>{SHORT_TERM}</dt><dd>{JUDGMENT_LABEL[now.short_term]}</dd>
        <dt>{LONG_TERM}</dt><dd>{JUDGMENT_LABEL[now.long_term]}</dd>
      </dl>
      <p className="ec-own-text" dir="auto">{now.line}</p>
      {now.masked && now.mask_reason !== null && <p className="ec-withheld">Figures withheld: {now.mask_reason}</p>}
      <p className="ec-own-note">Your own view, in your own wording: not a source's and not the assistant's.</p>
    </div>
  );
}

function Review({ chain }: { chain: ChainView }) {
  const approval = chain.approval;
  if (approval.state === null) return null;
  if (approval.state === "awaiting_review") {
    return <p className="ec-review-state" data-approval="awaiting_review">Your review of this version: awaiting your review.</p>;
  }
  return (
    <div className="ec-owner" data-approval={approval.state}>
      <p className="ec-review-state">Your review of this version: {REVIEW_STATE[approval.state as ReviewRecordView["state"]]
        ?? approval.state}, {approval.account !== null && approval.saved_at !== null
        && <Signed account={approval.account} at={approval.saved_at} />}.</p>
      {approval.notes !== null && approval.notes !== "" && <p className="ec-own-text" dir="auto">{approval.notes}</p>}
      {approval.masked === true && <p className="ec-withheld">Figures in these notes are withheld while a document of their basis does not verify.</p>}
      {approval.differs.length > 0 && <p>What differs now: {approval.differs.join("; ")}</p>}
    </div>
  );
}

/**
 * Both forms. Their drafts and save outcomes live here, above the forms, so a reload never loses them: a form that holds
 * text or a refusal stays on screen (unable to send while the chain is closed) beside the reason, and the leave guard
 * covers both texts.
 */
function Forms({ chain, onReload }: { chain: ChainView; onReload: () => void }) {
  const draft = useReadingDraft();
  const review = useReviewDraft();
  const readingSave = useSave(chain, onReload, () => { draft.setLine(""); draft.setShortTerm(null); draft.setLongTerm(null); });
  const reviewSave = useSave(chain, onReload, () => { review.setNotes(""); review.setStatus(null); });
  useUnsavedGuard(draft.line.trim() !== "" || review.notes.trim() !== "");
  const typed = draft.line.trim() !== "";
  const keepReview = review.notes.trim() !== "" || reviewSave.refused || reviewSave.phase !== "idle";
  const keepReading = typed || readingSave.refused || readingSave.phase !== "idle";
  const reviewForm = (closed: boolean) => (
    <ReviewForm chain={chain} draft={review} save={reviewSave} blocked={reviewBlockedBy(draft.line)} closed={closed} />);
  const readingForm = (closed: boolean) => <ReadingForm chain={chain} draft={draft} save={readingSave} closed={closed} />;
  if (chain.history.state === "invalid" || chain.state !== "available") {
    return (
      <>
        {chain.history.state === "invalid"
          ? <p className="ec-invalid" role="alert" data-history="invalid">This chain's saved records cannot be verified: {chain.history.problem}</p>
          : <p className="ec-none" data-forms="closed">New reviews and readings are not accepted while the chain is{" "}
            {CHAIN_STATE[chain.state].toLowerCase()}{chain.reasons.length > 0 ? `: ${chain.reasons[0]}` : ""}.</p>}
        {keepReview && reviewForm(true)}
        {keepReading && readingForm(true)}
      </>
    );
  }
  const approval = chain.approval.state;
  // A typed reading keeps its form (and its leave guard) even if a reload ends the approval it was written under.
  return (
    <>
      {reviewForm(false)}
      {approval === "approved" || keepReading ? readingForm(false)
        : <p className="ec-none" data-forms="reading-closed">{approval === "needs_revision"
          ? "A reading can be written once you approve a version of this chain; your latest review asks for a revision."
          : approval === "approved_earlier_basis"
            ? "A reading can be written once you approve this basis; your approval is on an earlier one."
            : "A reading can be written once you approve this version of the chain."}</p>}
    </>
  );
}

function History({ chain }: { chain: ChainView }) {
  const history = chain.history;
  return (
    <>
      <p className="ec-note" data-note="source-wording">{SOURCE_WORDING_NOTE}</p>
      <h4>Versions</h4>
      <ol className="ec-versions">{history.versions.map((raw) => {
        const version = raw as { version: number; published_on: string; title: string; change: unknown;
          state: string; passages: { ref: string; where: string; quote: string | null; state: string }[] };
        const answered = reviewNoteSentence(version.change);
        return (
          <li key={version.version} data-version={version.version} data-version-state={version.state}>
            <strong>Version {version.version}</strong>, published {version.published_on}
            {version.state === "latest" ? " (latest)" : ""}: {version.title}
            {text(record(version.change)?.note) !== null && <p className="ec-change">Change: {text(record(version.change)?.note)}</p>}
            {answered !== null && <p className="ec-review-note" data-review-note="">{answered}</p>}
            <details><summary>Passages pinned in this version</summary>
              <ul>{version.passages.map((passage) => (
                <li key={passage.ref}>{passage.quote !== null ? <Quote words={passage.quote} where={passage.where} />
                  : <span className="ec-withheld">{passage.ref}: quote withheld ({passage.state}).</span>}</li>))}</ul>
            </details>
          </li>);
      })}</ol>
      <h4>Your reviews</h4>
      {history.reviews.length === 0 ? <p className="ec-none">No review is saved.</p> : (
        <ol className="ec-records" data-records="reviews">{history.reviews.map((item) => (
          <li key={item.review_id} data-review-state={item.state}>
            <p><strong>{REVIEW_STATE[item.state]}</strong>, <Signed account={item.account} at={item.saved_at} /></p>
            {item.notes !== "" && <p className="ec-own-text" dir="auto">{item.notes}</p>}
            <Basis item={item} />
          </li>))}</ol>)}
      <h4>Your readings</h4>
      {history.readings.length === 0 ? <p className="ec-none">No reading is saved.</p> : (
        <ol className="ec-records" data-records="readings">{history.readings.map((item) => (
          <li key={item.reading_id} data-reading-state={item.state}>
            <p><strong>{READING_STATE[item.state]}</strong>, <Signed account={item.account} at={item.saved_at} /></p>
            <p>{SHORT_TERM}: {JUDGMENT_LABEL[item.short_term]}. {LONG_TERM}: {JUDGMENT_LABEL[item.long_term]}.</p>
            <p className="ec-own-text" dir="auto">{item.line}</p>
            <Basis item={item} />
          </li>))}</ol>)}
    </>
  );
}

function Measured({ chain }: { chain: ChainView }) {
  const target = chain.target;
  const measure = record(target.measure);
  const figure = (value: unknown) => {
    const one = record(value);
    return one === null ? null : [text(one.as_shown), text(one.unit), text(one.year) === null ? null : `(${text(one.year)})`]
      .filter((item) => item !== null).join(" ");
  };
  const latest = measure === null ? null : figure(measure.latest);
  const previous = measure === null ? null : figure(measure.previous);
  const price = chain.measured.price as Record<string, unknown>;
  const series = record(price.series);
  const changes = Array.isArray(price.changes) ? price.changes as { year: number; change_pct: string }[] : [];
  const context = Array.isArray(price.context) ? price.context as { from: number; to: number; change_pct: string }[] : [];
  return (
    <>
      <p className="ec-note" data-measured="target-note">{chain.measured.target_note}</p>
      {latest !== null && (
        <p data-measured="target">{previous !== null ? <>Now {latest}, against {previous}</> : <>Now {latest}</>}
          {text(target.change_pct) !== null && <>; change {target.change_pct as string}%</>}.</p>)}
      <h4>What the price did after</h4>
      <p data-measured="price" data-price-state={String(price.state)}>
        {series !== null && text(series.label) !== null && <span className="ec-series">{text(series.label)}. </span>}
        {price.state === "measured"
          ? <>{priceChanges(Number(price.event_year), changes).map((line) => <span key={line} className="ec-change-line">{line}</span>)}</>
          : price.state === "withheld" ? `Withheld: ${String(price.problem)}` : String(price.text)}</p>
      <p data-measured="short-term">{String(price.short_term)}</p>
      {context.length > 0 && price.state !== "withheld" && (
        <details><summary>Earlier year-to-year changes, not tied to this event</summary>
          <ul>{priceContext(context).map((line) => <li key={line}>{line}</li>)}</ul>
        </details>)}
    </>
  );
}

/** One chain: the seven parts of the page in order, each in its own voice. */
export function EventChainCard({ chain, onReload }: { chain: ChainView; onReload: () => void }) {
  const stated = chain.steps.map((step, index) => ({ step, number: index + 1 }))
    .filter((item): item is { step: Extract<Step, { kind: "stated" }>; number: number } => item.step.kind === "stated");
  const notStated = chain.steps.map((step, index) => ({ step, number: index + 1 }))
    .filter((item): item is { step: Extract<Step, { kind: "not_stated" }>; number: number } => item.step.kind === "not_stated");
  const mechanisms = chain.steps.map((step, index) => ({ step, number: index + 1 }))
    .filter((item): item is { step: Extract<Step, { kind: "mechanism" }>; number: number } => item.step.kind === "mechanism");
  const approvedOn = mechanismMark(chain.approval);
  const statement = record(chain.target.statement);
  return (
    <article className="ec-card" data-chain={chain.id} data-chain-state={chain.state}>
      <header>
        <h2>{chain.title}</h2>
        <p className="ec-meta">Version {chain.latest_version}, published {chain.published_on}. State: <strong>{CHAIN_STATE[chain.state]}</strong>.</p>
        {chain.reasons.length > 0 && <ul className="ec-reasons">{chain.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>}
      </header>

      <Part id="source" title="The source says">
        <div className="ec-event" data-event-state={chain.event.state}>
          {eventLines(chain.event as { state: string; pinned: unknown; current: unknown }).map((line) => (
            <p key={line.label ?? line.text} data-event-line={line.label ?? "note"}>
              {line.label !== null && <strong>{line.label}: </strong>}{line.text}</p>))}
        </div>
        <div className="ec-steps">{stated.map(({ step, number }, at) => (
          <div key={number} className="ec-step-item">
            {at > 0 && <Joined>{STEP_JOIN}</Joined>}
            <StatedStep step={step} number={number} />
          </div>))}</div>
      </Part>

      <Part id="not-stated" title="Not stated by any retained source">
        {notStated.length === 0 ? <p className="ec-none">Every step above is stated by a retained source.</p>
          : <ul>{notStated.map(({ step, number }) => (
            <li key={number} data-step={number}><span className="ec-step-no">Step {number}</span> {step.text}</li>))}</ul>}
      </Part>

      <Part id="mechanism" title="A conditional mechanism">
        {mechanisms.map(({ step, number }) => (
          <div key={step.id} className="ec-mechanism" data-step={number}>
            <Joined>{STEP_JOIN}</Joined>
            <p><span className="ec-step-no">Step {number}</span> {step.text}</p>
            <p className="ec-mark" data-mark="mechanism">General economics, not stated by any source about this event.
              Drafted by the assistant; {approvedOn}</p>
          </div>))}
      </Part>

      <Part id="bears-on" title="Bears on">
        <p data-target-kind={chain.target.kind}><strong>The thesis {String(chain.target.kind)}:</strong>{" "}
          {text(chain.target.title) ?? String(chain.target.id)}</p>
        {statement !== null && text(statement.text) !== null && <p className="ec-statement">{text(statement.text)}</p>}
        {statement === null && <p className="ec-withheld">The thesis element is {String(chain.target.state)}.</p>}
      </Part>

      <Part id="measured" title="Measured"><Measured chain={chain} /></Part>

      <Part id="reading" title="My reading">
        {chain.history.state === "valid" && <><Reading chain={chain} /><Review chain={chain} /></>}
        <Forms chain={chain} onReload={onReload} />
      </Part>

      <Part id="history" title="History">
        {chain.history.state === "invalid"
          ? <p className="ec-none">The history is not shown while the saved records cannot be verified.</p>
          : <History chain={chain} />}
      </Part>
    </article>
  );
}
