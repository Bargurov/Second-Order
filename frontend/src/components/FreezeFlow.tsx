import { useEffect, useRef, useState } from "react";
import { useLoad, type Loaded } from "../api";
import { formatUtc } from "../format";
import {
  EXPLICIT_TIME, H15_OBSERVABLES, OBSERVABLE_LABEL, approveFreeze, checkAction, emptyManual, fetchBaselines,
  fetchFreezableDrafts, hypothesisHref, importBaseline, manualPayload, previewFreeze, providerName, upgradeStore,
  type ActionState, type BaselineSummary, type Baselines, type Drafts, type Frozen, type Inputs, type ManualForm,
  type ManualLeg, type Preview, type StoreState,
} from "../lifecycle";
import { Link } from "../router";
import { BaselineCard, EffectiveContent, FreshnessList, ScoringNote } from "./FrozenParts";

type Outcome =
  | { state: "idle" }
  | { state: "pending" }
  | { state: "frozen"; result: Frozen }
  | { state: "refused"; message: string }
  | { state: "unconfirmed"; message: string; actionId: string }
  | { state: "checked"; result: ActionState };

/**
 * One deliberate path to one freeze: choose what to freeze, choose (or explicitly import) a baseline, preview, then
 * approve that exact preview. Changing anything clears the preview; the server stamps the time; a lost reply is
 * resolved by reading the outcome, never by sending the approval again.
 */
