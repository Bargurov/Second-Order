import { useEffect, useRef, useState, type CSSProperties } from "react";
import { useLoad } from "../api";
import { formatUtc } from "../format";
import { level, percent, signed } from "../electricity";
import {
  CLASS_LABEL, CLASSES, KIND_NOTE, fetchCrossSource, printed, runCrossSourceCheck,
  type CheckResult, type ComparisonText, type CrossSourceView, type EiaChange, type G17Cell,
} from "../crossSource";

const order = (i: number) => ({ "--i": i }) as CSSProperties;
const SECTION_ANCHOR: Record<string, string> = { electricity: "#electricity-title", g17: "#g17-title" };

/** Descriptive comparisons across the retained G.17 and EIA sources, a separate part of the Findings page. Loading only
 * reads and verifies; the one explicit action computes them locally. */
export function CrossSourceComparisons({ start }: { start: number }) {
  const [version, setVersion] = useState(0);
  const [loaded, retry] = useLoad(fetchCrossSource, `cross-source:${version}`);
  const [last, setLast] = useState<CrossSourceView | null>(null);
  useEffect(() => {
    if (loaded.state === "ready") setLast(loaded.data);
  }, [loaded]);
  const view = loaded.state === "ready" ? loaded.data : last;
  return (
    <section className="findings-part findings-cross" aria-labelledby="cross-title">
      <header className="findings-part-head reveal" style={order(start)}>
        <p className="kicker">Cross-source · G.17 and EIA Table 7.6, side by side</p>
        <h2 id="cross-title">Cross-source comparisons</h2>
        {view && <p className="findings-scope cross-scope">{view.scope}</p>}
      </header>
      {!view && loaded.state === "loading" && <p className="state-panel" role="status">Reading comparisons…</p>}
      {!view && loaded.state !== "loading" && loaded.state !== "ready" && (
        <section className="card" role="alert"><p>{loaded.message}</p>
          <button type="button" className="button" onClick={retry}>Try again</button></section>
      )}
      {view && (
        <>
          <Action view={view} start={start + 1} onChecked={() => setVersion((value) => value + 1)} />
          {view.state === "problem" && (
            <section className="card cross-problem" role="alert"><h3>Not shown</h3><p>{view.detail}</p></section>
          )}
          {view.state === "checked" && view.comparisons && (
            <>
              <Industrial view={view} start={start + 2} />
              <Utility view={view} start={start + 3} />
              <Limits view={view} start={start + 4} />
            </>
          )}
        </>
      )}
    </section>
  );
}

function Action({ view, start, onChecked }: { view: CrossSourceView; start: number; onChecked: () => void }) {
  const [outcome, setOutcome] = useState<CheckResult | null>(null);
  const [pending, setPending] = useState(false);
  const inflight = useRef(false);
  const sources = view.sources;
  return (
    <section className="card cross-action reveal" style={order(start)} aria-labelledby="cross-action-title">
      <h3 id="cross-action-title">Sources and coverage</h3>
      {sources ? (
        <p className="cross-coverage">The retained EIA file runs monthly from {sources.eia.monthly_first} to
          {" "}{sources.eia.monthly_last} (retrieved {sources.eia.retrieved_at ? formatUtc(sources.eia.retrieved_at) : "—"};
          {" "}{sources.eia.edition_note}) Each G.17 value comes from the release named beside it:
          {" "}{sources.g17.map((item) => item.release_date_as_stated).join(", ")}. A period the EIA file does not reach is
          shown as not covered; no other month is used in its place.</p>
      ) : (
        <p className="findings-empty">{view.state === "not_checked" && view.available
          ? "Nothing has been computed yet. Both retained sources are available; nothing is compared until you ask."
          : view.sources_detail ?? "The retained sources are not available."}</p>
      )}
      {view.state === "not_checked" && view.detail && <p className="findings-note">{view.detail}</p>}
      <p className="findings-note">The action reads only the G.17 Table 1 pages and the EIA Table 7.6 files kept on this
        computer by the approved acquisitions, verifies their recorded hashes and structure, and computes the
        comparisons. It makes no API call, contacts no provider and costs nothing; an unchanged repeat reuses the stored
        result.</p>
      <button type="button" className="button cross-run" disabled={pending || !view.available} onClick={async () => {
        if (inflight.current) return;
        inflight.current = true;
        setPending(true);
        const result = await runCrossSourceCheck();
        inflight.current = false;
        setPending(false);
        setOutcome(result);
        if (result.state === "done") onChecked();
      }}>{pending ? "Computing…" : "Compute from retained files"}</button>
      {outcome && (
        <p className={`findings-outcome cross-outcome is-${outcome.state}`} role="status">
          {outcome.state === "done" ? (outcome.data.created
            ? `Computed ${outcome.data.periods} periods locally (no API call). The result was stored.`
            : "The stored result for these files and rules was reused; nothing was written.") : outcome.message}</p>
      )}
    </section>
  );
}

