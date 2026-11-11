import { useEffect, useRef, useState } from "react";
import { useLoad, type Loaded } from "../api";
import {
  DOSSIER_STATE_LABEL, EVALUATE_AND_PREPARE, approveAssessment, assessmentHref, checkAssessmentAction, fetchReadiness,
  importOutcome, lifecycleDossierHref, prepareDossier, previewAssessment, verdictWord,
  type AssessmentActionState, type AssessmentPreview, type AssessmentRow, type Candidate, type DossierState,
  type LegReadiness, type Readiness, type Recorded,
} from "../assessment";
import { formatUtc } from "../format";
import { OBSERVABLE_LABEL, providerName, upgradeStore } from "../lifecycle";
import { Link } from "../router";
import { TableArea } from "./FrozenParts";

type Outcome =
  | { state: "idle" }
  | { state: "pending" }
  | { state: "recorded"; result: Recorded }
  | { state: "refused"; message: string }
  | { state: "unconfirmed"; message: string; actionId: string }
  | { state: "checked"; result: AssessmentActionState };

/**
 * One frozen hypothesis's path to one explicit assessment: see what is ready, choose (or explicitly import) an
 * outcome snapshot, preview exactly what will be assessed, then approve that preview once. Loading only reads; a
 * changed choice clears the preview; a lost reply is resolved by reading the outcome, never by sending again.
 */
export function AssessmentFlow({ hypothesisId, onRecorded }: { hypothesisId: string; onRecorded: () => void }) {
  const [version, setVersion] = useState(0);
  const [loaded, retry] = useLoad((signal) => fetchReadiness(hypothesisId, signal), `readiness:${hypothesisId}:${version}`);
  // The last readiness read: the flow stays mounted while it reloads after an import or an assessment.
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  useEffect(() => {
    if (loaded.state === "ready") setReadiness(loaded.data);
  }, [loaded]);
  const reload = () => setVersion((value) => value + 1);
  if (!readiness) {
    if (loaded.state === "loading") return <p className="freeze-note" role="status">Checking readiness…</p>;
    return <div className="freeze-problem" role="alert"><p>{"message" in loaded ? loaded.message : ""}</p>
      <button type="button" className="button" onClick={retry}>Try again</button></div>;
  }
  return <Flow readiness={readiness} loaded={loaded} onReload={reload} onRecorded={() => { reload(); onRecorded(); }} />;
}

