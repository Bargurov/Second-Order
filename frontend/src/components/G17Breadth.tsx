import type { CSSProperties } from "react";
import {
  BREADTH_CLASSES, MARKER, rate, type Breadth, type BreadthCard, type BreadthMonth, type Counts, type Switch,
} from "../g17";

const order = (i: number) => ({ "--i": i }) as CSSProperties;

/** A month's composition: one segment per class, widths proportional to counts of the 19 subsectors (not shares of
 * aggregate growth). Decorative; the counts table beside it carries the numbers. */
export function CompositionBar({ month }: { month: BreadthMonth }) {
  return (
    <span className="g17-bar" aria-hidden="true">
      {BREADTH_CLASSES.map(({ key }) => month.counts[key] > 0 && (
        <span key={key} className={`is-${key}`} style={{ width: `${(month.counts[key] / month.expected) * 100}%` }} />
      ))}
    </span>
  );
}

export function Legend() {
  return (
    <ul className="g17-legend" aria-label="Legend">
      {BREADTH_CLASSES.map(({ key, label }) => (
        <li key={key}><span className={`g17-swatch is-${key}`} aria-hidden="true" />{label}</li>
      ))}
    </ul>
  );
}

export function CountsTable({ months, caption }: { months: BreadthMonth[]; caption: string }) {
  return (
    <div className="table-scroll">
      <table className="findings-table g17-breadth-table">
        <caption>{caption}</caption>
        <thead><tr><th scope="col">Month</th><th scope="col">Composition</th><th scope="col">Up</th>
          <th scope="col">Down</th><th scope="col">0.0</th><th scope="col">Not printed</th>
          <th scope="col">Manufacturing (NAICS)</th><th scope="col">Breadth</th></tr></thead>
        <tbody>{months.map((month) => (
          <tr key={month.month} data-month={month.month}>
            <th scope="row">{month.month_label}<small>{MARKER[month.marker]}</small></th>
            <td><CompositionBar month={month} /></td>
            {BREADTH_CLASSES.map(({ key }) => (
              <td key={key} className="findings-num">{month.counts[key]}
                {month.shares && key !== "missing" && <small>{month.shares[key]}</small>}</td>
            ))}
            <td className="findings-num">{rate(month.aggregate_rate)}</td>
            <td>{month.state_text}{month.aggregate_vs_breadth && <small>aggregate against most subsectors</small>}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function SwitchList({ items, label }: { items: Switch[]; label: string }) {
  if (items.length === 0) return null;
  return (
    <p className="g17-switches"><strong>{label}:</strong> {items.map((item) => `${item.label} (${item.naics}) `
      + `${rate(item.earlier_rate)} to ${rate(item.later_rate)}`).join("; ")}.</p>
  );
}

const changeText = (change: Counts) => BREADTH_CLASSES.map(({ key }) =>
  `${key === "printed_zero" ? "0.0" : key === "missing" ? "not printed" : key === "positive" ? "up" : "down"} `
  + `${change[key] > 0 ? "+" : ""}${change[key]}`).join(", ");

function Card({ card }: { card: BreadthCard }) {
  const kicker = card.type === "aggregate_vs_breadth" ? "Aggregate against breadth"
    : card.type === "breadth_shift" ? `Within the ${card.source?.release_date_as_stated} release` : "Revision";
  return (
    <article className="card g17-card g17-breadth-card" data-card={card.id} data-type={card.type}>
      <p className="kicker">{kicker} · {card.month_label}</p>
      <h3>{card.title}</h3>
      <h4>Observed</h4>
      {card.observed && (
        <CountsTable months={card.observed} caption={`As published in the ${card.source?.release_date_as_stated} `
          + "release (Table 1)"} />
      )}
      {card.type === "aggregate_vs_breadth" && card.observed && (
        <p className="g17-switches"><strong>Printed {card.observed[0].aggregate_rate && Number(
          card.observed[0].aggregate_rate) > 0 ? "down" : "up"}:</strong> {card.observed[0].members[
          card.observed[0].aggregate_rate && Number(card.observed[0].aggregate_rate) > 0 ? "negative" : "positive"]
          .join("; ")}.</p>
      )}
      {card.type === "breadth_shift" && card.change && (
        <p className="findings-note">Change in counts: {changeText(card.change)}.</p>
      )}
      {card.type === "breadth_revision" && card.earlier && card.later && (
        <>
          <table className="findings-table g17-chain">
            <thead><tr><th scope="col">Release</th><th scope="col">Subsectors</th>
              <th scope="col">Manufacturing (NAICS)</th><th scope="col">Source</th></tr></thead>
            <tbody>{[card.earlier, card.later].map((item) => (
              <tr key={item.release}><th scope="row">{item.release_date_as_stated}<small>{MARKER[item.marker]}</small></th>
                <td>{item.counts_text}</td><td className="findings-num">{item.aggregate_rate_text}</td>
                <td><a href={item.url} rel="noreferrer">{item.table}</a> <code>{item.sha256.slice(0, 12)}</code></td></tr>
            ))}</tbody>
          </table>
          {card.change && <p className="findings-note">Change in counts: {changeText(card.change)}.</p>}
          <SwitchList items={card.reversals ?? []} label="Switched direction" />
          <SwitchList items={card.printed_zero_transitions ?? []} label="To or from a printed 0.0" />
          {card.condition && <p className="g17-switches">{card.condition}</p>}
        </>
      )}
      {card.source && (
        <p className="findings-note">Source: <a href={card.source.url} rel="noreferrer">{card.source.table}</a>,
          {" "}{card.source.release_date_as_stated} release <code>{card.source.sha256.slice(0, 12)}</code>.</p>
      )}
      <h4>What this adds</h4>
      <p>{card.adds}</p>
      <h4>Interpretation <small>(not observed)</small></h4>
      <p className="finding-inference">{card.interpretation}</p>
      {card.estimates && card.estimates.length > 1 && (
        <><h4>Estimates of this month</h4><ul className="g17-estimates">{card.estimates.map((item) => (
          <li key={item.release}>{item.release_date_as_stated} ({MARKER[item.marker]}): {item.counts_text};
            {" "}Manufacturing (NAICS) {item.aggregate_rate_text}{item.met ? " — aggregate against most subsectors" : ""}</li>
        ))}</ul></>
      )}
      {card.limitations.length > 0 && (
        <><h4>Limitations</h4><ul className="g17-limits">{card.limitations.map((item) => <li key={item}>{item}</li>)}
        </ul></>
      )}
    </article>
  );
}

const count = (n: number | undefined, word: string) => `${n ?? 0} ${word}${n === 1 ? "" : "s"}`;

/** The breadth summary of the latest retained release, with the breadth cards. Reads only. */
export function BreadthSummary({ breadth, start }: { breadth: Breadth; start: number }) {
  if (breadth.state !== "checked") {
    return (
      <section className="card g17-breadth reveal" style={order(start)} aria-labelledby="g17-breadth-title"
               role={breadth.state === "problem" ? "alert" : undefined}>
        <h3 id="g17-breadth-title">Manufacturing breadth</h3>
        <p className="findings-empty">{breadth.detail}</p>
      </section>
    );
  }
  const latest = breadth.latest!, universe = breadth.universe!, totals = breadth.totals ?? {};
  const shown = breadth.shown ?? [];
  return (
    <section className="card g17-breadth reveal" style={order(start)} aria-labelledby="g17-breadth-title">
      <h3 id="g17-breadth-title">Manufacturing breadth: {universe.expected} NAICS subsectors</h3>
      <p className="findings-note g17-universe">Counts of the {universe.durable} durable and {universe.nondurable}
        {" "}nondurable NAICS manufacturing subsectors, set against Manufacturing (NAICS). Mining, utilities and other
        (non-NAICS) manufacturing are outside this universe, and parent rows are not counted. The bars show counts of
        subsectors, not shares of aggregate growth.</p>
      <p className="g17-latest">As published in the <a href={latest.url} rel="noreferrer">
        {latest.release_date_as_stated} release</a> (the latest retained release), Table 1
        {" "}<code>{latest.sha256.slice(0, 12)}</code>.</p>
      {latest.state === "computed" ? (
        <><Legend /><CountsTable months={latest.months} caption="Subsectors by printed direction, by reference month" /></>
      ) : <p className="findings-empty" role="status">Breadth is not available for this release: {latest.detail}</p>}
      <p>{breadth.adds}</p>
      <p className="g17-totals" data-total={breadth.total}>{breadth.total === 0
        ? "No breadth finding: no month met the aggregate-against-breadth condition, no breadth shift within the latest "
          + "release and no revision changed a month's breadth."
        : `Showing ${shown.length} of ${breadth.total} breadth finding${breadth.total === 1 ? "" : "s"}`}
        {" "}({count(totals.aggregate_vs_breadth, "month")} with the aggregate against most subsectors in its latest
        estimate, {count(totals.breadth_shift, "shift")} within the latest release,
        {" "}{count(totals.breadth_revision, "revision")}).</p>
      <p className="findings-note">{breadth.order}</p>
      <div className="g17-cards">{shown.map((card) => <Card key={card.id} card={card} />)}</div>
      {(breadth.counts_unchanged_members_switched ?? 0) > 0 && (
        <p className="findings-note">In {breadth.counts_unchanged_members_switched} revised month
          {breadth.counts_unchanged_members_switched === 1 ? "" : "s"}, the counts stayed the same while subsectors
          switched direction; the full tables list them.</p>
      )}
      <ul className="findings-limits">{(breadth.limitations ?? []).map((item) => <li key={item}>{item}</li>)}</ul>
    </section>
  );
}
