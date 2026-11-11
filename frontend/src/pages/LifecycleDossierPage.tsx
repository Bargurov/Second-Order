import { useEffect, type CSSProperties } from "react";
import { useLoad } from "../api";
import { assessmentHref, fetchLifecycleDossier, lifecycleDossierHref, type SnapshotStatus } from "../assessment";
import { formatUtc } from "../format";
import { hypothesisHref } from "../lifecycle";
import { Link } from "../router";
import { DossierView } from "./DossierPage";
import "../lifecycle.css";

const order = (i: number) => ({ "--i": i }) as CSSProperties;

/** A prepared Dossier of one recorded assessment, verified when read. Reading never evaluates, imports or prepares. */
export function LifecycleDossierPage({ id, evaluationId, search }: { id: string; evaluationId: string; search: string }) {
  const [loaded, retry] = useLoad((signal) => fetchLifecycleDossier(id, evaluationId, signal), `dossier:${id}:${evaluationId}`);
  useEffect(() => {
    if (loaded.state !== "ready") document.title = "Dossier · Second Order";
  }, [loaded]);
  if (loaded.state === "loading") return <p className="state-panel" role="status">Loading the Dossier…</p>;
  if (loaded.state !== "ready") {
    return (
      <section className="state-panel" aria-labelledby="lifecycle-dossier-missing">
        <p className="kicker">Hypotheses</p>
        <h1 id="lifecycle-dossier-missing">{loaded.state === "missing" ? "This Dossier has not been prepared" : "It could not be shown"}</h1>
        <p className="lede">{loaded.message}</p>
        <p><Link to={assessmentHref(id, evaluationId)}>The recorded assessment</Link>{loaded.state === "error" && <> ·
          {" "}<button type="button" className="button" onClick={retry}>Try again</button></>}</p>
      </section>
    );
  }
  const data = loaded.data;
  return (
    <>
      <section className="card lifecycle-dossier-note reveal" style={order(0)} aria-labelledby="lifecycle-dossier-title">
        <p className="kicker"><Link to="/hypotheses">Hypotheses</Link> · <Link to={hypothesisHref(id)}>frozen record</Link>
          {" "}· <Link to={assessmentHref(id, evaluationId)}>recorded assessment</Link> · Dossier</p>
        <h2 id="lifecycle-dossier-title">Prepared {formatUtc(data.prepared_at)}</h2>
        <p className="freeze-note">{data.reproduction}</p>
        <ul className="lifecycle-snapshots">
          <SnapshotLine role="Baseline (bound at freeze)" status={data.snapshots.baseline} />
          <SnapshotLine role="Outcome" status={data.snapshots.outcome} />
        </ul>
      </section>
      <DossierView dossier={data.view} search={search} onRetry={retry} base={lifecycleDossierHref(id, evaluationId)} />
    </>
  );
}

function SnapshotLine({ role, status }: { role: string; status: SnapshotStatus }) {
  return (
    <li data-verifies={status.verifies}>
      <strong>{role}</strong> <code>{status.snapshot_id.slice(0, 12)}</code>: {status.verifies ? "reproducible" : "does not verify"}
      {" "}— {status.detail}
      {status.raw_source && <> Raw source: {status.raw_source.detail}</>}
    </li>
  );
}
