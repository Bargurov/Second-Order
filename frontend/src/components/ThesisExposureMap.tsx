import {
  CONCEPTS, LINK_WORDS, STAGE_WORDS, exposureMap, laneLabel, moverLabel, type LinkKind, type MapLane, type MapMover,
  type MoverKind,
} from "../thesisExposureMap";
import { Cited, FigureLine, Placeholder, StatementBlock, short, type Reading } from "./ThesisSections";

/**
 * The exposure map at the head of "Who is exposed": where a change in the copper price can reach each company the
 * thesis moves (its side's stages, a general mechanism), what that company's own filing states (with every figure and
 * passage it cites to inspect), and which companies' results feed a reason (the reason's measure, or related to it).
 * Built by thesisExposureMap from the reply's structured fields only. A withheld part shows its frame only: its
 * company, side and stages, or the reason it names, never its statement, figures or metric. Lines carry no arrowheads,
 * and nothing is computed here.
 */

const LINK_ORDER: LinkKind[] = ["stated", "conditional", "unmeasured"];
const MOVER_WORDS: Record<MoverKind, string> = {
  measure: "Its figure is the reason's measure",
  related: "Related; its figure is not the reason's measure",
  withheld: "Withheld until its sources check again",
};

export function ExposureMap({ r }: { r: Reading }) {
  const map = exposureMap(r.view);
  return (
    <div className="thesis-map" data-exposure-map>
      <p className="thesis-map-lead" data-map-lead>
        <strong>Who is exposed, and through what mechanism.</strong> Each lane starts from a change in the copper price,
        whatever its cause, and follows where it can reach a company's accounts; under it is what the company's own
        filing states. The thesis reads the physical balance and does not claim that the balance moves the price.
      </p>
      <dl className="thesis-map-concepts">
        {CONCEPTS.map((concept) => (
          <div key={concept.id} data-concept={concept.id}><dt>{concept.term}</dt><dd>{concept.text}</dd></div>
        ))}
      </dl>
      <div className="thesis-map-legend" data-map-legend>
        <p className="thesis-part">How the lines read</p>
        <ul>
          {LINK_ORDER.map((kind) => (
            <li key={kind} data-link={kind}>
              <span className="thesis-map-swatch" aria-hidden="true" />
              <span><strong>{LINK_WORDS[kind].name}.</strong> {LINK_WORDS[kind].what}</span>
            </li>
          ))}
        </ul>
        <p className="thesis-map-legend-note">Lines join the parts in reading order and carry no arrowheads: a line shows
          where an effect can travel, not that one part causes the next.</p>
      </div>
      <h3 id="exposure-map-lanes">Where a change in the copper price can reach</h3>
      <ol className="thesis-map-lanes" aria-labelledby="exposure-map-lanes">
        {map.lanes.map((lane) => <li key={lane.id}><Lane lane={lane} r={r} /></li>)}
      </ol>
      <h3 id="exposure-map-movers">Whose results feed a reason</h3>
      <p className="library-section-note">A company's figure measures a reason only when it is the figure the reason's
        status is read from; otherwise one company's result is related to the reason, not a measure of the market.</p>
      <ul className="thesis-map-movers" aria-labelledby="exposure-map-movers">
        {map.movers.map((mover) => <MoverLine key={mover.id} mover={mover} r={r} />)}
      </ul>
    </div>
  );
}