export function FreezeFlow({ store, onFrozen, onStoreChanged }: {
  store: StoreState;
  onFrozen: () => void;
  onStoreChanged: () => void;
}) {
  const [origin, setOrigin] = useState<"manual" | "model">("manual");
  const [form, setForm] = useState<ManualForm>(emptyManual);
  const [draftId, setDraftId] = useState<string | null>(null);
  const [baselineId, setBaselineId] = useState<string | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewProblem, setPreviewProblem] = useState<string | null>(null);
  const [approved, setApproved] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>({ state: "idle" });
  const [reload, setReload] = useState(0);
  const [drafts, retryDrafts] = useLoad(fetchFreezableDrafts, `drafts:${reload}`);
  const [baselines, retryBaselines] = useLoad(fetchBaselines, `baselines:${reload}`);
  const inflight = useRef(false);

  const built = origin === "manual" ? manualPayload(form) : { payload: null, missing: draftId ? [] : ["a reviewed draft"] };
  const inputs: Inputs | null = baselineId && (origin === "model" ? draftId : built.payload)
    ? { origin, manual: origin === "manual" ? built.payload : null, draft_id: origin === "model" ? draftId : null,
        baseline_snapshot_id: baselineId }
    : null;
  const key = JSON.stringify(inputs);
  useEffect(() => {  // Any change to what would be frozen voids the preview and the approval.
    setPreview(null);
    setApproved(false);
    setPreviewProblem(null);
    if (outcome.state !== "frozen" && outcome.state !== "checked") setOutcome({ state: "idle" });
  }, [key]);  // eslint-disable-line react-hooks/exhaustive-deps

  const runPreview = async () => {
    if (!inputs) return;
    setPreviewing(true);
    setPreviewProblem(null);
    const result = await previewFreeze(inputs);
    setPreviewing(false);
    if (result.state === "done") setPreview(result.data);
    else setPreviewProblem(result.message);
  };

  const freeze = async () => {
    if (!inputs || !preview || !approved || inflight.current) return;
    inflight.current = true;  // One request at a time from this page; a second click does nothing.
    setOutcome({ state: "pending" });
    const result = await approveFreeze(inputs, preview);
    inflight.current = false;
    if (result.state === "done") {
      setOutcome({ state: "frozen", result: result.data });
      onFrozen();
    } else if (result.state === "refused") {
      if (result.preview) {
        setPreview(result.preview);  // The server's current preview, to review and approve again (or not).
        setApproved(false);
      }
      setOutcome({ state: "refused", message: result.message });
    } else {
      setOutcome({ state: "unconfirmed", message: result.message, actionId: preview.preview_sha256 });
    }
  };

  const check = async (actionId: string) => {
    const result = await checkAction(actionId, new AbortController().signal);
    if (result.state === "ready") {
      setOutcome({ state: "checked", result: result.data });
      if (result.data.state === "frozen") onFrozen();
    } else {
      setOutcome({ state: "unconfirmed", actionId, message: "message" in result ? result.message : "Not checked." });
    }
  };

  return (
    <div className="freeze-flow">
      <section className="freeze-step" aria-labelledby="freeze-step-1">
        <h3 id="freeze-step-1"><span>1</span> What to freeze</h3>
        <fieldset className="freeze-choice">
          <legend>Origin</legend>
          <label><input type="radio" name="freeze-origin" checked={origin === "manual"}
                        onChange={() => setOrigin("manual")} /> A manual hypothesis on the H.15 observables</label>
          <label><input type="radio" name="freeze-origin" checked={origin === "model"}
                        onChange={() => setOrigin("model")} /> A reviewed model draft</label>
        </fieldset>
        {origin === "manual" ? <ManualFields form={form} onChange={setForm} missing={built.missing} />
          : <DraftChoice drafts={drafts} chosen={draftId} onChoose={setDraftId} onRetry={retryDrafts} />}
      </section>

      <section className="freeze-step" aria-labelledby="freeze-step-2">
        <h3 id="freeze-step-2"><span>2</span> Baseline</h3>
        <StoreNotice store={store} onUpgraded={() => { onStoreChanged(); setReload((value) => value + 1); }} />
        <BaselineChoice baselines={baselines} chosen={baselineId} onChoose={setBaselineId} onRetry={retryBaselines}
                        onImported={(id) => { setBaselineId(id); onStoreChanged(); setReload((value) => value + 1); }} />
      </section>

      <section className="freeze-step" aria-labelledby="freeze-step-3">
        <h3 id="freeze-step-3"><span>3</span> Preview</h3>
        <p className="freeze-note">A preview writes nothing and contacts no provider. It shows exactly what an approval
          would freeze.</p>
        <button type="button" className="button freeze-preview-button" disabled={!inputs || previewing}
                onClick={runPreview}>{previewing ? "Previewing…" : "Preview the freeze"}</button>
        {!inputs && <p className="freeze-note">Complete step 1 and choose a baseline to preview.</p>}
        {previewProblem && <p className="freeze-problem" role="alert">{previewProblem}</p>}
        {preview && <PreviewPanel preview={preview} />}
      </section>

      <section className="freeze-step" aria-labelledby="freeze-step-4">
        <h3 id="freeze-step-4"><span>4</span> Approve one freeze</h3>
        {preview && !preview.freezable && (
          <p className="freeze-problem" role="alert">This preview cannot be frozen: {preview.blockers.join(" ")}</p>
        )}
        <label className="freeze-confirm">
          <input type="checkbox" checked={approved} disabled={!preview?.freezable || outcome.state === "frozen"}
                 onChange={(event) => setApproved(event.target.checked)} />
          <span>I approve freezing exactly this previewed hypothesis with this baseline. The server stamps the freeze
            time; the record can never be edited, restamped or frozen again.</span>
        </label>
        <button type="button" className="button button-freeze"
                disabled={!preview?.freezable || !approved || outcome.state === "pending" || outcome.state === "frozen"}
                onClick={freeze}>{outcome.state === "pending" ? "Freezing…" : "Freeze"}</button>
        <OutcomePanel outcome={outcome} onCheck={check} />
      </section>
    </div>
  );
}

