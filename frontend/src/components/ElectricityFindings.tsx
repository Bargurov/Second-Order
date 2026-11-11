import { useEffect, useRef, useState, type CSSProperties } from "react";
import { useLoad } from "../api";
import { formatUtc } from "../format";
import {
  CLASS_LABEL, SHORT, fetchElectricity, level, percent, runElectricityCheck, signed,
  type Card, type CheckResult, type Comparison, type Contributions, type ElectricityView, type MonthRow,
} from "../electricity";

const order = (i: number) => ({ "--i": i }) as CSSProperties;

/** Electricity by sector from retained EIA Table 7.6, a separate evidence type on the Findings page. Loading only reads
 * and verifies; the one explicit check computes the fixed comparisons locally. */
export function ElectricityFindings({ start }: { start: number }) {
  const [version, setVersion] = useState(0);
  const [loaded, retry] = useLoad(fetchElectricity, `electricity:${version}`);
  const [last, setLast] = useState<ElectricityView | null>(null);
  useEffect(() => {
    if (loaded.state === "ready") setLast(loaded.data);
  }, [loaded]);
  const view = loaded.state === "ready" ? loaded.data : last;
  return (
    <section className="findings-part findings-electricity" aria-labelledby="electricity-title">
      <header className="findings-part-head reveal" style={order(start)}>
        <p className="kicker">Evidence type 3 · electricity by sector</p>
        <h2 id="electricity-title">Electricity by sector (EIA Monthly Energy Review, Table 7.6)</h2>
        {view && <p className="findings-scope electricity-scope">{view.scope}</p>}
      </header>
      {!view && loaded.state === "loading" && <p className="state-panel" role="status">Reading electricity findings…</p>}
      {!view && loaded.state !== "loading" && loaded.state !== "ready" && (
        <section className="card" role="alert"><p>{loaded.message}</p>
          <button type="button" className="button" onClick={retry}>Try again</button></section>
      )}
      {view && (
        <>
          <Sources view={view} start={start + 1} onChecked={() => setVersion((value) => value + 1)} />
          {view.state === "problem" && (
            <section className="card electricity-problem" role="alert"><h3>Not shown</h3><p>{view.detail}</p></section>
          )}
          {view.state === "checked" && (
            <>
              <Months view={view} start={start + 2} />
              <Findings view={view} start={start + 3} />
              <Reconciliation view={view} start={start + 4} />
              <Method view={view} start={start + 5} />
            </>
          )}
        </>
      )}
    </section>
  );
}

