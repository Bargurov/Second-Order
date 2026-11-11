import { type Moved } from "../thesis";
import { ExposureMap } from "./ThesisExposureMap";
import { Cited, FigureLine, Placeholder, Section, StatementBlock, Withheld, type Reading } from "./ThesisSections";

/**
 * Section 8 of the thesis page, "Who is exposed": the exposure map (ThesisExposureMap), then the two exposure tables as
 * before. As in every section, a part is shown only when the server found it available, and numbers are shown as
 * served.
 */

export function ExposureSection({ r }: { r: Reading }) {
  const reasonTitle = (id: string) => r.view.reasons.find((reason) => reason.id === id)?.title ?? null;
  return (
    <Section id="exposure" plain={r.view.plain.exposure}
             note="An exposure map read from company filings, not a recommendation.">
      <ExposureMap r={r} />
      <p className="thesis-part thesis-map-tables">The same companies, in tables</p>
      <h3>Companies that move the thesis</h3>
      <p className="library-section-note">Their decisions or results move a reason.</p>
      <table className="thesis-exposure">
        <thead><tr><th scope="col">Company</th><th scope="col">Moves the reason</th><th scope="col">Through</th></tr></thead>
        <tbody>
          {r.view.exposure.movers.map((mover) => (
            <tr key={mover.id} data-mover={mover.id} data-state={mover.state}>
              <th scope="row" data-label="Company">{mover.company}</th>
              <td data-label="Moves the reason"><a href={`#reason-${mover.moves}`}>
                {reasonTitle(mover.moves) ?? <Placeholder what="The reason's title" />}</a></td>
              <td data-label="Through">{mover.state !== "available" ? <Withheld element={mover} r={r} /> : (
                <><p className="thesis-cell-text">{mover.through}</p>
                  <Cited cites={mover.cites!} figures={mover.figures!} passages={mover.passages!} r={r} /></>
              )}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3>Companies the thesis moves</h3>
      <p className="library-section-note">The side each is on, how it is exposed and how much, from its own report or
        computed from retained figures.</p>
      <table className="thesis-exposure">
        <thead><tr><th scope="col">Company</th><th scope="col">Side</th><th scope="col">How it is exposed</th>
          <th scope="col">How much</th></tr></thead>
        <tbody>
          {r.view.exposure.moved.map((moved) => {
            const side = r.view.labels.sides[moved.side];
            const cut = side.indexOf(": ");
            return (
              <tr key={moved.id} data-moved={moved.id} data-state={moved.state}>
                <th scope="row" data-label="Company">{moved.company}</th>
                <td data-label="Side"><span className="thesis-side">{cut > 0 ? side.slice(0, cut) : side}</span>
                  {cut > 0 && <span className="thesis-side-note">{side.slice(cut + 2)}</span>}</td>
                {moved.state !== "available" ? (
                  <td colSpan={2} data-label="How it is exposed"><Withheld element={moved} r={r} /></td>
                ) : (
                  <>
                    <td data-label="How it is exposed"><StatementBlock statement={moved.how!} r={r} fold /></td>
                    <td data-label="How much"><Amount moved={moved} r={r} /></td>
                  </>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </Section>
  );
}

function Amount({ moved, r }: { moved: Moved; r: Reading }) {
  const amount = moved.amount!;
  if (amount.kind === "stated") {
    return <div className="thesis-amount"><p className="thesis-part">Stated in the filing</p>
      <FigureLine figure={amount.figure} r={r} /></div>;
  }
  const inputs = [amount.per_unit, amount.price, ...(amount.unit_price ? [amount.unit_price] : [])];
  return (
    <div className="thesis-amount is-computed">
      <p className="thesis-part">Computed by fixed code</p>
      <p className="thesis-amount-result">
        <span data-computed="usd-per-unit">About {moved.usd_per_unit} USD per unit</span>
        {moved.share_pct !== null && <>, <span data-computed="share">{moved.share_pct}% of the unit price</span></>}
      </p>
      <p className="thesis-formula">
        {amount.per_unit.as_shown} kg per unit × {amount.price.as_shown} USD per tonne ÷ 1,000 kg per tonne, in whole
        dollars{amount.unit_price && <>; its share of {amount.unit_price.as_shown}, to one decimal</>}
      </p>
      <details>
        <summary>The {inputs.length} retained figures it uses</summary>
        <ul className="thesis-cited">
          {inputs.map((figure) => <li key={figure.id}><FigureLine figure={figure} r={r} /></li>)}
        </ul>
      </details>
    </div>
  );
}