function ManualFields({ form, onChange, missing }: {
  form: ManualForm; onChange: (form: ManualForm) => void; missing: string[];
}) {
  const set = (field: keyof ManualForm, value: string) => onChange({ ...form, [field]: value });
  const setLeg = (index: number, field: keyof ManualLeg, value: string) =>
    onChange({ ...form, legs: form.legs.map((leg, i) => (i === index ? { ...leg, [field]: value } : leg)) });
  const time = form.published_at.trim();
  return (
    <div className="freeze-form">
      <label><span>Headline</span>
        <input name="headline" value={form.headline} onChange={(e) => set("headline", e.target.value)} /></label>
      <label><span>Source URL</span>
        <input name="source_url" value={form.source_url} inputMode="url"
               onChange={(e) => set("source_url", e.target.value)} /></label>
      <label><span>Publication time, with its UTC offset</span>
        <input name="published_at" value={form.published_at} placeholder="2026-10-13T08:30:00-04:00" spellCheck={false}
               aria-invalid={time !== "" && !EXPLICIT_TIME.test(time)} onChange={(e) => set("published_at", e.target.value)} />
        <small>As the source states it. A source that gives only a date cannot be frozen here without inventing a
          time, so it is not supported.</small></label>
      <label><span>Story ID</span>
        <input name="story_id" value={form.story_id} spellCheck={false}
               onChange={(e) => set("story_id", e.target.value)} /></label>
      <label className="freeze-wide"><span>Summary</span>
        <textarea name="summary" rows={3} value={form.summary} onChange={(e) => set("summary", e.target.value)} /></label>
      <label className="freeze-wide"><span>How the content was authored</span>
        <input name="authoring" value={form.authoring} placeholder="For example: written by me without AI assistance; or describe the assistance"
               onChange={(e) => set("authoring", e.target.value)} />
        <small>Recorded as the engine's model text. Say so if an AI system helped; nothing here is attributed to a
          model that did not write it.</small></label>
      <fieldset className="freeze-choice freeze-wide">
        <legend>Primary leg</legend>
        {H15_OBSERVABLES.map((id) => (
          <label key={id}><input type="radio" name="freeze-primary" value={id} checked={form.primary === id}
                                 onChange={() => onChange({ ...form, primary: id })} /> {OBSERVABLE_LABEL[id]}</label>
        ))}
      </fieldset>
      {form.legs.map((leg, index) => (
        <fieldset key={leg.observable_id} className="freeze-leg freeze-wide">
          <legend>{OBSERVABLE_LABEL[leg.observable_id]} <code>{leg.observable_id}</code></legend>
          <label><span>Direction</span>
            <select name={`${leg.observable_id}:expected`} value={leg.expected}
                    onChange={(e) => setLeg(index, "expected", e.target.value)}>
              <option value="">Choose…</option><option value="up">Up</option><option value="down">Down</option>
            </select></label>
          <label><span>Horizon (observations)</span>
            <select name={`${leg.observable_id}:horizon`} value={leg.horizon}
                    onChange={(e) => setLeg(index, "horizon", e.target.value)}>
              <option value="">Choose…</option><option value="1">1</option><option value="5">5</option>
              <option value="20">20</option>
            </select></label>
          <label><span>Link</span>
            <select name={`${leg.observable_id}:link`} value={leg.link}
                    onChange={(e) => setLeg(index, "link", e.target.value)}>
              <option value="">Choose…</option><option value="direct">Direct</option><option value="proxy">Proxy</option>
            </select></label>
          <label><span>Headline already reports this move?</span>
            <select name={`${leg.observable_id}:headline_reports_move`} value={leg.headline_reports_move}
                    onChange={(e) => setLeg(index, "headline_reports_move", e.target.value)}>
              <option value="">Choose…</option><option value="no">No</option><option value="yes">Yes</option>
            </select></label>
          <label className="freeze-wide"><span>Channel</span>
            <input name={`${leg.observable_id}:channel`} value={leg.channel}
                   onChange={(e) => setLeg(index, "channel", e.target.value)} /></label>
          <label className="freeze-wide"><span>Rationale</span>
            <textarea name={`${leg.observable_id}:rationale`} rows={2} value={leg.rationale}
                      onChange={(e) => setLeg(index, "rationale", e.target.value)} /></label>
          <label className="freeze-wide"><span>Falsifier</span>
            <textarea name={`${leg.observable_id}:falsifier`} rows={2} value={leg.falsifier}
                      onChange={(e) => setLeg(index, "falsifier", e.target.value)} /></label>
        </fieldset>
      ))}
      {missing.length > 0 && (
        <p className="freeze-note freeze-wide" aria-live="polite">Still needed: {missing.join("; ")}.</p>
      )}
    </div>
  );
}

