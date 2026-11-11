import { useEffect, useRef, useState } from "react";
import { fetchReviews, saveReview, type Loaded, type SaveResult } from "../api";
import type { DraftReviewView, ReviewHistory, ReviewPayload, ReviewRecord, ReviewStatus } from "../draftTypes";
import { formatUtc, shortHash } from "../format";
import {
  ATTRIBUTION_LABEL, STATUS_NOTE, appendSaved, correctionCount, correctionRows, currentReview, formFrom,
  formProblems, historyUpTo, isDirty, isEmptyReview, latestReview, payloadFrom, reconcile, savedAgainst, statusLabel,
  type Reconciled, type ReviewForm,
} from "../review";

interface Props {
  view: DraftReviewView;
  /** The fingerprint the server sent with `view`; saves are bound to it. */
  fingerprint: string;
  history: Loaded<ReviewHistory>;
  /** Load the draft and its saved versions again, discarding unsaved edits. */
  onReload: () => void;
  onDirtyChange: (dirty: boolean) => void;
}

/** What the last save, or the check of a save, established. */
type Notice = SaveResult | Exclude<Reconciled, { state: "saved" | "conflict" }>;

const UNMATCHED = "The server's reply does not match the version that was sent.";

/**
 * The reviewer's own record of one draft: a judgment, notes and, for a model draft only, corrections. Each
 * save appends a version on this computer; the model's proposal shown above is never changed. The form is set
 * from the saved versions only when they load: a save or a check never replaces what is being typed.
 */
