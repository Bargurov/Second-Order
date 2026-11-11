import type { DriverItem, EventsView, MechanismFile } from "../fuels";
import { ACTS_ON_TEXT, DRIVERS_COPY as COPY, SOURCE_COPY } from "../fuelsSituation";
import { leadAndRest } from "../fuelsText";
import { Explanation, MechanismReview, SourceList, TextList } from "./FuelsBits";
import { SectionHead } from "./CopperBits";

/** A driver: its title and the part of the barrel it acts on mainly, the mechanism's first sentence, and the rest behind
 * a disclosure with the possible direction, what changes it, what to watch and its sources. */
function DriverRow({ item }: { item: DriverItem }) {
  const [lead, rest] = leadAndRest(item.mechanism);
  return (
    <li className="fu-mech" data-driver-id={item.id} data-acts-on={item.acts_on}>
      <div className="fu-mech-head">
        <h3 className="fu-mech-title">{item.title}<Explanation /></h3>
        <p className="fu-acts">{COPY.actsOn}: <span className="fu-acts-on">{ACTS_ON_TEXT[item.acts_on]}</span></p>
      </div>
      <div className="fu-mech-text">
        <p className="fu-mech-lead">{lead}</p>
        <details className="fu-mech-more">
          <summary><span className="visually-hidden">{item.title}: </span>{COPY.more}</summary>
          {rest && <p className="fu-mech-rest">{rest}</p>}
          <h4>{COPY.direction}</h4><TextList items={item.direction} />
          <h4>{COPY.changesWhen}</h4><TextList items={item.changes_when} />
          <h4>{COPY.watch}</h4><TextList items={item.watch} />
          <h4>{SOURCE_COPY.heading}</h4><SourceList sources={item.sources} />
        </details>
      </div>
    </li>
  );
}

/** Market Drivers (spec section 5): eight standing mechanisms, each marked E, then the current-events box, which says
 * that no verified event is connected and that a driver is not a statement about current events. */
export function FuelsDrivers({ drivers, events }: { drivers: MechanismFile<DriverItem>; events: EventsView }) {
  return (
    <section id="drivers" className="ct-section fu-section" aria-labelledby="drivers-title" data-state={drivers.state}>
      <SectionHead id="drivers" kicker={COPY.kicker} title={COPY.title}>
        <p className="ct-plain">{COPY.intro}</p>
      </SectionHead>
      {drivers.state === "written" ? (
        <>
          <MechanismReview part={drivers} name="drivers" />
          <ol className="fu-mechs">{drivers.items.map((item) => <DriverRow key={item.id} item={item} />)}</ol>
        </>
      ) : <p className="fu-not-written">{COPY.notWritten}</p>}
      <aside className="fu-events" data-events={events.state} aria-labelledby="events-title">
        <p className="fu-events-k" id="events-title">{COPY.eventsHead}</p>
        <p className="fu-events-text">{events.text}</p>
      </aside>
    </section>
  );
}