function Flow({ readiness, loaded, onReload, onRecorded }: {
  readiness: Readiness; loaded: Loaded<Readiness>; onReload: () => void; onRecorded: () => void;
}) {
  const [chosen, setChosen] = useState<string | null>(null);
  const [preview, setPreview] = useState<AssessmentPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [approved, setApproved] = useState(false);
  const [reassess, setReassess] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>({ state: "idle" });
  const inflight = useRef(false);
  useEffect(() => {  // Another outcome choice voids the preview and the approval.
    setPreview(null);
    setApproved(false);
    setReassess(false);
    setProblem(null);
  }, [chosen]);
  const usable = readiness.candidates.filter((item) => item.usable);

  const runPreview = async () => {
    if (!chosen) return;
    setPreviewing(true);
    setProblem(null);
    const result = await previewAssessment(readiness.hypothesis_id, chosen);
    setPreviewing(false);
    setApproved(false);
    setReassess(false);
    if (result.state === "done") setPreview(result.data);
    else setProblem(result.message);
  };

  const evaluate = async () => {
    if (!preview || !approved || inflight.current) return;
    inflight.current = true;  // One request at a time from this page; a second click does nothing.
    setOutcome({ state: "pending" });
    const result = await approveAssessment(preview, preview.binding.reassessment && reassess);
    inflight.current = false;
    if (result.state === "done") {
      setOutcome({ state: "recorded", result: result.data });
      onRecorded();
    } else if (result.state === "refused") {
      if (result.preview) {
        setPreview(result.preview);  // The server's current preview, to review and approve again (or not).
        setApproved(false);
        setReassess(false);
      }
      setOutcome({ state: "refused", message: result.message });
    } else {
      setOutcome({ state: "unconfirmed", message: result.message, actionId: preview.preview_sha256 });
    }
  };

  const check = async (actionId: string) => {
    const result = await checkAssessmentAction(actionId, new AbortController().signal);
    if (result.state === "ready") {
      setOutcome({ state: "checked", result: result.data });
      if (result.data.state === "recorded") onRecorded();
    } else setOutcome({ state: "unconfirmed", actionId, message: "message" in result ? result.message : "Not checked." });
  };

  return (
    <div className="freeze-flow assess-flow" data-state={readiness.state}>
      <section className="freeze-step" aria-labelledby="assess-step-1">
        <h3 id="assess-step-1"><span>1</span> Outcome data</h3>
        <ReadinessSummary readiness={readiness} />
        {loaded.state === "loading" && <p className="freeze-note" role="status">Reading again…</p>}
        <StoreUpgrade readiness={readiness} onUpgraded={onReload} />
        <CandidateChoice candidates={readiness.candidates} chosen={chosen} onChoose={setChosen} />
        <PackageImports readiness={readiness} onImported={(id) => { onReload(); if (id) setChosen(id); }} />
      </section>

      <section className="freeze-step" aria-labelledby="assess-step-2">
        <h3 id="assess-step-2"><span>2</span> Preview the assessment</h3>
        <p className="freeze-note">A preview writes nothing, evaluates nothing and contacts no provider. It shows what
          would be assessed and recorded, not the result.</p>
        <button type="button" className="button assess-preview-button" disabled={!chosen || previewing}
                onClick={runPreview}>{previewing ? "Previewing…" : "Preview the assessment"}</button>
        {!chosen && <p className="freeze-note">Choose an outcome snapshot in step 1. {readiness.default_selection}</p>}
        {usable.length === 0 && <p className="freeze-note">No usable outcome snapshot is stored for this hypothesis yet.</p>}
        {problem && <p className="freeze-problem" role="alert">{problem}</p>}
        {preview && <PreviewPanel preview={preview} />}
      </section>

      <section className="freeze-step" aria-labelledby="assess-step-3">
        <h3 id="assess-step-3"><span>3</span> {EVALUATE_AND_PREPARE}</h3>
        {preview && !preview.assessable && (
          <p className="freeze-problem" role="alert">This preview cannot be assessed: {preview.blockers.join(" ")}</p>
        )}
        {preview?.binding.reassessment && (
          <label className="freeze-confirm assess-reassess">
            <input type="checkbox" name="reassessment" checked={reassess} disabled={!preview.assessable}
                   onChange={(event) => setReassess(event.target.checked)} />
            <span>This hypothesis already has {preview.binding.prior_assessments.length} recorded
              assessment{preview.binding.prior_assessments.length === 1 ? "" : "s"}. I decide to record an additional
              one on this outcome snapshot; the earlier ones stay unchanged and individually accessible.</span>
          </label>
        )}
        <label className="freeze-confirm">
          <input type="checkbox" name="approve-assessment" checked={approved}
                 disabled={!preview?.assessable || outcome.state === "recorded"}
                 onChange={(event) => setApproved(event.target.checked)} />
          <span>I approve evaluating exactly this preview, recording the result and preparing its Dossier. The cutoff is
            the server's, the record is append-only and is never recomputed or overwritten.</span>
        </label>
        <button type="button" className="button button-freeze"
                disabled={!preview?.assessable || !approved || (preview.binding.reassessment && !reassess) ||
                  outcome.state === "pending" || outcome.state === "recorded"}
                onClick={evaluate}>{outcome.state === "pending" ? "Evaluating…" : EVALUATE_AND_PREPARE}</button>
        <OutcomePanel outcome={outcome} onCheck={check} onPrepared={onRecorded} />
      </section>
    </div>
  );
}

