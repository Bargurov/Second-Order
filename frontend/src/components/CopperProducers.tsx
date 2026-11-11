import { useRef, useState } from "react";
import { capitalCharge, type Action, type Panel } from "../copperActions";
import { inputKey, Latest, latest } from "../copperRequests";
import { statementDate, type CopperToolsView, type Project } from "../copperTools";
import { ComputedValue, FigureValue, Kind, LinkedQuote, LinkedValue, Plain, SectionHead } from "./CopperBits";

/** Sections 9 and 10 of the copper tools page: the published producer unit-cost comparison, what its margins can and
 * cannot establish, the company-stated projects and the capital-recovery panel (no defaults; writes nothing). */
export function CopperProducers({ view }: { view: CopperToolsView }) {
  const p = view.producers;
  const figure = (id: string | null) => <FigureValue view={view} id={id} unit={false} />;
  return (
    <>
      <section id="producers" className="library-section-block ct-section" aria-labelledby="producers-title">
        <SectionHead id="producers" kicker="09 · Producers" title={p.title}>
          <Plain>By-product credits: when a mine also earns revenue from gold or molybdenum, its net copper cost moves
            with those metals' prices, even if the mine is unchanged. Two producers are not a cost curve.</Plain>
        </SectionHead>
        <h3>Are the disclosed unit costs comparable?</h3>
        <div className="ct-table-wrap"><table className="ct-table" data-table="matrix">
          <thead><tr><th scope="col">Dimension</th><th scope="col">Freeport-McMoRan</th>
            <th scope="col">Southern Copper</th><th scope="col">Comparable?</th></tr></thead>
          <tbody>{p.matrix.map((row) => (
            <tr key={row.dimension}><th scope="row">{row.dimension}</th><td>{row.fcx}</td><td>{row.scco}</td>
              <td>{row.comparable}{row.cites.length > 0 && (
                <ul className="ct-cites">{row.cites.map((id) => (
                  <li key={id}>{view.passages[id].text === null ? "Withheld: not verified"
                    : <q>{view.passages[id].text}</q>}</li>))}</ul>)}</td></tr>))}</tbody>
        </table></div>
        <h3>The comparison, 2025, US dollars per pound of copper</h3>
        <div className="ct-table-wrap"><table className="ct-table" data-table="costs">
          <thead><tr><th scope="col">Producer, division</th><th scope="col">Method</th><th scope="col">Before credits</th>
            <th scope="col">By-product credits</th><th scope="col">Other charges</th><th scope="col">Unit net cash cost</th>
            <th scope="col">Co-product method</th><th scope="col">Revenue per pound</th><th scope="col">Volume, million lb</th>
          </tr></thead>
          <tbody>{p.rows.map((row) => (
            <tr key={row.id} data-row={row.id} data-state={row.state}>
              <th scope="row">{row.producer}, {row.division}</th><td>{row.method}</td>
              {row.state === "available" ? (
                <>
                  <td>{figure(row.figures.before)}</td>
                  <td>{row.figures.credits.length ? row.figures.credits.map((id) => <span key={id}>{figure(id)}</span>) : "—"}</td>
                  <td>{row.figures.other.length ? row.figures.other.map((id) => (
                    <span key={id} className="ct-charge">{view.figures[id].measure.split(": ").pop()}: {figure(id)}</span>))
                    : row.figures.excluded ? <>Excluded idle-facility and recovery costs: {figure(row.figures.excluded)}</>
                    : "In the figure before credits"}</td>
                  <td className="ct-total">{figure(row.figures.net)}</td>
                  <td>{row.figures.co_product ? figure(row.figures.co_product) : "Not published"}</td>
                  <td>{row.figures.revenue ? figure(row.figures.revenue) : <span className="ct-missing">Not retained
                    <Kind kind="missing" title="Missing: not among the retained figures" /></span>}</td>
                  <td>{figure(row.figures.volume)}</td>
                </>) : <td colSpan={7} className="ct-withheld">Withheld: {row.problem}</td>}
            </tr>))}</tbody>
        </table></div>
        <p className="ct-note">Each row's figures add up exactly (before credits, plus credits, plus charges, equals the
          stated unit net cash cost) or the row is withheld. Rows are not ranked or averaged.</p>
      </section>

      <section id="margins" className="library-section-block ct-section" aria-labelledby="margins-title">
        <SectionHead id="margins" kicker="10 · Margins, capital and time" title="What margins can and cannot tell us">
          <Plain>These are averages across each company's mines, measured the company's way; they show that average
            revenue was above average reported cash cost in 2025, not which mines could close. A new mine must also repay
            its capital, which is spent years before its first tonne.</Plain>
        </SectionHead>
        <div className="ct-table-wrap"><table className="ct-table" data-table="margins">
          <thead><tr><th scope="col">Division</th><th scope="col">Reported average revenue minus reported average unit
            cash cost, $/lb</th><th scope="col">Company's own gross profit per pound (after depreciation)</th></tr></thead>
          <tbody>{p.margins.map((margin) => {
            const row = p.rows.find((item) => item.id === margin.row)!;
            return (
              <tr key={margin.row} data-margin={margin.row} data-state={margin.state}>
                <th scope="row">{row.producer}, {row.division}</th>
                <td>{margin.state === "not_retained" ? <span className="ct-missing">{margin.problem}</span>
                  : <ComputedValue item={margin} />}</td>
                <td>{margin.gross_profit ? figure(margin.gross_profit) : "—"}</td>
              </tr>);
          })}</tbody>
        </table></div>
        <p className="ct-note">These are division averages, not any mine's avoidable cost.</p>
        <p className="policy-label">What this can establish</p>
        <p>{p.can_establish}</p>
        <p className="policy-label">What this cannot establish</p>
        <ul className="ct-cannot">{p.cannot_establish.map((text) => <li key={text}>{text}</li>)}</ul>
        <h3>Company-stated projects</h3>
        <div className="ct-table-wrap"><table className="ct-table" data-table="projects">
          <thead><tr><th scope="col">Project</th><th scope="col">Type</th><th scope="col">Stated capacity</th>
            <th scope="col">Stated capital</th><th scope="col">Capital per tonne of annual capacity, US$</th>
            <th scope="col">Timing and conditions, as stated</th><th scope="col">Company-stated incentive price</th>
            <th scope="col">Break-even economics, as stated</th>
          </tr></thead>
          <tbody>{p.projects.map((project) => <ProjectRow key={project.id} view={view} project={project} />)}</tbody>
        </table></div>
        <p className="ct-note" data-note="incentive_break_even">{p.notes.incentive_break_even}</p>
        <p className="ct-note" data-note="no_path">{p.notes.no_path}</p>
        <Plain>{p.brownfield_greenfield}</Plain>
        <CapitalPanel view={view} />
      </section>
    </>
  );
}