export function HumanReview({ view, fingerprint, history, onReload, onDirtyChange }: Props) {
  const [saved, setSaved] = useState<ReviewHistory | null>(null);
  const [form, setForm] = useState<ReviewForm | null>(null);
  const [busy, setBusy] = useState<"saving" | "checking" | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [unconfirmed, setUnconfirmed] = useState<ReviewPayload | null>(null);
  const checking = useRef<AbortController | null>(null);
  const latest = saved ? latestReview(saved) : null;
  const current = saved ? currentReview(saved, fingerprint) : null;

  useEffect(() => {
    if (history.state !== "ready") return;
    setSaved(history.data);
    setForm(formFrom(view, currentReview(history.data, fingerprint)));
  }, [history, view, fingerprint]);

  const dirty = form !== null && isDirty(view, form, current);
  useEffect(() => {
    onDirtyChange(dirty);
    return () => onDirtyChange(false);
  }, [dirty, onDirtyChange]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  useEffect(() => () => checking.current?.abort(), []);

  if (form === null || saved === null) {
    if (history.state === "loading") return <p className="draft-state" role="status">Loading saved review versions…</p>;
    return (
      <div className="draft-state" role="alert">
        <p>Saved review versions could not be loaded, so nothing can be saved. {"message" in history ? history.message : ""}</p>
        <button type="button" className="button" onClick={onReload}>Try again</button>
      </div>
    );
  }

  const viewChanged = saved.draft_view_sha256 !== fingerprint;
  const problems = formProblems(view, form);
  const payload = payloadFrom(view, fingerprint, form, latest);
  const canSave = dirty && problems.length === 0 && !isEmptyReview(payload) && busy === null &&
    unconfirmed === null && !viewChanged;
  // Functional updates, so edits made while a save or check is pending are never lost. Editing clears the last
  // message, except an unconfirmed save, which stays until the saved versions are checked.
  const edit = (change: (before: ReviewForm) => ReviewForm) => {
    setForm((before) => before && change(before));
    setNotice((before) => (before?.state === "unconfirmed" ? before : null));
  };
  const update = (change: Partial<ReviewForm>) => edit((before) => ({ ...before, ...change }));
  const updateLeg = (legId: string, change: Partial<ReviewForm["legs"][string]>) =>
    edit((before) => ({ ...before, legs: { ...before.legs, [legId]: { ...before.legs[legId], ...change } } }));

  const save = async () => {
    const sent = payload;
    setBusy("saving");
    setNotice(null);
    const outcome = await saveReview(view.id, sent);
    if (outcome.state === "saved") {
      const next = appendSaved(saved, sent, outcome.record);
      if (next) setSaved(next);
      else setUnconfirmed(sent);
      setNotice(next ? outcome : { state: "unconfirmed", message: UNMATCHED });
    } else {
      if (outcome.state === "unconfirmed") setUnconfirmed(sent);
      setNotice(outcome);
    }
    setBusy(null);
  };

  // Reads the saved versions to learn what became of an unconfirmed save; it never sends the save again.
  const check = async () => {
    if (unconfirmed === null) return;
    const controller = new AbortController();
    checking.current = controller;
    setBusy("checking");
    let loaded: Loaded<ReviewHistory>;
    try {
      loaded = await fetchReviews(view.id, controller.signal);
    } catch {
      return;  // Left the draft while checking.
    }
    if (loaded.state !== "ready") {
      const reason = "message" in loaded ? loaded.message : "";
      setNotice({ state: "unconfirmed", message: `The saved versions could not be read. ${reason}` });
    } else {
      const found = reconcile(loaded.data, unconfirmed);
      setUnconfirmed(null);
      if (found.state === "conflict") {
        setNotice({ state: "conflict", message: found.message });
      } else if (found.state === "superseded") {
        // Saved, but not the latest: the page takes in the versions up to its own and leaves the newer ones to
        // an explicit reload, so nothing is merged and a save from here is refused as a conflict.
        setSaved(historyUpTo(loaded.data, found.record));
        setNotice(found);
      } else {
        setSaved(loaded.data);
        setNotice(found.state === "saved" ? { state: "saved", record: found.record } : found);
      }
    }
    setBusy(null);
  };

  const saveState = busy === "saving" ? "Saving… edits you make now are kept for the next version"
    : dirty ? "Unsaved changes"
    : current ? `All changes saved · version ${current.sequence}`
    : latest ? "Nothing saved for this view yet" : "Nothing saved yet";

  return (
    <section className="human-review" aria-labelledby="human-review-title">
      <h4 id="human-review-title">Your review</h4>
      <p className="draft-note">
        Each save is kept on this computer as a new version; earlier versions are never changed. Your review is
        stored apart from the model's proposal above and never alters it, and nothing here freezes, evaluates or
        approves the draft.
      </p>
      {viewChanged && (
        <div className="review-message is-failed" role="alert">
          <p>
            <strong>The prepared draft has changed since this page loaded it.</strong> A review of what is shown
            here can no longer be saved.
          </p>
          <button type="button" className="button" onClick={onReload}>Reload the draft (discards these edits)</button>
        </div>
      )}
      {latest && !savedAgainst(latest, fingerprint) && (
        <p className="review-earlier" role="note">
          Your latest saved version was made against an earlier prepared view of this draft. Its judgment and
          corrections are listed under Saved versions but are not applied here; this form starts from the model's
          proposal as it is prepared now.
        </p>
      )}

      <fieldset className="review-status">
        <legend>Your judgment</legend>
        {([null, "needs_revision", "human_reviewed"] as (ReviewStatus | null)[]).map((status) => (
          <label key={status ?? "none"} className="review-choice">
            <input type="radio" name={`review-status-${view.id}`} checked={form.status === status}
                   onChange={() => update({ status })} />
            {statusLabel(status)}
          </label>
        ))}
        <p className="draft-note">{STATUS_NOTE}</p>
      </fieldset>

      <label className="review-field">
        <span>Review notes</span>
        <textarea rows={4} value={form.notes} onChange={(event) => update({ notes: event.target.value })} />
      </label>

      {view.draft ? (
        <fieldset className="review-corrections">
          <legend>Your corrections (optional)</legend>
          <p className="draft-note">
            Edit only what you would correct. The map, observables, directions, horizons and primary leg cannot be
            changed here. Saved corrections are attributed to you and shown beside the model's original.
          </p>
          <label className="review-field">
            <span>Summary {form.summary.trim() !== view.draft.summary && <em className="review-changed">changed from the model</em>}</span>
            <textarea rows={4} value={form.summary} onChange={(event) => update({ summary: event.target.value })} />
          </label>
          {view.draft.legs.map((leg) => {
            const edited = form.legs[leg.id];
            const node = view.draft!.nodes.find((item) => item.id === leg.node_id)?.label ?? leg.node_id;
            return (
              <div key={leg.id} className="review-leg">
                <p className="review-leg-title">{leg.primary ? "Primary" : "Secondary"} leg · {node}</p>
                <label className="review-field">
                  <span>Reasoning {edited.rationale.trim() !== leg.rationale && <em className="review-changed">changed from the model</em>}</span>
                  <textarea rows={3} value={edited.rationale}
                            onChange={(event) => updateLeg(leg.id, { rationale: event.target.value })} />
                </label>
                <label className="review-field">
                  <span>Falsifier {edited.falsifier.trim() !== leg.falsifier && <em className="review-changed">changed from the model</em>}</span>
                  <textarea rows={2} value={edited.falsifier}
                            onChange={(event) => updateLeg(leg.id, { falsifier: event.target.value })} />
                </label>
                <label className="review-choice">
                  <input type="checkbox" checked={edited.headline_reports_move}
                         onChange={(event) => updateLeg(leg.id, { headline_reports_move: event.target.checked })} />
                  The source already reports this move (headline_reports_move)
                  {edited.headline_reports_move !== leg.headline_reports_move && <em className="review-changed">changed from the model</em>}
                </label>
              </div>
            );
          })}
        </fieldset>
      ) : (
        <p className="draft-note">
          This attempt has no model draft, so you can save notes and a judgment only. Nothing here creates a draft.
        </p>
      )}

      {problems.length > 0 && (
        <ul className="review-problems" aria-live="polite">{problems.map((problem) => <li key={problem}>{problem}</li>)}</ul>
      )}
      <div className="review-save-bar">
        <span className={`review-dirty${dirty ? " is-dirty" : ""}`} role="status">{saveState}</span>
        <button type="button" className="button" disabled={!canSave} onClick={save}>
          {busy === "saving" ? "Saving…" : "Save as a new version"}
        </button>
      </div>
      <SaveMessage notice={notice} dirty={dirty} checking={busy === "checking"} onCheck={check} onReload={onReload} />

      {current && <SavedCorrections view={view} record={current} />}
      {saved.reviews.length > 0 && <VersionHistory history={saved} fingerprint={fingerprint} />}
    </section>
  );
}

function SaveMessage({ notice, dirty, checking, onCheck, onReload }: {
  notice: Notice | null;
  dirty: boolean;
  checking: boolean;
  onCheck: () => void;
  onReload: () => void;
}) {
  if (notice === null) return null;
  if (notice.state === "saved") {
    return (
      <p className="review-message is-saved" role="status">
        Saved version {notice.record.sequence} at {formatUtc(notice.record.saved_at)}.
        {dirty && " Changes made since are not in it and are not saved yet."}
      </p>
    );
  }
  if (notice.state === "not-saved") {
    return (
      <p className="review-message is-failed" role="status">
        <strong>Not saved.</strong> The saved versions show that this save was not recorded. Your edits are kept;
        you can save them again.
      </p>
    );
  }
  if (notice.state === "superseded") {
    return (
      <div className="review-message is-superseded" role="alert">
        <p>
          <strong>Saved, but no longer the latest.</strong> Your save was recorded as version {notice.record.sequence}
          {" "}at {formatUtc(notice.record.saved_at)}. A newer version {notice.latest.sequence} has been saved since,
          so this page does not show the latest review and a save from here would be refused.
          {dirty && " Edits made after your save are kept on this page but are not saved."}
        </p>
        <button type="button" className="button" onClick={onReload}>
          Reload the draft and its saved versions (discards edits on this page)
        </button>
      </div>
    );
  }
  if (notice.state === "unconfirmed") {
    return (
      <div className="review-message is-unconfirmed" role="alert">
        <p>
          <strong>Not confirmed.</strong> {notice.message} This version may or may not have been saved. Your edits
          are kept, and nothing is sent again automatically. Check the saved versions before saving again.
        </p>
        <button type="button" className="button" disabled={checking} onClick={onCheck}>
          {checking ? "Checking…" : "Check the saved versions"}
        </button>
      </div>
    );
  }
  return (
    <div className="review-message is-failed" role="alert">
      <p><strong>Not saved.</strong> {notice.message}</p>
      {notice.state === "conflict" && (
        <button type="button" className="button" onClick={onReload}>
          Reload the draft and its saved versions (discards these edits)
        </button>
      )}
    </div>
  );
}

function SavedCorrections({ view, record }: { view: DraftReviewView; record: ReviewRecord }) {
  const rows = correctionRows(view, record);
  if (rows.length === 0) return null;
  return (
    <section className="saved-corrections" aria-labelledby="saved-corrections-title">
      <h5 id="saved-corrections-title">Saved corrections</h5>
      <p className="draft-note">
        By {ATTRIBUTION_LABEL.toLowerCase()} · version {record.sequence}, saved {formatUtc(record.saved_at)}. The
        model's original stays as it was.
      </p>
      <dl className="correction-list">
        {rows.map((row) => (
          <div key={row.field}>
            <dt>{row.field}</dt>
            <dd>
              <span className="correction-original"><span className="correction-label">Model's original</span>{row.original}</span>
              <span className="correction-human"><span className="correction-label">Your correction</span>{row.corrected}</span>
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function VersionHistory({ history, fingerprint }: { history: ReviewHistory; fingerprint: string }) {
  return (
    <details className="draft-provenance review-history">
      <summary>Saved versions ({history.reviews.length})</summary>
      <ol reversed>
        {[...history.reviews].reverse().map((record) => (
          <li key={record.review_id}>
            <p>
              <strong>Version {record.sequence}</strong> · {formatUtc(record.saved_at)} · {statusLabel(record.status)} ·{" "}
              {correctionCount(record.corrections)} correction{correctionCount(record.corrections) === 1 ? "" : "s"}
              {record.parent_review_id ? ` · follows version ${record.sequence - 1}` : " · first version"}
            </p>
            {!savedAgainst(record, fingerprint) && (
              <p className="review-earlier-tag">Saved against an earlier prepared view; not applied to this one.</p>
            )}
            {record.notes.trim() && <p className="draft-plain review-history-notes">{record.notes}</p>}
            <p className="draft-note">
              Review <code className="draft-wrap">{shortHash(record.review_id, 12)}</code> · bound to prompt hash{" "}
              <code className="draft-wrap">{shortHash(record.binding.prompt_hash, 12)}</code> and prepared view{" "}
              <code className="draft-wrap">{shortHash(record.binding.draft_view_sha256, 12)}</code>
            </p>
          </li>
        ))}
      </ol>
    </details>
  );
}