function EiaCell({ item }: { item: EiaChange }) {
  if (item.state !== "computed") {
    return <td className={`cross-cell is-${item.state}`}>{item.state === "not_covered" ? "Not covered" : "Unavailable"}
      <small>{item.reason}</small></td>;
  }
  return <td className="cross-cell findings-num">{percent(item.percent)}<small>{signed(item.change)} million kWh</small>
  </td>;
}

function G17Value({ cell }: { cell: G17Cell }) {
  if (cell.state === "not_printed") return <td className="cross-cell is-unavailable">Not printed<small>no retained
    release prints this period</small></td>;
  const status = cell.marker === "p" ? "preliminary" : cell.marker === "r" ? "revised" : "no marker printed";
  return (
    <td className="cross-cell findings-num">{cell.state === "blank" ? "blank" : printed(cell.value)}
      <small>{cell.release_date_as_stated} release · {status}{cell.vintages_differ ? " · other releases differ" : ""}
      </small></td>
  );
}

function Header({ text, link }: { text: ComparisonText; link?: boolean }) {
  return (
    <>
      <h3>{text.title}</h3>
      <p className="cross-question">{text.question}</p>
      <dl className="cross-measures">
        <div><dt>EIA</dt><dd>{text.eia_measure}</dd></div>
        <div><dt>G.17</dt><dd>{text.g17_measure}</dd></div>
      </dl>
      {link !== false && <p className="findings-note">See also <a href={SECTION_ANCHOR[text.link.section]}>
        {text.link.label}</a> and <a href={SECTION_ANCHOR[text.link_g17.section]}>{text.link_g17.label}</a>.</p>}
    </>
  );
}

function Differences({ text }: { text: ComparisonText }) {
  return (
    <>
      <h4>Not the same measurement</h4>
      <ul className="cross-list">{text.differences.map((item) => <li key={item}>{item}</li>)}</ul>
      {text.possibilities.length > 0 && (
        <>
          <h4>Possibilities <small>(not established by these observations)</small></h4>
          <ul className="cross-list cross-possible">{text.possibilities.map((item) => <li key={item}>{item}</li>)}</ul>
          <p className="findings-note">{text.possibilities_note}</p>
        </>
      )}
    </>
  );
}

function Sources({ cells }: { cells: { period: string; label: string; g17: G17Cell; eia: EiaChange }[] }) {
  return (
    <details className="findings-group cross-provenance">
      <summary>Source of each value</summary>
      <table className="findings-table">
        <thead><tr><th scope="col">Period</th><th scope="col">G.17 cell</th><th scope="col">EIA calculation</th></tr>
        </thead>
        <tbody>{cells.map((row) => (
          <tr key={row.period}><th scope="row">{row.label}</th>
            <td>{row.g17.state === "not_printed" ? "—" : <>{row.g17.path} ({row.g17.naics}) · {row.g17.column}
              <small><a href={row.g17.url} rel="noreferrer">Table 1, {row.g17.release_date_as_stated}</a>
                {" "}<code>{row.g17.sha256?.slice(0, 12)}</code>{row.g17.vintages.length > 1 ? " · printed: "
                + row.g17.vintages.map((v) => `${v.release_date_as_stated} ${printed(v.value)}`).join("; ") : ""}
              </small></>}</td>
            <td>{row.eia.code}: {row.eia.months.join(", ")} against {row.eia.prior_months.join(", ")}
              <small>{row.eia.state === "computed" ? `${level(row.eia.current)} against ${level(row.eia.prior)} million kWh`
                : row.eia.reason}</small></td>
          </tr>
        ))}</tbody>
      </table>
    </details>
  );
}