const CAVEATS_LABEL = "Company caveats";

/** A row's stamp: which company statement it is, when and in which document (Bagdad only). */
function StatementStamp({ view, project }: { view: CopperToolsView; project: Project }) {
  const s = project.statement;
  if (s === null) return null;
  return (
    <>
      <span className="ct-statement" data-statement={s.kind}>
        {`${s.text} · ${s.date_text} ${statementDate(s.date)} · ${s.document}`}</span>
      {s.terms && <span className="ct-terms" data-terms>Source terms: {s.terms}</span>}
      {s.kind === "company_estimates" && view.linked.problem &&
        <span className="ct-withheld" data-linked-problem>{view.linked.problem}</span>}
    </>
  );
}

function ProjectRow({ view, project }: { view: CopperToolsView; project: Project }) {
  const linked = (id: string) => id in view.linked.records;
  const figure = (id: string) => linked(id)
    ? <span key={id} className="ct-stated"><LinkedValue view={view} id={id} /></span>
    : <span key={id} className="ct-stated">{view.figures[id].measure.split(": ").pop()}:{" "}
      <FigureValue view={view} id={id} /></span>;
  const quote = (id: string) => linked(id) ? <LinkedQuote view={view} id={id} />
    : view.passages[id].text === null ? "Withheld: not verified" : <q>{view.passages[id].text}</q>;
  const decisions = project.passages.filter((id) => view.linked.records[id]?.role === "decision");
  const others = project.passages.filter((id) => !decisions.includes(id));
  return (
    <tr data-project={project.id}>
      <th scope="row">{project.name} ({project.company})<StatementStamp view={view} project={project} /></th>
      <td>{project.type_text}</td>
      <td>{project.capacity.map((id) => (
        <span key={id} className="ct-stated">{figure(id)}{project.capacity_label && <> · {project.capacity_label}</>}
        </span>))}{project.by_product && figure(project.by_product)}</td>
      <td>{project.capital ? figure(project.capital) : <span className="ct-missing">Not stated
        <Kind kind="missing" title="Missing: the company states no capital" /></span>}
        {project.earlier_capital && figure(project.earlier_capital)}
        {project.caveats.length > 0 && <div className="ct-caveats" data-caveats>
          <p className="policy-label">{CAVEATS_LABEL}</p>
          <ul className="ct-cites">{project.caveats.map((id) => <li key={id}>{quote(id)}</li>)}</ul></div>}</td>
      <td>{project.capital_per_annual_tonne.length > 0 ? project.capital_per_annual_tonne.map((item, n) => (
        <span key={n} className="ct-stated"><ComputedValue item={item} /></span>)) : project.intensity_problem}</td>
      <td><ul className="ct-cites">
        {decisions.map((id) => <li key={id}>{quote(id)}</li>)}
        {project.construction && <li>Construction: <LinkedValue view={view} id={project.construction} /></li>}
        {others.map((id) => <li key={id}>{quote(id)}</li>)}
      </ul></td>
      <td>{project.incentive.length > 0 ? project.incentive.map(figure) : "Not stated"}</td>
      <td data-break-even>{project.break_even.length > 0 ? project.break_even.map((id) => (
        <span key={id} className="ct-stated"><LinkedValue view={view} id={id} /> copper
          {project.break_even_condition && <>, at <LinkedValue view={view} id={project.break_even_condition} />
            {" "}molybdenum</>}</span>)) : "Not stated"}</td>
    </tr>
  );
}

