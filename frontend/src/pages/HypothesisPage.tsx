import { useEffect, useState, type CSSProperties } from "react";
import { useLoad } from "../api";
import { AssessmentFlow } from "../components/AssessmentFlow";
import { BaselineCard, EffectiveContent, FreshnessList, ScoringNote } from "../components/FrozenParts";
import { formatUtc } from "../format";
import { fetchFrozen, type FrozenView } from "../lifecycle";
import { Link } from "../router";
import "../lifecycle.css";

const order = (i: number) => ({ "--i": i }) as CSSProperties;

/** One frozen hypothesis, reopened from the store. Loading reads only; assessing it is an explicit action below. */
export function HypothesisPage({ id }: { id: string }) {
  const [version, setVersion] = useState(0);
  const [loaded, retry] = useLoad((signal) => fetchFrozen(id, signal), `frozen:${id}:${version}`);
  // The last record read. The assessment flow stays mounted while the record reloads after an assessment, so its
  // outcome (and any "Dossier not prepared" action) is never lost to a refresh.
  const [last, setLast] = useState<FrozenView | null>(null);
  useEffect(() => {
    if (loaded.state === "ready") setLast(loaded.data);
  }, [loaded]);
  const view: typeof loaded = loaded.state === "loading" && last ? { state: "ready", data: last } : loaded;
  useEffect(() => {
    document.title = view.state === "ready" ? `${view.data.hypothesis.event.headline} · Frozen · Second Order`
      : "Frozen hypothesis · Second Order";
  }, [view]);
  if (view.state === "loading") return <p className="state-panel" role="status">Loading the frozen hypothesis…</p>;
  if (view.state !== "ready") {
    return (
      <section className="state-panel" aria-labelledby="frozen-missing">
        <p className="kicker">Hypotheses</p>
        <h1 id="frozen-missing">{view.state === "missing" ? "There is no frozen hypothesis at this address" : "It could not be read"}</h1>
        <p className="lede">{view.message}</p>
        <p><Link to="/hypotheses">All hypotheses</Link>{view.state === "error" && <> · <button type="button" className="button"
          onClick={retry}>Try again</button></>}</p>
      </section>
    );
  }
  const frozen = view.data;
  return (
    <article className="frozen-hypothesis">
      <header className="hypotheses-header reveal" style={order(0)}>
        <p className="kicker"><Link to="/hypotheses">Hypotheses</Link> · frozen record</p>
        <h1>{frozen.hypothesis.event.headline}</h1>
        <p className="freeze-status" data-status={frozen.status}>{frozen.status}</p>
        {frozen.classification && <p className="freeze-classification">{frozen.classification}</p>}
      </header>
      <section className="card reveal" style={order(1)} aria-labelledby="frozen-record">
        <h2 id="frozen-record">Record</h2>
        <dl className="ledger freeze-ledger">
          <div><dt>Hypothesis ID (SHA-256 of the stored record)</dt><dd>{frozen.hypothesis_id}</dd></div>
          <div><dt>Frozen at (server time)</dt><dd>{formatUtc(frozen.frozen_at)}</dd></div>
          <div><dt>Recorded at</dt><dd>{formatUtc(frozen.recorded_at)}</dd></div>
          <div><dt>Effective content SHA-256</dt><dd>{frozen.effective_sha256 ?? "Not recorded (frozen outside this interface)"}</dd></div>
          <div><dt>Approval</dt><dd>{frozen.action_id ?? "Not recorded (frozen outside this interface)"}</dd></div>
          <div><dt>Evaluations</dt><dd>{frozen.evaluations}</dd></div>
        </dl>
        <p className="freeze-note">The record never changes. Assessments are appended separately, each by its own
          explicit approval below; opening this page starts none.</p>
      </section>
      <section className="card reveal assess-card" style={order(1)} aria-labelledby="assess-title">
        <h2 id="assess-title">Outcome and assessment</h2>
        <AssessmentFlow hypothesisId={frozen.hypothesis_id} onRecorded={() => setVersion((value) => value + 1)} />
      </section>
      <section className="card reveal" style={order(2)} aria-label="Content">
        <EffectiveContent hypothesis={frozen.hypothesis} origin={frozen.origin} />
      </section>
      <section className="card reveal" style={order(3)} aria-label="Baseline and measurement">
        <BaselineCard baseline={frozen.baseline} />
        <FreshnessList freshness={frozen.freshness} />
        <ScoringNote scoring={frozen.scoring} convention={frozen.measurement_convention} />
        {frozen.limitations.length > 0 && (
          <div className="freeze-block"><h4>Limitations</h4>
            <ul>{frozen.limitations.map((item) => <li key={item}>{item}</li>)}</ul></div>
        )}
      </section>
    </article>
  );
}