function Industrial({ view, start }: { view: CrossSourceView; start: number }) {
  const text = view.comparisons_text.industrial_vs_manufacturing;
  const rows = view.comparisons!.industrial_vs_manufacturing;
  return (
    <section className="card cross-card reveal" style={order(start)} data-comparison="industrial_vs_manufacturing">
      <Header text={text} />
      <table className="findings-table cross-table">
        <thead><tr><th scope="col">Period</th><th scope="col" className="findings-num">EIA industrial retail sales</th>
          <th scope="col" className="findings-num">G.17 Manufacturing (NAICS) output</th>
          <th scope="col">Signs <small>(sign only)</small></th></tr></thead>
        <tbody>{rows.map((row) => (
          <tr key={row.period} data-period={row.period} className={`is-${row.signs}`}>
            <th scope="row">{row.label}</th>
            <EiaCell item={row.eia} /><G17Value cell={row.g17} />
            <td className="cross-signs">{view.sign_labels[row.signs]}</td>
          </tr>
        ))}</tbody>
      </table>
      <p className="findings-note">{KIND_NOTE.fourth_quarter} {KIND_NOTE.twelve_month}</p>
      <p className="findings-note">{view.sign_note}</p>
      <Differences text={text} />
      <Sources cells={rows.map((row) => ({ period: row.period, label: row.label, g17: row.g17, eia: row.eia }))} />
    </section>
  );
}

function Utility({ view, start }: { view: CrossSourceView; start: number }) {
  const text = view.comparisons_text.utility_output_and_customers;
  const rows = view.comparisons!.utility_output_and_customers;
  return (
    <section className="card cross-card reveal" style={order(start)} data-comparison="utility_output_and_customers">
      <Header text={text} />
      <table className="findings-table cross-table">
        <thead><tr><th scope="col">Period</th><th scope="col" className="findings-num">G.17 Electric utility output</th>
          <th scope="col" className="findings-num">EIA total retail sales</th>
          {CLASSES.map((code) => <th key={code} scope="col" className="findings-num">{CLASS_LABEL[code]}
            <small>million kWh</small></th>)}
          <th scope="col" className="findings-num">Rounding residual</th></tr></thead>
        <tbody>{rows.map((row) => (
          <tr key={row.period} data-period={row.period}>
            <th scope="row">{row.label}</th>
            <G17Value cell={row.g17} /><EiaCell item={row.eia_total} />
            {row.breakdown.state === "computed" ? (
              <>{CLASSES.map((code) => (
                <td key={code} className="findings-num">{signed(row.breakdown.sectors![code])}
                  <small>{percent(row.eia_classes[code].percent)}</small></td>
              ))}<td className="findings-num">{signed(row.breakdown.residual_change)}</td></>
            ) : <td colSpan={CLASSES.length + 1} className="cross-cell is-unavailable">Breakdown not computed
              <small>{row.breakdown.detail}</small></td>}
          </tr>
        ))}</tbody>
      </table>
      <p className="findings-note">{KIND_NOTE.fourth_quarter} {KIND_NOTE.twelve_month}</p>
      <p className="findings-note">The four classes and the rounding residual add up to the change in EIA total retail
        sales. G.17 utility output is shown beside them, not decomposed by them.</p>
      <Differences text={text} />
      <Sources cells={rows.map((row) => ({ period: row.period, label: row.label, g17: row.g17, eia: row.eia_total }))} />
    </section>
  );
}

function Limits({ view, start }: { view: CrossSourceView; start: number }) {
  return (
    <section className="card cross-limits reveal" style={order(start)} aria-labelledby="cross-limits-title">
      <h3 id="cross-limits-title">Read with</h3>
      <ul className="cross-list">{view.common_limitations.map((item) => <li key={item}>{item}</li>)}</ul>
      <p className="findings-note">Stored result <code>{view.result?.result_id.slice(0, 12)}</code> under
        {" "}{view.result?.rules_version}, computed {view.result ? formatUtc(view.result.computed_at) : "—"}; read again
        now by recomputing it from the retained files, without writing.</p>
    </section>
  );
}
