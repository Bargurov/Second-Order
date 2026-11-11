import { useEffect, useState, type CSSProperties } from "react";
import { useLoad } from "../api";
import { fetchAssessment, lifecycleDossierHref, verdictWord, type AssessmentView } from "../assessment";
import { DossierLink, PrepareButton } from "../components/AssessmentFlow";
import { TableArea } from "../components/FrozenParts";
import { formatUtc } from "../format";
import { OBSERVABLE_LABEL, hypothesisHref, providerName } from "../lifecycle";
import { Link } from "../router";
import "../lifecycle.css";

const order = (i: number) => ({ "--i": i }) as CSSProperties;
const number = (value: number | null | undefined, digits = 2) =>
  value === null || value === undefined ? "—" : value.toFixed(digits);

/** One recorded assessment, exactly as stored. Reading it evaluates, prepares and writes nothing. */
export function AssessmentPage({ id, evaluationId }: { id: string; evaluationId: string }) {
  const [version, setVersion] = useState(0);
  const [loaded, retry] = useLoad((signal) => fetchAssessment(id, evaluationId, signal),
                                  `assessment:${id}:${evaluationId}:${version}`);
  const [last, setLast] = useState<AssessmentView | null>(null);
  useEffect(() => {
    if (loaded.state === "ready") setLast(loaded.data);
  }, [loaded]);
  const view: typeof loaded = loaded.state === "loading" && last ? { state: "ready", data: last } : loaded;
  useEffect(() => {
    document.title = view.state === "ready" ? `${view.data.headline} · Assessment · Second Order`
      : "Assessment · Second Order";
  }, [view]);
  if (view.state === "loading") return <p className="state-panel" role="status">Loading the assessment…</p>;
  if (view.state !== "ready") {
    return (
      <section className="state-panel" aria-labelledby="assessment-missing">
        <p className="kicker">Hypotheses</p>
        <h1 id="assessment-missing">{view.state === "missing" ? "There is no assessment at this address" : "It could not be read"}</h1>
        <p className="lede">{view.message}</p>
        <p><Link to={hypothesisHref(id)}>The hypothesis</Link>{view.state === "error" && <> · <button type="button"
          className="button" onClick={retry}>Try again</button></>}</p>
      </section>
    );
  }
  const data = view.data;
  const { evaluation, action } = data;
  return (
    <article className="frozen-hypothesis assessment-record">
      <header className="hypotheses-header reveal" style={order(0)}>
        <p className="kicker"><Link to="/hypotheses">Hypotheses</Link> · <Link to={hypothesisHref(id)}>frozen record</Link>
          {" "}· assessment {data.position} of {data.assessments}</p>
        <h1>{data.headline}</h1>
        <p className="freeze-status" data-verdict={evaluation.verdict}>Recorded · {verdictWord(evaluation.verdict)}</p>
        {data.classification && <p className="freeze-classification">{data.classification}</p>}
      </header>
      <section className="card reveal" style={order(1)} aria-labelledby="assessment-record-title">
        <h2 id="assessment-record-title">Record</h2>
        <dl className="ledger freeze-ledger">
          <div><dt>Assessment ID (SHA-256 of the stored record)</dt><dd>{data.evaluation_id}</dd></div>
          <div><dt>Recorded at (server time)</dt><dd>{formatUtc(data.recorded_at)}</dd></div>
          <div><dt>Recorded by</dt><dd>{data.recorded_by}</dd></div>
          <div><dt>Cutoff</dt><dd>{formatUtc(evaluation.as_of)}</dd></div>
          <div><dt>Rules</dt><dd>{evaluation.rules.version} · SHA-256 {evaluation.rules_hash}</dd></div>
          <div><dt>Baseline (bound at freeze)</dt><dd>{data.baseline.snapshot_id} · {providerName(data.baseline.provider)}</dd></div>
          <div><dt>Outcome</dt><dd>{data.outcome ? `${data.outcome.snapshot_id} · ${providerName(data.outcome.provider)} · held since ${formatUtc(data.outcome.retrieved_at)}` : "Not recorded"}</dd></div>
          {action && <div><dt>Approval</dt><dd>{action.binding.hypothesis_id === id ? `${action.approval.reassessment
            ? "Reassessment" : "First assessment"}, approved ${formatUtc(action.approval.received_at)}` : "Does not match"}</dd></div>}
          <div><dt>Dossier</dt><dd><DossierLink hypothesisId={id} evaluationId={data.evaluation_id} dossier={data.dossier} /></dd></div>
        </dl>
        {data.dossier.state === "not_prepared" && (
          <PrepareButton hypothesisId={id} evaluationId={data.evaluation_id} onPrepared={() => setVersion((v) => v + 1)} />
        )}
        {data.dossier.state === "problem" && <p className="freeze-problem" role="alert">{data.dossier.detail}</p>}
        {action && <p className="freeze-note">{action.binding.cutoff_rule}</p>}
      </section>
      <section className="card reveal" style={order(2)} aria-labelledby="assessment-legs-title">
        <h2 id="assessment-legs-title">Legs, as recorded</h2>
        <TableArea label="Legs, as recorded">
          <table className="freeze-legs assess-recorded-legs">
            <thead><tr><th scope="col">Leg</th><th scope="col">Verdict</th><th scope="col">Measured change</th>
              <th scope="col">Percentile rank</th><th scope="col">Reference windows</th>
              <th scope="col">Scoring anchor → target (New York dates)</th>
              <th scope="col">Reason</th></tr></thead>
            <tbody>{evaluation.legs.map((leg) => (
              <tr key={leg.leg_id} data-leg={leg.leg_id} data-verdict={leg.verdict}>
                <th scope="row">{leg.leg_id}{leg.primary ? " (primary)" : ""}<br />
                  {OBSERVABLE_LABEL[leg.observable_id] ?? leg.observable_id}, {leg.horizon} obs.</th>
                <td>{verdictWord(leg.verdict)}</td>
                <td>{leg.measured_change === undefined || leg.measured_change === null ? "—"
                  : `${number(leg.measured_change, 1)} ${leg.unit}`}</td>
                <td>{number(leg.percentile_rank)}</td>
                <td>{leg.reference_windows ?? "—"}</td>
                <td>{data.anchor_dates[leg.leg_id]?.score_anchor
                  ? `${data.anchor_dates[leg.leg_id].score_anchor} → ${data.anchor_dates[leg.leg_id].target_at ?? "—"}` : "—"}</td>
                <td>{leg.reason || "—"}</td>
              </tr>
            ))}</tbody>
          </table>
        </TableArea>
        <p className="freeze-note">{data.measurement_convention} Labels describe whether later observations were
          consistent with the frozen hypothesis; they are not causal proof, significance tests or trading signals.
          {data.dossier.state === "prepared" && <> The <Link to={lifecycleDossierHref(id, data.evaluation_id)}>Dossier</Link>
            {" "}shows the chart and reference distribution.</>}</p>
        {data.limitations.length > 0 && <div className="freeze-block"><h4>Limitations</h4>
          <ul>{data.limitations.map((item) => <li key={item}>{item}</li>)}</ul></div>}
      </section>
    </article>
  );
}