function CapitalPanel({ view }: { view: CopperToolsView }) {
  const panel = view.producers.capital_panel;
  const [rate, setRate] = useState("");
  const [years, setYears] = useState("");
  // A reply is kept with the inputs it was computed for and shown only while they are still the inputs.
  const [answer, setAnswer] = useState<{ key: string; reply: Action<Panel> } | null>(null);
  const [busy, setBusy] = useState(false);
  const gate = useRef(new Latest());
  const key = inputKey({ rate: rate.trim(), years: years.trim() });
  const currentKey = useRef(key);
  currentKey.current = key;
  const names = Object.fromEntries(view.producers.projects.map((project) => [project.id, project]));
  /** An input changed: a reply in flight or on screen no longer answers the inputs, so neither is used. */
  const changed = () => { gate.current.invalidate(); setAnswer(null); setBusy(false); };
  async function compute() {
    const [sentRate, sentYears] = [rate.trim(), years.trim()];
    setBusy(true);
    const outcome = await latest(gate.current, key, () => currentKey.current,
                                 () => capitalCharge(view, sentRate, sentYears));
    if (!outcome.used) return;  // Superseded or sent for other inputs: never shown.
    setAnswer({ key, reply: outcome.value });
    setBusy(false);
  }
  const reply = answer !== null && answer.key === key ? answer.reply : null;
  return (
    <div className="ct-panel" data-panel="capital">
      <h3>Capital recovery, with a rate and a life you enter</h3>
      <p className="ct-note">An illustration with no defaults. For a rate r of zero or more and a whole number of years n,
        the yearly capital charge is the capital times CRF(r, n) = r(1 + r)<sup>n</sup> / ((1 + r)<sup>n</sup> − 1); at a
        zero rate CRF is 1/n, the capital recovered evenly with no return. It ignores {panel.ignores.join(", ")}. It is
        not a price of any kind, and nothing you enter is stored.</p>
      <p className="ct-actions">
        <label className="ct-inline">Rate, % <input type="text" inputMode="decimal" value={rate} title={panel.rate_rule}
          onChange={(event) => { setRate(event.target.value); changed(); }} /></label>
        <label className="ct-inline">Life, years <input type="text" inputMode="numeric" value={years}
          title={panel.years_rule} onChange={(event) => { setYears(event.target.value); changed(); }} /></label>
        <button type="button" className="button" disabled={busy || rate.trim() === "" || years.trim() === ""}
                onClick={compute}>Compute the capital charge</button>
      </p>
      {reply && reply.state !== "ready" && <p role="alert" className="ct-error">{reply.message}</p>}
      {reply?.state === "ready" && (
        <div data-panel-result={reply.data.method}>
          <p>CRF({reply.data.rate_pct}%, {reply.data.years}) = {reply.data.crf}
            <Kind kind="computed" title={`Computed · E14 · ${reply.data.method === "limit_at_zero_rate"
              ? "zero rate: 1/n" : "annuity"} · rounded for display`} />
            {reply.data.method === "limit_at_zero_rate" && " (zero rate: the capital recovered evenly, 1/n a year)"}
            <Kind kind="assumption" title="Assumption: the rate and the life are yours" /></p>
          <div className="ct-table-wrap"><table className="ct-table" data-table="charges">
            <thead><tr><th scope="col">Project</th><th scope="col">Capital charge per pound of stated capacity, $/lb</th>
            </tr></thead>
            <tbody>{reply.data.projects.map((row) => (
              <tr key={row.project} data-charge-project={row.project}><th scope="row">{names[row.project]?.name}
                {names[row.project]?.statement && <> · {names[row.project]?.statement?.text}</>}</th>
                <td>{row.charges.length ? row.charges.map((charge, n) => (
                  <span key={n} className="ct-stated">{charge.shown === null ? "Withheld"
                    : <>≈ {charge.shown}<Kind kind="computed" title="Computed · E14 · rounded for display" /></>}</span>))
                  : row.problem}</td></tr>))}</tbody>
          </table></div>
        </div>)}
    </div>
  );
}