function DraftChoice({ drafts, chosen, onChoose, onRetry }: {
  drafts: Loaded<Drafts>;
  chosen: string | null; onChoose: (id: string) => void; onRetry: () => void;
}) {
  if (drafts.state === "loading") return <p className="freeze-note" role="status">Loading the Tracker's drafts…</p>;
  if (drafts.state !== "ready") {
    return <div className="freeze-problem" role="alert"><p>{drafts.message}</p>
      <button type="button" className="button" onClick={onRetry}>Try again</button></div>;
  }
  const rows = drafts.data.drafts;
  return (
    <div className="freeze-drafts">
      <p className="freeze-note">Only a real provider draft built under {drafts.data.contract} (H.15 observables), with a
        current review marked Human-reviewed, can be frozen. {drafts.data.note}</p>
      {rows.length === 0 ? <p className="freeze-empty">No Tracker analyses yet.</p> : (
        <ul className="freeze-draft-list">
          {rows.map((row) => (
            <li key={row.draft_id} className={row.eligible ? "is-eligible" : "is-ineligible"} data-draft={row.draft_id}>
              <label>
                <input type="radio" name="freeze-draft" disabled={!row.eligible} checked={chosen === row.draft_id}
                       onChange={() => onChoose(row.draft_id)} />
                <span className="freeze-draft-headline">{row.headline}</span>
              </label>
              <span className="freeze-draft-meta">{row.mode} · {row.outcome.replace("_", " ")} · {row.prompt_version} ·
                review: {row.review.state}{row.review.status ? ` (${row.review.status.replace("_", " ")})` : ""}</span>
              {!row.eligible && <ul className="freeze-reasons">{row.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>}
              <Link to={`/?draft=${row.draft_id}`}>Open review</Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function StoreNotice({ store, onUpgraded }: { store: StoreState; onUpgraded: () => void }) {
  const [state, setState] = useState<{ pending: boolean; message: string | null }>({ pending: false, message: null });
  if (store.interface_freezes) return null;
  if (!store.exists) return <p className="freeze-note">{store.detail}</p>;
  return (
    <div className="freeze-upgrade" role="note">
      <p>{store.detail}</p>
      {store.schema === 2 && (
        <button type="button" className="button" disabled={state.pending} onClick={async () => {
          setState({ pending: true, message: null });
          const result = await upgradeStore();
          setState({ pending: false, message: result.state === "done" ? null : result.message });
          if (result.state === "done") onUpgraded();
        }}>Upgrade this store to schema 4</button>
      )}
      {state.message && <p className="freeze-problem" role="alert">{state.message}</p>}
    </div>
  );
}

function BaselineChoice({ baselines, chosen, onChoose, onRetry, onImported }: {
  baselines: Loaded<Baselines>;
  chosen: string | null; onChoose: (id: string) => void; onRetry: () => void; onImported: (id: string) => void;
}) {
  const [start, setStart] = useState("");  // Empty: each package's own first common date.
  const [importing, setImporting] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  if (baselines.state === "loading") return <p className="freeze-note" role="status">Loading baselines…</p>;
  if (baselines.state !== "ready") {
    return <div className="freeze-problem" role="alert"><p>{baselines.message}</p>
      <button type="button" className="button" onClick={onRetry}>Try again</button></div>;
  }
  const { snapshots, packages } = baselines.data;
  return (
    <div className="freeze-baselines">
      <h4>Snapshots in the store</h4>
      {snapshots.length === 0 ? <p className="freeze-empty">No H.15 snapshot is stored yet; import a kept package below.</p> : (
        <ul className="freeze-snapshot-list">
          {snapshots.map((snapshot) => (
            <li key={snapshot.snapshot_id} data-snapshot={snapshot.snapshot_id}>
              <label><input type="radio" name="freeze-baseline" checked={chosen === snapshot.snapshot_id}
                            onChange={() => onChoose(snapshot.snapshot_id)} /> <SnapshotLine snapshot={snapshot} /></label>
            </li>
          ))}
        </ul>
      )}
      <h4>Kept release packages</h4>
      <p className="freeze-note">{baselines.data.note}</p>
      <label className="freeze-start"><span>First date to import (empty: each package's first common date)</span>
        <input type="date" name="import-start" value={start} onChange={(e) => setStart(e.target.value)} /></label>
      {packages.length === 0 ? <p className="freeze-empty">No release package is kept. Retrieving one is a separate,
        approved action under <Link to="/market-context">Market context</Link>.</p> : (
        <ul className="freeze-package-list">
          {packages.map((row) => {
            const from = start || row.coverage?.first || "";
            return (
            <li key={row.package_id} data-package={row.package_id}>
              <span><code>{row.package_id}</code> · {row.status.replace("_", " ")} · received {formatUtc(row.received_at)}
                {row.coverage ? ` · both series ${row.coverage.first} to ${row.coverage.last}` : ""}</span>
              {row.importable ? (
                <button type="button" className="button button-quiet" disabled={importing !== null}
                        onClick={async () => {
                          setImporting(row.package_id);
                          setMessage(null);
                          const result = await importBaseline(row.package_id, from);
                          setImporting(null);
                          if (result.state === "done") {
                            setMessage(result.data.created ? "Imported as a new snapshot." :
                              "Already imported with this start: the existing snapshot is reused, nothing was written.");
                            onImported(result.data.snapshot.snapshot_id);
                          } else setMessage(result.message);
                        }}>{importing === row.package_id ? "Importing…" : `Import from ${from}`}</button>
              ) : <span className="freeze-note">Not importable: {row.detail ?? row.status.replace("_", " ")}</span>}
            </li>
            );
          })}
        </ul>
      )}
      {message && <p className="freeze-note" role="status">{message}</p>}
    </div>
  );
}

function SnapshotLine({ snapshot }: { snapshot: BaselineSummary }) {
  const ranges = Object.entries(snapshot.coverage).map(([series, entry]) =>
    `${series} ${entry.classified_from} to ${entry.classified_through}`);
  return (
    <span className="freeze-snapshot">
      <code>{snapshot.snapshot_id.slice(0, 12)}</code> · {providerName(snapshot.provider)} · held since
      {" "}{formatUtc(snapshot.retrieved_at)} · {snapshot.vintage_date === null ? "no vintage" : `vintage ${snapshot.vintage_date}`}
      {" "}· {ranges.join("; ")}
    </span>
  );
}

function PreviewPanel({ preview }: { preview: Preview }) {
  return (
    <div className="freeze-preview" data-preview={preview.preview_sha256}>
      <p className="freeze-classification">{preview.classification}</p>
      <dl className="ledger freeze-ledger">
        <div><dt>Preview SHA-256</dt><dd>{preview.preview_sha256}</dd></div>
        <div><dt>Effective content SHA-256</dt><dd>{preview.effective_sha256}</dd></div>
        <div><dt>Freeze policy</dt><dd>{preview.binding.freeze_policy}</dd></div>
        <div><dt>Freeze time</dt><dd>{preview.freeze_time}</dd></div>
      </dl>
      <EffectiveContent hypothesis={preview.binding.effective_hypothesis} origin={preview.binding.origin}
                        bindings={preview.binding.source_bindings} />
      <BaselineCard baseline={preview.baseline} />
      <FreshnessList freshness={preview.freshness} note={preview.policy_note} />
      {preview.readiness && (
        <div className="freeze-block">
          <h4>Readiness (rules {preview.readiness.rules_version})</h4>
          <ul>{Object.entries(preview.readiness.legs).map(([leg, entry]) => (
            <li key={leg}>{OBSERVABLE_LABEL[entry.observable_id] ?? entry.observable_id}, horizon {entry.horizon}: event
              anchor {entry.event_anchor ?? "none"}, {entry.reference_windows} usable reference windows of
              {" "}{entry.required_reference_windows} required — {entry.scorable ? "scorable" : "not scorable"}</li>
          ))}</ul>
        </div>
      )}
      <ScoringNote scoring={preview.scoring} convention={preview.measurement_convention} />
      <div className="freeze-block"><h4>Limitations</h4>
        <ul>{preview.limitations.map((item) => <li key={item}>{item}</li>)}</ul></div>
      {preview.blockers.length > 0 && (
        <div className="freeze-blockers" role="alert"><h4>Why this cannot be frozen</h4>
          <ul>{preview.blockers.map((item) => <li key={item}>{item}</li>)}</ul></div>
      )}
    </div>
  );
}

function OutcomePanel({ outcome, onCheck }: { outcome: Outcome; onCheck: (actionId: string) => void }) {
  if (outcome.state === "frozen") {
    const { result } = outcome;
    return (
      <div className="freeze-outcome is-frozen" role="status">
        <p className="freeze-status">{result.status}</p>
        <p>{result.created ? `Frozen at ${formatUtc(result.recorded_at)} (the server's time).`
          : `This approval had already frozen it at ${formatUtc(result.recorded_at)}; nothing was frozen again.`}
          {" "}Nothing was evaluated or prepared.</p>
        <Link to={hypothesisHref(result.hypothesis_id)}>Open the frozen hypothesis</Link>
      </div>
    );
  }
  if (outcome.state === "refused") return <p className="freeze-problem" role="alert">{outcome.message}</p>;
  if (outcome.state === "unconfirmed") {
    return (
      <div className="freeze-outcome is-unconfirmed" role="alert">
        <p>{outcome.message}</p>
        <p>The approval is not sent again. Read whether it froze anything:</p>
        <button type="button" className="button" onClick={() => onCheck(outcome.actionId)}>Check the outcome</button>
      </div>
    );
  }
  if (outcome.state === "checked") {
    const { result } = outcome;
    return (
      <div className="freeze-outcome" role="status">
        <p>{result.detail}</p>
        {result.state === "frozen" && result.hypothesis_id && (
          <Link to={hypothesisHref(result.hypothesis_id)}>Open the frozen hypothesis</Link>
        )}
      </div>
    );
  }
  return null;
}
