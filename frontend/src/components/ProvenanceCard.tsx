import type { CSSProperties, ReactNode } from "react";
import { NOT_EVALUATED, formatUtc, shortHash, vintageLabel } from "../format";
import type { DataProvenance, Evaluation, SnapshotSummary } from "../types";

interface Props {
  provenance: DataProvenance;
  evaluation: Evaluation | null;
  evaluationId: string | null;
  style?: CSSProperties;
}

const cell = (snapshot: SnapshotSummary | null, pick: (snapshot: SnapshotSummary) => ReactNode, missing: string) =>
  snapshot ? pick(snapshot) : <span className="muted">{missing}</span>;

/** The pinned snapshots, recorded rules and measurement convention behind a store-backed Dossier. */
export function ProvenanceCard({ provenance, evaluation, evaluationId, style }: Props) {
  const { baseline, outcome } = provenance;
  const rows: [string, (snapshot: SnapshotSummary) => ReactNode, string][] = [
    ["Snapshot ID", (snapshot) => <code className="full-id">{snapshot.snapshot_id}</code>, "Not yet named"],
    ["Vintage date", (snapshot) => vintageLabel(snapshot.vintage_date), "—"],
    ["Retrieved", (snapshot) => formatUtc(snapshot.retrieved_at), "—"],
    ["Adapter", (snapshot) => snapshot.adapter_version, "—"],
  ];
  return (
    <section className="card provenance-card reveal" style={style} aria-labelledby="provenance-title">
      <p className="kicker">04 · Data provenance</p>
      <h2 id="provenance-title">Pinned {provenance.provider} snapshots</h2>
      <p className="card-note">{provenance.measurement_convention}</p>
      <div className="table-scroll">
        <table className="snapshot-table">
          <thead>
            <tr>
              <th scope="col"><span className="visually-hidden">Field</span></th>
              <th scope="col">Baseline · bound at freeze</th>
              <th scope="col">Outcome · named at evaluation</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([label, pick, missing]) => (
              <tr key={label}>
                <th scope="row">{label}</th>
                <td>{cell(baseline, pick, missing)}</td>
                <td>{cell(outcome, pick, missing)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <dl className="ledger provenance-ledger">
        <div>
          <dt>Evaluation ID</dt>
          <dd title={evaluationId ?? undefined}>{evaluationId ? shortHash(evaluationId, 12) : NOT_EVALUATED}</dd>
        </div>
        <div>
          <dt>Recorded rules</dt>
          <dd title={evaluation?.rules_hash}>
            {evaluation ? `${evaluation.rules.version} · ${shortHash(evaluation.rules_hash, 10)}` : "Recorded at evaluation"}
          </dd>
        </div>
      </dl>
      <p className="attribution">{provenance.attribution}</p>
    </section>
  );
}