function Sources({ view, start, onChecked }: { view: ElectricityView; start: number; onChecked: () => void }) {
  const [outcome, setOutcome] = useState<CheckResult | null>(null);
  const [pending, setPending] = useState(false);
  const inflight = useRef(false);
  const coverage = view.coverage;
  return (
    <section className="card electricity-check reveal" style={order(start)} aria-labelledby="electricity-check-title">
      <h3 id="electricity-check-title">Coverage and sources</h3>
      {coverage ? (
        <p className="electricity-coverage" data-last={coverage.file.monthly_last}>
          Months compared: <strong>{coverage.compared.first_label} to {coverage.compared.last_label}</strong>, each
          against the same month a year earlier ({coverage.against.first_label} to {coverage.against.last_label}), and
          {" "}{coverage.period.label} against {coverage.period.prior_label}. The retained file runs monthly from
          {" "}{coverage.file.monthly_first} to {coverage.file.monthly_last} (annual totals {coverage.file.annual_first}
          –{coverage.file.annual_last}, kept apart). {coverage.file.monthly_last_label} is the last month in that file
          as retrieved{coverage.file.retrieved_at ? ` ${formatUtc(coverage.file.retrieved_at)}` : ""}; it is not
          described here as current. Geography: {coverage.geography}</p>
      ) : (
        <p className="findings-empty">{view.state === "not_checked" && view.available
          ? "Nothing has been computed yet. The retained Table 7.6 files are available; nothing is compared until you ask."
          : view.sources_detail ?? "No retained Table 7.6 files are available."}</p>
      )}
      {view.state === "not_checked" && view.detail && <p className="findings-note">{view.detail}</p>}
      {view.sources.length > 0 && (
        <table className="findings-table electricity-sources">
          <thead><tr><th scope="col">Source</th><th scope="col">Retrieved</th><th scope="col">Edition</th>
            <th scope="col">SHA-256</th></tr></thead>
          <tbody>{view.sources.map((source) => (
            <tr key={source.kind} data-kind={source.kind}>
              <th scope="row">{source.url ? <a href={source.url} rel="noreferrer">{source.role}</a> : source.role}
                <small>{source.file ?? source.unavailable}{source.approval_id ? ` · ${source.approval_id}` : ""}</small></th>
              <td>{source.retrieved_at ? formatUtc(source.retrieved_at) : "—"}
                {source.last_modified_header && <small>Last-Modified: {source.last_modified_header}</small>}</td>
              <td>{source.kind === "landing" && source.statements
                ? `Release date ${source.statements.release_date_as_stated ?? "not readable"}; next release `
                  + `${source.statements.next_release_as_stated ?? "not stated"}`
                : source.edition ?? "None stated"}<small>{source.edition_note}</small></td>
              <td>{source.sha256 ? <code>{source.sha256.slice(0, 12)}</code> : "—"}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
      <p className="findings-note">The check reads only the Table 7.6 CSV and PDF and the Monthly Energy Review page
        kept on this computer by the approved acquisitions, verifies their recorded hashes and the CSV's series, units,
        dates and values, and computes the fixed comparisons. It makes no API call, contacts no provider and costs
        nothing; an unchanged repeat reuses the stored result.</p>
      <button type="button" className="button electricity-run" disabled={pending || !view.available} onClick={async () => {
        if (inflight.current) return;
        inflight.current = true;
        setPending(true);
        const result = await runElectricityCheck();
        inflight.current = false;
        setPending(false);
        setOutcome(result);
        if (result.state === "done") onChecked();
      }}>{pending ? "Computing…" : "Compute from retained files"}</button>
      {outcome && (
        <p className={`findings-outcome electricity-outcome is-${outcome.state}`} role="status">
          {outcome.state === "done" ? (outcome.data.created
            ? `Computed ${outcome.data.months} months locally (no API call): ${outcome.data.monthly_findings} monthly `
              + `finding${outcome.data.monthly_findings === 1 ? "" : "s"}${outcome.data.period_finding
                ? " and a January–June finding" : ""}. The result was stored.`
            : "The stored result for these files and rules was reused; nothing was written.") : outcome.message}</p>
      )}
    </section>
  );
}

/** One month's markers on a shared percentage axis, one row per sector, with the ±1% band shaded and the total as a
 * tick. Decorative; the table carries the data. */
function Strip({ row, bound }: { row: MonthRow; bound: number }) {
  const at = (value: string) => `${50 + (Number(value) / bound) * 50}%`;
  const total = row.context.find((item) => item.code === "ESTCPUS");
  return (
    <div className="electricity-strip" aria-hidden="true">
      <span className="electricity-band" style={{ left: at("-1"), right: `calc(100% - ${at("1")})` }} />
      <span className="electricity-zero" />
      {total?.percent && <span className="electricity-total" style={{ left: at(total.percent) }} />}
      {row.sectors.map((item, lane) => item.percent !== null && (
        <span key={item.code} className={`electricity-dot is-${item.class}`}
          style={{ left: at(item.percent), top: `${3 + lane * 11}px` }}>{SHORT[item.code]}</span>
      ))}
    </div>
  );
}

function Cell({ item }: { item: Comparison }) {
  return (
    <td className={`electricity-cell is-${item.class}${item.role === "context" ? " is-context" : ""}`}
      data-code={item.code}>
      {item.class === "unavailable" ? <>not available<small>{item.reason}</small></> : <>{percent(item.percent)}
        <small>{signed(item.change)}{item.role === "analyzed" ? ` · ${CLASS_LABEL[item.class]}` : ""}</small></>}
    </td>
  );
}

function Months({ view, start }: { view: ElectricityView; start: number }) {
  const values = view.months.flatMap((row) => [...row.sectors, ...row.context.filter((item) => item.code === "ESTCPUS")])
    .map((item) => Math.abs(Number(item.percent ?? 0)));
  const bound = Math.max(2, Math.ceil(Math.max(...values) + 0.5));
  return (
    <section className="card electricity-months reveal" style={order(start)} aria-labelledby="electricity-months-title">
      <h3 id="electricity-months-title">Each sector against the same month a year earlier</h3>
      <p className="findings-note">Retail sales, percentage change and change in million kWh. Up is +1% or more, down
        −1% or less, both inclusive; anything between is little changed. Transportation (railways only) and total
        retail sales are context and never enter a finding.</p>
      <ul className="electricity-legend" aria-hidden="true">
        <li><span className="electricity-dot is-key">R</span>residential <span className="electricity-dot is-key">C</span>
          commercial <span className="electricity-dot is-key">I</span>industrial</li>
        <li><span className="electricity-swatch is-up" />up</li>
        <li><span className="electricity-swatch is-down" />down</li>
        <li><span className="electricity-swatch is-little" />little changed</li>
        <li><span className="electricity-swatch is-band" />the ±1% band</li>
        <li><span className="electricity-swatch is-total" />total retail sales</li>
        <li>axis −{bound}% to +{bound}%</li>
      </ul>
      <table className="findings-table electricity-table">
        <caption>Year-over-year change by month ({view.months[0].label} to {view.months.at(-1)!.label})</caption>
        <thead><tr><th scope="col">Month</th><th scope="col">Residential</th><th scope="col">Commercial</th>
          <th scope="col">Industrial</th><th scope="col">Transportation <small>context</small></th>
          <th scope="col">Total retail sales <small>context</small></th>
          <th scope="col" className="electricity-strip-head">On one axis</th></tr></thead>
        <tbody>{view.months.map((row) => (
          <tr key={row.month} data-month={row.month} className={row.divergence.finding ? "is-finding" : undefined}>
            <th scope="row">{row.label}<small>{row.divergence.finding ? "sectors diverge" : "against "
              + row.prior_label}</small></th>
            {[...row.sectors, ...row.context].map((item) => <Cell key={item.code} item={item} />)}
            <td className="electricity-strip-cell"><Strip row={row} bound={bound} /></td>
          </tr>
        ))}</tbody>
      </table>
    </section>
  );
}

function ContributionRows({ found }: { found: Contributions }) {
  if (found.state !== "computed" || !found.rows) {
    return <p className="findings-note">Contributions not computed: {found.detail}</p>;
  }
  return (
    <table className="findings-table electricity-contributions">
      <thead><tr><th scope="col">Part of total retail sales</th><th scope="col" className="findings-num">Change,
        million kWh</th></tr></thead>
      <tbody>
        {found.rows.map((row) => (
          <tr key={row.code}><th scope="row">{row.label}{row.role === "context" && <small>context</small>}</th>
            <td className="findings-num">{signed(row.change)}</td></tr>
        ))}
        <tr><th scope="row">Rounding residual<small>independent rounding of published values</small></th>
          <td className="findings-num">{signed(found.residual_change)}</td></tr>
        <tr className="is-total"><th scope="row">Total retail sales</th>
          <td className="findings-num">{signed(found.total_change)}</td></tr>
      </tbody>
    </table>
  );
}

function FindingCard({ card }: { card: Card }) {
  return (
    <article className="card electricity-card" data-card={card.id} data-type={card.type}>
      <p className="kicker">{card.type === "month" ? "Monthly" : "January–June"} · against {card.prior_label}</p>
      <h3>{card.title}</h3>
      <h4>Observed</h4>
      <table className="findings-table electricity-observed">
        <thead><tr><th scope="col">Retail sales</th><th scope="col" className="findings-num">{card.label}</th>
          <th scope="col" className="findings-num">{card.prior_label}</th>
          <th scope="col" className="findings-num">Change, million kWh</th><th scope="col">Change</th></tr></thead>
        <tbody>{card.observed.map((item) => (
          <tr key={item.code} className={item.role === "context" ? "is-context" : `is-${item.class}`}>
            <th scope="row">{item.label}{item.role === "context" && <small>context</small>}</th>
            <td className="findings-num">{level(item.current)}</td><td className="findings-num">{level(item.prior)}</td>
            <td className="findings-num">{signed(item.change)}</td>
            <td>{percent(item.percent)}{item.role === "analyzed" && <small>{CLASS_LABEL[item.class]}</small>}</td>
          </tr>
        ))}</tbody>
      </table>
      <p className="findings-note">Source: <a href={card.source.url} rel="noreferrer">{card.source.file}</a>
        {" "}<code>{card.source.sha256.slice(0, 12)}</code>{card.source.retrieved_at
          ? `, retrieved ${formatUtc(card.source.retrieved_at)}` : ""}.</p>
      <h4>What this adds</h4>
      <p>{card.adds}</p>
      <h4>Interpretation <small>(not observed)</small></h4>
      <p className="finding-inference">{card.interpretation}</p>
      <h4>Contributions to the change in total retail sales</h4>
      <ContributionRows found={card.contributions} />
      <h4>Read with</h4>
      <ul className="electricity-disclosures">{[...card.notes, ...card.disclosures].map((item) => <li key={item}>{item}</li>)}</ul>
    </article>
  );
}

function Findings({ view, start }: { view: ElectricityView; start: number }) {
  const findings = view.findings!, period = view.period!;
  return (
    <section className="card electricity-findings reveal" style={order(start)}
      aria-labelledby="electricity-findings-title">
      <h3 id="electricity-findings-title">Sectors moving in opposite directions</h3>
      <p className="electricity-totals" data-total={findings.total}>{findings.total === 0
        ? "No month, and not the January–June comparison, had one analyzed sector up and another down. That is a valid "
          + "result of the fixed rule."
        : `${findings.monthly.length} of ${view.months.length} months had at least one analyzed sector up and another `
          + `down${findings.period ? "; so did January–June" : "; January–June did not"}.`}</p>
      <p className="findings-note">{findings.order}</p>
      <div className="electricity-cards">
        {findings.monthly.map((card) => <FindingCard key={card.id} card={card} />)}
        {findings.period && <FindingCard card={findings.period} />}
      </div>
      <h4 className="electricity-subhead">{period.label} against {period.prior_label}</h4>
      <p className="findings-note">Each sector's six months are summed before the change is computed; monthly rates
        are not averaged. {period.days_note}</p>
      <table className="findings-table electricity-period">
        <thead><tr><th scope="col">Retail sales</th><th scope="col" className="findings-num">{period.label}</th>
          <th scope="col" className="findings-num">{period.prior_label}</th><th scope="col">Change</th></tr></thead>
        <tbody>{[...period.sectors, ...period.context].map((item) => (
          <tr key={item.code} className={item.role === "context" ? "is-context" : `is-${item.class}`}>
            <th scope="row">{item.label}{item.role === "context" && <small>context</small>}</th>
            <td className="findings-num">{level(item.current)}</td><td className="findings-num">{level(item.prior)}</td>
            <td>{percent(item.percent)} <small>{signed(item.change)} million kWh{item.role === "analyzed"
              ? ` · ${CLASS_LABEL[item.class]}` : ""}</small></td>
          </tr>
        ))}</tbody>
      </table>
    </section>
  );
}

function Reconciliation({ view, start }: { view: ElectricityView; start: number }) {
  const found = view.reconciliation!;
  const beyond = found.months.filter((item) => item.state !== "within_rounding");
  return (
    <section className="card electricity-reconciliation reveal" style={order(start)}
      aria-labelledby="electricity-reconciliation-title">
      <h3 id="electricity-reconciliation-title">Do the four sectors add up to total retail sales?</h3>
      <p className="electricity-totals">{found.counts.within_rounding} of {found.months.length} months read reconcile
        within rounding (tolerance {found.tolerance} million kWh: five values each published to 0.001); largest
        residual {found.max_abs_residual ?? "—"}. {found.counts.beyond_rounding} beyond rounding,
        {" "}{found.counts.unavailable} not available.</p>
      <p className="findings-note">Residential, commercial and industrial are not the whole total: transportation and
        the rounding residual are shown beside them in every contribution table.</p>
      {beyond.length > 0 && (
        <ul className="electricity-beyond">{beyond.map((item) => (
          <li key={item.month}>{item.month}: {item.state === "unavailable" ? "a value is not available"
            : `residual ${signed(item.residual)} million kWh (sum ${level(item.sum)}, total ${level(item.total)})`}</li>
        ))}</ul>
      )}
      <details className="findings-group">
        <summary>Every month read · {found.months.length}</summary>
        <table className="findings-table electricity-residuals">
          <thead><tr><th scope="col">Month</th><th scope="col" className="findings-num">Sum of four sectors</th>
            <th scope="col" className="findings-num">Total retail sales</th><th scope="col" className="findings-num">
              Residual</th></tr></thead>
          <tbody>{found.months.map((item) => (
            <tr key={item.month} data-state={item.state}><th scope="row">{item.month}</th>
              <td className="findings-num">{level(item.sum)}</td><td className="findings-num">{level(item.total)}</td>
              <td className="findings-num">{signed(item.residual)}</td></tr>
          ))}</tbody>
        </table>
      </details>
    </section>
  );
}

function Method({ view, start }: { view: ElectricityView; start: number }) {
  const table = view.table_definitions;
  return (
    <section className="card electricity-method reveal" style={order(start)} aria-labelledby="electricity-method-title">
      <h3 id="electricity-method-title">How these are compared, and what they are not</h3>
      <p>Values are the CSV's retail sales in million kWh, compared with exact decimals for the same month a year
        earlier. The 1% band is a fixed, transparent product filter: not statistical significance, not an empirically
        calibrated threshold and not proof of materiality. Direct use, total end use and electric vehicle use are in the
        file but excluded.</p>
      <h4>Every finding is read with</h4>
      <ul className="electricity-disclosures">{view.disclosures.map((item) => <li key={item}>{item}</li>)}</ul>
      <ul className="findings-limits">{view.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
      <details className="findings-group electricity-definitions">
        <summary>{table.title} ({table.unit}): footnotes as printed</summary>
        <p className="findings-note">{table.transcribed_from.how} Bound to the PDF with SHA-256
          {" "}<code>{table.transcribed_from.sha256.slice(0, 12)}</code>; edition printed: {table.edition_printed}.</p>
        <dl className="electricity-footnotes">{Object.entries(table.footnotes).map(([mark, text]) => (
          <div key={mark}><dt>{mark}</dt><dd>{text}</dd></div>
        ))}</dl>
        <ul>{[table.markers, ...table.notes, table.web_page, table.not_retained].map((item) => <li key={item}>{item}</li>)}</ul>
      </details>
      <p className="findings-note">Stored result <code>{view.result?.result_id.slice(0, 12)}</code> under
        {" "}{view.result?.rules_version}, computed {view.result ? formatUtc(view.result.computed_at) : "—"}; read again
        now by recomputing it from the retained files, without writing.</p>
    </section>
  );
}
