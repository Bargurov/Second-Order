import type { MechanismFile, SectorItem } from "../fuels";
import { EFFECT_TEXT, SOURCE_COPY, TRANSMISSION_COPY as COPY } from "../fuelsSituation";
import { leadAndRest } from "../fuelsText";
import { Explanation, MechanismReview, SourceList, TextList } from "./FuelsBits";
import { SectionHead } from "./CopperBits";

/** A sector card. Closed, it shows the sector, the price that starts the chain and the possible effect in words with
 * the effect's first sentence; open, the chain as arrow steps that wrap, the rest of the effect, the second-order
 * effects, what can flip the direction, the lag (marked when no listed source supports it) and the sources. All
 * cards share one name, so opening one closes the others. */
function SectorCard({ item }: { item: SectorItem }) {
  const [lead, rest] = leadAndRest(item.effect_text);
  return (
    <details className="fu-sector" name="fu-sector" data-sector={item.id} data-effect={item.effect}>
      <summary>
        <span className="fu-sector-name">{item.sector}<Explanation /></span>
        <span className="fu-sector-trigger"><span className="fu-k">{COPY.startsFrom}</span> {item.trigger}</span>
        <span className="fu-sector-effect" data-effect={item.effect}>
          <span className="fu-k">{COPY.possibleEffect}: {EFFECT_TEXT[item.effect]}</span> — {lead}</span>
      </summary>
      <div className="fu-sector-body">
        <h4>{COPY.chain}</h4>
        <ol className="fu-chain">{item.chain.map((step, index) => (
          <li key={index}><span className="fu-step">{step}</span></li>))}</ol>
        {rest && <p className="fu-effect-rest">{rest}</p>}
        <h4>{COPY.secondOrder}</h4><TextList items={item.second_order} />
        <h4>{COPY.flipsWhen}</h4><TextList items={item.flips_when} />
        <h4>{COPY.lag}</h4>
        <p className="fu-lag" data-lag-sourced={String(item.lag_sourced)}>{item.lag}
          {!item.lag_sourced && <>{" "}<span className="fu-not-sourced">{COPY.notSourced}</span></>}</p>
        <h4>{SOURCE_COPY.heading}</h4><SourceList sources={item.sources} />
      </div>
    </details>
  );
}

/** Economic Transmission (spec section 5): seven conditional chains from a named fuel price to a sector, each marked E. */
export function FuelsTransmission({ transmission }: { transmission: MechanismFile<SectorItem> }) {
  return (
    <section id="transmission" className="ct-section fu-section" aria-labelledby="transmission-title"
             data-state={transmission.state}>
      <SectionHead id="transmission" kicker={COPY.kicker} title={COPY.title}>
        <p className="ct-plain">{COPY.intro}</p>
      </SectionHead>
      {transmission.state === "written" ? (
        <>
          <MechanismReview part={transmission} name="transmission" />
          <div className="fu-sectors">{transmission.items.map((item) => <SectorCard key={item.id} item={item} />)}</div>
        </>
      ) : <p className="fu-not-written">{COPY.notWritten}</p>}
    </section>
  );
}