function ReadinessSummary({ readiness }: { readiness: Readiness }) {
  const { expected } = readiness;
  return (
    <div className="assess-readiness">
      <p className="freeze-status" data-state={readiness.state}>{readiness.state_label}</p>
      <p>Expected scoring anchor {expected.expected_score_anchor ?? "unknown"} (the first session after the New York
        freeze date {expected.freeze_date_new_york}); latest expected target {expected.latest_expected_target ?? "unknown"}.
        {" "}{expected.counts_after && `Its observation counts only after that New York date ends (${expected.counts_after}). `}
        When the publisher supplies it is not known; nothing is requested while waiting.</p>
      <p className="freeze-note">{expected.note} {readiness.measurement_convention}</p>
      {readiness.baseline_problem && <p className="freeze-problem" role="alert">{readiness.baseline_problem}</p>}
      {readiness.fred_note && <p className="freeze-note assess-fred">{readiness.fred_note}</p>}
      <p className="freeze-note">{readiness.rules_note}</p>
    </div>
  );
}

function StoreUpgrade({ readiness, onUpgraded }: { readiness: Readiness; onUpgraded: () => void }) {
  const [state, setState] = useState<{ pending: boolean; message: string | null }>({ pending: false, message: null });
  if (readiness.assessable_store) return null;
  return (
    <div className="freeze-upgrade" role="note">
      <p>This store uses schema {readiness.store_schema}. Assessments need schema 4 (an added assessment-action table);
        upgrading only adds tables and leaves every record unchanged.</p>
      <button type="button" className="button" disabled={state.pending} onClick={async () => {
        setState({ pending: true, message: null });
        const result = await upgradeStore();
        setState({ pending: false, message: result.state === "done" ? null : result.message });
        if (result.state === "done") onUpgraded();
      }}>Upgrade this store to schema 4</button>
      {state.message && <p className="freeze-problem" role="alert">{state.message}</p>}
    </div>
  );
}

function legLine(leg: LegReadiness): string {
  const name = OBSERVABLE_LABEL[leg.observable_id] ?? leg.observable_id;
  const dates = leg.score_anchor ? `scoring anchor ${leg.score_anchor}, target ${leg.target ?? "not in the data yet"}` : "";
  return `${name}, ${leg.horizon} observation${leg.horizon === 1 ? "" : "s"}: ${dates}${dates ? " — " : ""}` +
    `${leg.state.replace(/_/g, " ")}${leg.detail ? `. ${leg.detail}` : ""}`;
}

