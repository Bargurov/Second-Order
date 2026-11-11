import { useEffect, type CSSProperties } from "react";
import { fetchDossier, useLoad, type Loaded } from "../api";
import { LoadError, NotPrepared, Skeleton } from "../components/Chrome";
import { DossierHeader } from "../components/DossierHeader";
import { LegPanel } from "../components/LegPanel";
import { ProvenanceCard } from "../components/ProvenanceCard";
import { ReferenceHistogram } from "../components/ReferenceHistogram";
import { SeriesChart } from "../components/SeriesChart";
import { TransmissionMap } from "../components/TransmissionMap";
import { anchorPoints, verdictStatus } from "../format";
import { joinLegs } from "../join";
import { navigate } from "../router";
import { requestedLeg } from "../routes";
import type { Dossier, DossierIndex } from "../types";
import { NotFoundPage } from "./NotFoundPage";

const order = (i: number) => ({ "--i": i }) as CSSProperties;

interface Props {
  id: string;
  search: string;
  index: Loaded<DossierIndex>;
}

export function DossierPage({ id, search, index }: Props) {
  const [loaded, retry] = useLoad((signal) => fetchDossier(id, signal), id);
  if (loaded.state === "loading") return <Skeleton />;
  if (loaded.state === "missing") return <NotFoundPage index={index} what={`No dossier has the ID ${id}.`} />;
  if (loaded.state === "not-prepared") return <NotPrepared message={loaded.message} />;
  if (loaded.state === "error") return <LoadError message={loaded.message} onRetry={retry} />;
  return <DossierView dossier={loaded.data} search={search} onRetry={retry} />;
}

/** A prepared Dossier view. ``base`` is the page's own address, so selecting a leg stays on it. */
export function DossierView({ dossier, search, onRetry, base }: {
  dossier: Dossier; search: string; onRetry: () => void; base?: string;
}) {
  const legs = joinLegs(dossier);
  useEffect(() => {
    document.title = `${dossier.hypothesis.event.headline} · Second Order`;
  }, [dossier]);
  if (!legs) {
    return <LoadError message="This prepared Dossier is internally inconsistent; prepare it again." onRetry={onRetry} />;
  }
  const requested = requestedLeg(search);
  const selected = legs.find((leg) => leg.definition.id === requested) ?? legs.find((leg) => leg.definition.primary) ?? legs[0];
  const select = (legId: string) => navigate(`${base ?? `/h/${dossier.id}`}?leg=${encodeURIComponent(legId)}`,
                                            { replace: true });
  const { hypothesis, evaluation } = dossier;
  const { result, view } = selected;

  return (
    <article className="dossier">
      <DossierHeader dossier={dossier} />

      <div className="dossier-body">
        <section className="card map-card reveal" style={order(1)} aria-labelledby="map-title">
          <div className="map-intro">
            <p className="kicker">01 · Hypothesis map</p>
            <h2 id="map-title">The claimed transmission path</h2>
            <p className="card-note">
              A map of the hypothesis as frozen, not a demonstrated causal mechanism. Select a tested observable to
              inspect its leg; dashed nodes are explanatory and unscored.
            </p>
          </div>
          <div className="map-canvas">
            <TransmissionMap
              nodes={hypothesis.nodes}
              edges={hypothesis.edges}
              legs={legs}
              selectedLegId={selected.definition.id}
              onSelect={select}
            />
          </div>
          <div className="leg-tabs" role="tablist" aria-label="Tested legs">
            {legs.map((leg) => (
              <button
                key={leg.definition.id}
                type="button"
                role="tab"
                aria-selected={leg === selected}
                className={`leg-tab${leg === selected ? " is-selected" : ""}`}
                onClick={() => select(leg.definition.id)}
              >
                <span className={`dot ${verdictStatus(leg.result?.verdict ?? null).className}`} />
                {leg.definition.primary ? "Primary" : "Secondary"} · {leg.node.label}
              </button>
            ))}
          </div>
        </section>

        <div className="card leg-card reveal" style={order(2)}>
          <LegPanel leg={selected} rules={evaluation?.rules ?? null} />
        </div>

        <section className="card chart-card reveal" style={order(3)} aria-labelledby="chart-title">
          <p className="kicker">02 · Observations</p>
          <h2 id="chart-title">
            {selected.node.label}
            {view.series && <span className="unit-note"> · {view.series.quote_unit}</span>}
          </h2>
          {!result ? (
            <p className="awaiting">
              Not yet evaluated. No outcome has been recorded, so nothing after the freeze is shown or measured.
              This leg scores a {selected.definition.horizon}-session move from the scoring anchor that its
              evaluation records.
            </p>
          ) : view.series ? (
            <>
              <SeriesChart
                series={view.series}
                result={result}
                anchors={anchorPoints(result, view)}
                publishedAt={hypothesis.event.published_at}
                publishedDate={dossier.published_date}
                replay={hypothesis.evidence_class === "replay"}
              />
              {view.series.caption && <p className="provenance">{view.series.caption}</p>}
              {view.series.attribution && <p className="attribution">{view.series.attribution}</p>}
            </>
          ) : (
            <p className="empty">No observation series is available for this leg.</p>
          )}
        </section>

        <section className="card histogram-card reveal" style={order(4)} aria-labelledby="histogram-title">
          <p className="kicker">03 · Reference distribution</p>
          <h2 id="histogram-title">Where this move ranks</h2>
          {!result ? (
            <p className="awaiting">
              Not ranked yet. A reference distribution is shown only with a stored evaluation; nothing is ranked
              before then.
            </p>
          ) : view.reference ? (
            <ReferenceHistogram
              reference={view.reference}
              result={result}
              anchors={anchorPoints(result, view)}
              unit={view.unit}
              expected={selected.definition.expected}
            />
          ) : (
            <p className="empty">This leg was not ranked: {result.reason || result.verdict}.</p>
          )}
        </section>
      </div>

      {dossier.data_provenance && (
        <ProvenanceCard
          provenance={dossier.data_provenance}
          evaluation={evaluation}
          evaluationId={dossier.evaluation_id}
          style={order(5)}
        />
      )}

      <section className="limitations reveal" style={order(6)} aria-labelledby="limits-title">
        <h2 id="limits-title" className="kicker">Limitations</h2>
        <ul>
          {dossier.limitations.map((item) => (
            <li key={item.title}>
              <strong>{item.title}.</strong> {item.text}
            </li>
          ))}
        </ul>
      </section>
    </article>
  );
}
