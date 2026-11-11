import { useEffect, useRef, useState } from "react";
import { MAX_NOTES, REVIEW_STATUSES, type Analysis, type ReviewStatus } from "../../contracts/user.ts";
import { useClient, useUnsaved, zoneOf } from "../context";
import { outcomeOf } from "../controller.ts";
import { REVIEW_LABEL, NO_REVIEW, reviewLabel } from "../present.ts";
import { reviewKey, reviewRestore, type ReviewDraft } from "../recovery.ts";
import type { Notice } from "../refusals.ts";
import {
  draftProblems, isCurrent, isDirty, latestReview, reviewForm, startingDraft, type Draft,
} from "../reviewDraft.ts";
import { inZone } from "../time.ts";
import { NoticeView } from "./NoticeView";

/** Your own review of this result: versions are kept, each bound to the result it was saved against. A label records
 * your judgment; it does not verify, freeze or score the analysis. Notes typed when the session ended come back here
 * for the same user, after the analysis has been read again, and only for the same result; they still follow the
 * version they were written after, so a version saved since is refused as a conflict. Saving is always explicit. */
export function ReviewEditor({ analysis, onSaved, onReload }: {
  analysis: Analysis; onSaved: (analysis: Analysis) => void; onReload: () => void;
}) {
  const { api, account, endSession, recovered, releaseRecovered } = useClient();
  const key = reviewKey(analysis.analysis_id);
  const [draft, setDraft] = useState<Draft>(() => startingDraft(analysis));
  /** The version restored notes were written after, until the person reads the analysis again or saves. */
  const [base, setBase] = useState<string | null | undefined>(undefined);
  const [restored, setRestored] = useState(false);
  /** Notes written for an earlier result: shown to copy, never put into the editor or saved against this result. */
  const [stale, setStale] = useState<ReviewDraft | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<number | null>(null);
  const acting = useRef(false);
  const zone = zoneOf(account);
  const dirty = isDirty(analysis, draft);
  const waiting = [recovered[key], recovered[`${key}:stale`]].find((item): item is ReviewDraft =>
    item?.kind === "review") ?? null;
  const fits = waiting !== null && reviewRestore(waiting, analysis) === "restore";

  const release = () => {
    releaseRecovered(key);
    releaseRecovered(`${key}:stale`);
  };
  const putBack = () => {
    if (!waiting) return;
    setDraft({ status: waiting.status, notes: waiting.notes });
    setBase(waiting.base);
    setRestored(true);
    setNotice(null);
    release();
  };
  useEffect(() => {  // Only with this analysis as just read from the server, and never over notes typed since.
    if (!waiting) return;
    if (!fits) {
      setStale(waiting);
      release();
    } else if (!dirty) putBack();
  }, [waiting, analysis.result_sha256]);

  useUnsaved(key, dirty && analysis.result_sha256 ? { kind: "review", analysisId: analysis.analysis_id,
    headline: analysis.source.headline, resultSha256: analysis.result_sha256,
    base: base === undefined ? latestReview(analysis)?.review_id ?? null : base, status: draft.status,
    notes: draft.notes } : null);
  useUnsaved(`${key}:stale`, stale);
  const problems = draftProblems(analysis, draft);
  const characters = Array.from(draft.notes).length;

  const readAgain = () => {
    setBase(undefined);  // Read again: from now on the editor follows the versions shown.
    onReload();
  };
  const save = async () => {
    if (acting.current || problems.length > 0) return;
    acting.current = true;
    setBusy(true);
    setNotice(null);
    const outcome = outcomeOf(await api.review(analysis.analysis_id, reviewForm(analysis, draft, base)), null, zone);
    acting.current = false;
    setBusy(false);
    if (outcome.kind === "ok") {
      setSaved(outcome.data.review.sequence);
      setBase(undefined);
      setRestored(false);
      onSaved(outcome.data.analysis);  // The editor is keyed by the result, so the draft stays as saved.
    } else if (outcome.kind === "session") endSession(outcome.reason);
    else setNotice(outcome.notice);  // The draft is kept as typed.
  };

  return (
    <section className="card client-card client-review" aria-labelledby="review-title">
      <h2 id="review-title">Your review</h2>
      <p className="card-note">Your judgment of this result, saved as a new version each time. It does not change the
        analysis.</p>
      {restored && dirty && (
        <p className="client-note" role="status" data-recovered="review">Your unsaved review is back as you left it
          when your session ended, for this same result. It is not saved: check it and save it yourself.</p>
      )}
      {waiting && fits && dirty && (
        <div className="client-notice is-unconfirmed" data-recovered="waiting">
          <p>The review you were writing when your session ended is waiting.</p>
          <p className="client-actions">
            <button type="button" className="button button-quiet" onClick={putBack}>Put it back (replaces these notes)</button>
            <button type="button" className="client-link-button" onClick={release}>Discard it</button>
          </p>
        </div>
      )}
      {stale && (
        <div className="client-notice is-unconfirmed" data-recovered="stale">
          <p className="client-notice-title">Your unsaved review was for an earlier result</p>
          <p>The result has changed since you wrote it, so it is not put back into the editor and cannot be saved
            against this result. Copy it if you need it.</p>
          <p className="client-sub">{reviewLabel(stale.status)}</p>
          <textarea className="client-ended-text" readOnly value={stale.notes} aria-label="Your notes for the earlier result" />
          <p className="client-actions">
            <button type="button" className="button button-quiet" onClick={() => setStale(null)}>Discard them</button></p>
        </div>
      )}
      <fieldset className="client-review-status" disabled={busy}>
        <legend>Status</legend>
        {[null, ...REVIEW_STATUSES].map((status: ReviewStatus | null) => (
          <label key={status ?? "none"}>
            <input type="radio" name="review-status" value={status ?? "none"} checked={draft.status === status}
                   onChange={() => setDraft((current) => ({ ...current, status }))} />
            {status ? REVIEW_LABEL[status] : NO_REVIEW}
          </label>
        ))}
      </fieldset>
      <label className="client-review-notes">Notes
        <textarea rows={6} value={draft.notes} disabled={busy}
                  onChange={(event) => setDraft((current) => ({ ...current, notes: event.target.value }))} />
        <span className={`client-sub${characters > MAX_NOTES ? " is-over" : ""}`}>
          {characters.toLocaleString("en-US")} of {MAX_NOTES.toLocaleString("en-US")} characters</span>
      </label>
      {dirty && problems.length > 0 && <ul className="client-problems">{problems.map((text) => <li key={text}>{text}</li>)}</ul>}
      {notice && <NoticeView notice={notice} onReadAgain={readAgain} busy={busy} />}
      {saved !== null && !dirty && <p className="client-note" role="status">Version {saved} was saved.</p>}
      <p className="client-actions">
        <button type="button" className="button client-save-review" disabled={busy || !dirty || problems.length > 0}
                onClick={() => void save()}>{busy ? "Saving…" : "Save a review version"}</button>
      </p>
      {analysis.reviews.length > 0 && (
        <ol className="client-versions" reversed>
          {[...analysis.reviews].reverse().map((review) => (
            <li key={review.review_id} data-version={review.sequence}>
              <p className="client-version-head">Version {review.sequence} · {reviewLabel(review.status)} ·{" "}
                {inZone(review.saved_at, zone)} · {review.reviewer.display_name}
                {!isCurrent(review, analysis) && " · saved against an earlier result"}</p>
              {review.notes && <p className="client-version-notes">{review.notes}</p>}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