function CandidateChoice({ candidates, chosen, onChoose }: {
  candidates: Candidate[]; chosen: string | null; onChoose: (id: string) => void;
}) {
  return (
    <div className="freeze-baselines">
      <h4>Outcome snapshots in the store</h4>
      {candidates.length === 0 ? <p className="freeze-empty">No other snapshot of this provider is stored. The
        baseline bound at freeze is never an outcome.</p> : (
        <ul className="freeze-snapshot-list assess-candidates">
          {candidates.map((item) => (
            <li key={item.snapshot_id} data-snapshot={item.snapshot_id} className={item.usable ? "" : "is-ineligible"}>
              <label>
                <input type="radio" name="outcome-snapshot" disabled={!item.usable} checked={chosen === item.snapshot_id}
                       onChange={() => onChoose(item.snapshot_id)} />
                <span className="freeze-snapshot"><code>{item.snapshot_id.slice(0, 12)}</code>
                  {item.summary && <> · {providerName(item.summary.provider)} · held since {formatUtc(item.summary.retrieved_at)}
                    {item.summary.package ? ` · package ${item.summary.package.package_id}` : ""}</>}
                  {item.state && <> · <strong>{item.state.replace(/_/g, " ")}</strong></>}</span>
              </label>
              {item.problems.length > 0 && <ul className="freeze-reasons">{item.problems.map((text) => <li key={text}>{text}</li>)}</ul>}
              {item.legs.length > 0 && <ul className="freeze-reasons assess-legs">{item.legs.map((leg) => (
                <li key={leg.leg_id} data-leg-state={leg.state}>{legLine(leg)}
                  {leg.gaps.length > 0 && ` Gaps: ${leg.gaps.map((gap) => `${gap.date} (${gap.status.replace(/_/g, " ")})`).join(", ")}.`}</li>
              ))}</ul>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function PackageImports({ readiness, onImported }: { readiness: Readiness; onImported: (id: string | null) => void }) {
  const [importing, setImporting] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  if (readiness.provider !== "board-h15") return null;
  return (
    <div className="freeze-baselines">
      <h4>Kept release packages</h4>
      <p className="freeze-note">Importing copies a kept, accepted package's two series into the store from the
        publication date, locally; an existing snapshot of it that already serves is reused. A package that is not
        held needs an approved retrieval on the <Link to="/hypotheses">Hypotheses</Link> page; nothing here downloads.</p>
      {readiness.packages.length === 0 ? <p className="freeze-empty">No release package is kept.</p> : (
        <ul className="freeze-package-list">
          {readiness.packages.map((row) => (
            <li key={row.package_id} data-package={row.package_id}>
              <span><code>{row.package_id}</code> · {row.status.replace(/_/g, " ")} · received {formatUtc(row.received_at)}
                {row.coverage ? ` · both series ${row.coverage.first} to ${row.coverage.last}` : ""}
                {row.coverage && !row.covers_expected_targets ? " · does not reach the latest expected target" : ""}</span>
              {row.serving_snapshot ? <span className="freeze-note">Serving as snapshot {row.serving_snapshot.slice(0, 12)}</span>
                : row.importable ? (
                  <button type="button" className="button button-quiet" disabled={importing !== null} onClick={async () => {
                    setImporting(row.package_id);
                    setMessage(null);
                    const result = await importOutcome(readiness.hypothesis_id, row.package_id);
                    setImporting(null);
                    if (result.state === "done") {
                      const data = result.data;
                      setMessage(data.reused ? "Already imported: the existing snapshot is reused; nothing was written."
                        : data.usable ? "Imported as a new outcome snapshot." : `Imported, but it cannot serve: ${data.problems.join(" ")}`);
                      onImported(data.usable && data.snapshot ? data.snapshot.snapshot_id : null);
                    } else setMessage(result.message);
                  }}>{importing === row.package_id ? "Importing…" : `Import as outcome from ${row.start}`}</button>
                ) : <span className="freeze-note">Not usable here: {row.reasons.join(" ")}</span>}
            </li>
          ))}
        </ul>
      )}
      {message && <p className="freeze-note" role="status">{message}</p>}
    </div>
  );
}

function PreviewPanel({ preview }: { preview: AssessmentPreview }) {
  const { binding } = preview;
  return (
    <div className="freeze-preview" data-preview={preview.preview_sha256}>
      {preview.classification && <p className="freeze-classification">{preview.classification}</p>}
      <p className="freeze-note assess-evaluation-note">{preview.evaluation_note}</p>
      <dl className="ledger freeze-ledger">
        <div><dt>Preview SHA-256</dt><dd>{preview.preview_sha256}</dd></div>
        <div><dt>Hypothesis ID (SHA-256 of the stored record)</dt><dd>{binding.hypothesis_id}</dd></div>
        <div><dt>Effective content SHA-256</dt><dd>{preview.hypothesis.effective_sha256 ?? "Not recorded (frozen outside this interface)"}</dd></div>
        <div><dt>Baseline (bound at freeze)</dt><dd>{binding.baseline_snapshot_id} · {providerName(preview.baseline.provider)} ·
          held since {formatUtc(preview.baseline.retrieved_at)}</dd></div>
        <div><dt>Outcome</dt><dd>{binding.outcome_snapshot_id} · {providerName(preview.outcome.provider)} · held since
          {" "}{formatUtc(preview.outcome.retrieved_at)}{preview.outcome.package ? ` · package ${preview.outcome.package.package_id}` : ""}
          {" "}· {preview.outcome.vintage_date === null ? "no vintage" : `vintage ${preview.outcome.vintage_date}`}</dd></div>
        <div><dt>Rules</dt><dd>{preview.rules.version} · SHA-256 {preview.rules.hash}</dd></div>
        <div><dt>Cutoff (server's)</dt><dd>{binding.cutoff ? formatUtc(binding.cutoff) : "None: not assessable"}</dd></div>
        <div><dt>Readiness</dt><dd>{preview.state_label}</dd></div>
      </dl>
      <p className="freeze-note">{preview.rules.note}</p>
      <p className="freeze-note">{preview.cutoff.rule}</p>
      <TableArea label="The dates each leg would be measured on">
        <table className="freeze-legs assess-dates">
          <thead><tr><th scope="col">Leg</th><th scope="col">Event anchor</th><th scope="col">Scoring anchor</th>
            <th scope="col">Target</th><th scope="col">Readiness</th></tr></thead>
          <tbody>{preview.legs.map((leg) => (
            <tr key={leg.leg_id} data-leg={leg.leg_id}>
              <th scope="row">{leg.leg_id}{leg.primary ? " (primary)" : ""}<br />
                <code>{leg.series_id}</code>, {leg.horizon} obs.</th>
              <td>{leg.event_anchor ?? "—"}</td><td>{leg.score_anchor ?? "—"}</td><td>{leg.target ?? "—"}</td>
              <td>{leg.state.replace(/_/g, " ")}{leg.gaps.length > 0 && `: no value on ${leg.gaps.map((gap) => gap.date).join(", ")}`}</td>
            </tr>
          ))}</tbody>
        </table>
      </TableArea>
      {preview.prior_assessments.length > 0 && (
        <div className="freeze-block"><h4>Already recorded for this hypothesis</h4>
          <AssessmentList hypothesisId={binding.hypothesis_id} rows={preview.prior_assessments} /></div>
      )}
      <div className="freeze-block"><h4>This approval will create</h4>
        <ul>{preview.creates.map((item) => <li key={item}>{item}</li>)}</ul></div>
      {preview.limitations.length > 0 && <div className="freeze-block"><h4>Limitations</h4>
        <ul>{preview.limitations.map((item) => <li key={item}>{item}</li>)}</ul></div>}
      {preview.blockers.length > 0 && (
        <div className="freeze-blockers" role="alert"><h4>Why this cannot be assessed now</h4>
          <ul>{preview.blockers.map((item) => <li key={item}>{item}</li>)}</ul></div>
      )}
    </div>
  );
}

/** Recorded assessments, by record time; none is selected or ordered by its result. */
export function AssessmentList({ hypothesisId, rows }: { hypothesisId: string; rows: AssessmentRow[] }) {
  return (
    <ol className="assess-list">
      {rows.map((row, index) => (
        <li key={row.evaluation_id} data-evaluation={row.evaluation_id}>
          <Link to={assessmentHref(hypothesisId, row.evaluation_id)}>Assessment {index + 1}</Link>
          {" "}· recorded {formatUtc(row.recorded_at)} · {verdictWord(row.verdict)} · outcome
          {" "}<code>{row.outcome_snapshot_id?.slice(0, 12) ?? "?"}</code> · rules {row.rules_version} · {row.recorded_by}
          {" "}· <DossierLink hypothesisId={hypothesisId} evaluationId={row.evaluation_id} dossier={row.dossier} />
        </li>
      ))}
    </ol>
  );
}

export function DossierLink({ hypothesisId, evaluationId, dossier }: {
  hypothesisId: string; evaluationId: string; dossier: DossierState;
}) {
  return dossier.state === "prepared"
    ? <Link to={lifecycleDossierHref(hypothesisId, evaluationId)}>Open the Dossier</Link>
    : <span className={`assess-dossier is-${dossier.state}`}>{DOSSIER_STATE_LABEL[dossier.state]}</span>;
}

/** The explicit preparation of one stored assessment's Dossier; it records no new assessment. */
export function PrepareButton({ hypothesisId, evaluationId, onPrepared }: {
  hypothesisId: string; evaluationId: string; onPrepared: () => void;
}) {
  const [state, setState] = useState<{ pending: boolean; message: string | null }>({ pending: false, message: null });
  return (
    <div className="assess-prepare">
      <button type="button" className="button" disabled={state.pending} onClick={async () => {
        setState({ pending: true, message: null });
        const result = await prepareDossier(hypothesisId, evaluationId);
        setState({ pending: false, message: result.state === "done" ? (result.data.created ? "Dossier prepared."
          : "The Dossier was already prepared; nothing was rewritten.") : result.message });
        if (result.state === "done") onPrepared();
      }}>{state.pending ? "Preparing…" : "Prepare Dossier"}</button>
      <span className="freeze-note"> Rebuilds the chart and reference distribution from the pinned inputs and records
        nothing new.</span>
      {state.message && <p className="freeze-note" role="status">{state.message}</p>}
    </div>
  );
}

function OutcomePanel({ outcome, onCheck, onPrepared }: {
  outcome: Outcome; onCheck: (actionId: string) => void; onPrepared: () => void;
}) {
  if (outcome.state === "recorded") {
    const { result } = outcome;
    const prepared = result.dossier.state === "prepared";
    return (
      <div className={`freeze-outcome ${prepared ? "is-frozen" : "is-unconfirmed"}`} role="status">
        <p className="freeze-status">{result.headline}</p>
        <p>{result.created ? `Recorded at ${formatUtc(result.recorded_at)} (the server's time).`
          : `This approval had already recorded it at ${formatUtc(result.recorded_at)}; nothing was evaluated again.`}</p>
        {!prepared && result.dossier.detail && <p>{result.dossier.detail}</p>}
        <p><Link to={assessmentHref(result.hypothesis_id, result.evaluation_id)}>Open the recorded assessment</Link>
          {prepared && <> · <Link to={lifecycleDossierHref(result.hypothesis_id, result.evaluation_id)}>Open the Dossier</Link></>}</p>
        {!prepared && <PrepareButton hypothesisId={result.hypothesis_id} evaluationId={result.evaluation_id}
                                     onPrepared={onPrepared} />}
      </div>
    );
  }
  if (outcome.state === "refused") return <p className="freeze-problem" role="alert">{outcome.message}</p>;
  if (outcome.state === "unconfirmed") {
    return (
      <div className="freeze-outcome is-unconfirmed" role="alert">
        <p>{outcome.message}</p>
        <p>The approval is not sent again. Read whether it recorded an assessment:</p>
        <button type="button" className="button" onClick={() => onCheck(outcome.actionId)}>Check the outcome</button>
      </div>
    );
  }
  if (outcome.state === "checked") {
    const { result } = outcome;
    return (
      <div className="freeze-outcome" role="status">
        <p>{result.detail}</p>
        {result.state === "recorded" && result.hypothesis_id && result.evaluation_id && (
          <p><Link to={assessmentHref(result.hypothesis_id, result.evaluation_id)}>Open the recorded assessment</Link>
            {result.dossier && <> · <DossierLink hypothesisId={result.hypothesis_id} evaluationId={result.evaluation_id}
                                                 dossier={result.dossier} /></>}</p>
        )}
      </div>
    );
  }
  return null;
}