function Lane({ lane, r }: { lane: MapLane; r: Reading }) {
  const side = r.view.labels.sides[lane.side];
  const cut = side.indexOf(": ");
  return (
    <article className="thesis-map-lane" data-map-lane={lane.id} data-side={lane.side} data-state={lane.moved.state}
             aria-label={laneLabel(lane, r.view.labels)}>
      <header className="thesis-map-lane-head">
        <h4>{lane.company}</h4>
        <p><span className="thesis-side">{cut > 0 ? side.slice(0, cut) : side}</span>
          {cut > 0 && <span className="thesis-side-note">{side.slice(cut + 2)}</span>}</p>
      </header>
      <p className="thesis-part">Where it can reach · {LINK_WORDS.conditional.name.toLowerCase()}</p>
      <ol className="thesis-map-chain" data-link="conditional">
        <li className="thesis-map-node is-start" data-stage="price">
          <strong>A change in the copper price</strong><span>Whatever its cause.</span>
        </li>
        {lane.stages.map((stage) => (
          <li key={stage} className="thesis-map-node" data-stage={stage}>
            <strong>{STAGE_WORDS[stage].name}</strong><span>{STAGE_WORDS[stage].condition}</span>
          </li>
        ))}
      </ol>
      <details className="thesis-map-notes">
        <summary>What each stage is</summary>
        <dl>{lane.stages.map((stage) => (
          <div key={stage}><dt>{STAGE_WORDS[stage].name}</dt><dd>{STAGE_WORDS[stage].what}</dd></div>
        ))}</dl>
      </details>
      {lane.shown ? <Stated lane={lane} r={r} /> : (
        <div className="thesis-withheld" role="note" data-withheld={lane.moved.state}>
          <p className="thesis-withheld-kicker">Withheld</p>
          <p>What its filing states is not shown until its sources check again
            ({short(r.view.labels.element_states[lane.moved.state])}); the table below lists why.</p>
        </div>
      )}
      <p className="thesis-map-unmeasured" data-link="unmeasured">
        <strong>{LINK_WORDS.unmeasured.name} on this map:</strong> it computes no pass-through share, elasticity or
        profit effect, and places no stated figure on a stage; only what the filing states has a size here.
      </p>
    </article>
  );
}

/** What an available lane's statement says, with its served status: a filing's own statement, or the author's reading
 * of retained figures; the stated figure with its metric exactly as served, or a computed amount as served. */
function Stated({ lane, r }: { lane: MapLane; r: Reading }) {
  const statement = lane.statement!;
  const own = statement.status === "stated";
  return (
    <div className={`thesis-map-stated${own ? "" : " is-reading"}`} data-link={own ? "stated" : undefined}>
      <p className="thesis-part">{own ? "What its filing states" : "What the thesis reads from retained figures"}</p>
      <StatementBlock statement={statement} r={r} fold />
      {lane.stated && (
        <div className="thesis-map-figure">
          <p className="thesis-map-metric"><span className="thesis-part">The figure, as the filing names it</span>{" "}
            <span data-map-metric>{lane.metric}</span></p>
          <FigureLine figure={lane.stated} r={r} />
        </div>
      )}
      {lane.computed && (
        <p className="thesis-map-computed" data-map-computed>
          Computed by fixed code from retained figures: about {lane.computed.usdPerUnit} USD per unit
          {lane.computed.sharePct !== null && <>, {lane.computed.sharePct}% of the unit price</>}.
        </p>
      )}
    </div>
  );
}

function MoverLine({ mover, r }: { mover: MapMover; r: Reading }) {
  const measure = mover.reasonOf?.measure ?? null;
  const status = mover.reasonStatus;
  return (
    <li className="thesis-map-mover" data-map-mover={mover.id} data-kind={mover.kind} data-state={mover.mover.state}
        aria-label={moverLabel(mover)}>
      <span className="thesis-map-company">{mover.company}</span>
      <span className="thesis-map-link" data-link={mover.link ?? undefined}>{MOVER_WORDS[mover.kind]}</span>
      <span className="thesis-map-reason">
        <a href={`#reason-${mover.reason}`}>{mover.reasonTitle ?? <Placeholder what="The reason's title" />}</a>
        {status !== null && (
          <span className={`thesis-tag thesis-tag-${status}`} data-status-of={status}
                title={r.view.labels.reason_states[status]}>{short(r.view.labels.reason_states[status])}</span>
        )}
      </span>
      {mover.kind !== "withheld" && (
        <details className="thesis-map-inspect">
          <summary>Inspect what it cites, and the figure the reason is read from</summary>
          <Cited cites={mover.mover.cites!} figures={mover.mover.figures!} passages={mover.mover.passages!} r={r} />
          {measure && (
            <div className="thesis-map-measure">
              <p className="thesis-part">The figure the reason's status is read from</p>
              <FigureLine figure={measure.latest} r={r} />
            </div>
          )}
        </details>
      )}
    </li>
  );
}
