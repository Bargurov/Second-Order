import { useEffect, type CSSProperties } from "react";
import { useLoad } from "../api";
import { formatUtc } from "../format";
import {
  MARKER, RELATION, STEP, fetchG17Tables, rate, rowName, type Comparison, type G17Tables,
} from "../g17";
import { CountsTable, Legend } from "../components/G17Breadth";
import { Link } from "../router";
import "../insights.css";

const order = (i: number) => ({ "--i": i }) as CSSProperties;

/** Every comparison and revision chain of the latest G.17 check, verified by the server. Reads only. */
export function G17TablesPage() {
  const [loaded, retry] = useLoad(fetchG17Tables, "g17-tables");
  useEffect(() => {
    document.title = "Industry comparisons · Findings · Second Order";
  }, []);
  return (
    <article className="findings g17-tables">
      <header className="findings-header reveal" style={order(0)}>
        <p className="kicker"><Link to="/findings">Findings</Link> · industrial production (G.17)</p>
        <h1>All industry comparisons and revision chains</h1>
        <p className="lede">Every comparison of the latest check and every published estimate of each industry row,
          release by release. Cards on the Findings page are a selection of these.</p>
      </header>
      {loaded.state === "loading" && <p className="state-panel" role="status">Reading stored comparisons…</p>}
      {(loaded.state === "error" || loaded.state === "missing") && (
        <section className="card" role="alert"><p>{loaded.message}</p>
          {loaded.state === "error" && <button type="button" className="button" onClick={retry}>Try again</button>}
          <p><Link to="/findings">Back to Findings</Link></p></section>
      )}
      {loaded.state === "ready" && <Tables data={loaded.data} />}
    </article>
  );
}

function Tables({ data }: { data: G17Tables }) {
  return (
    <>
      <section className="card reveal" style={order(1)} aria-labelledby="g17-sources-title">
        <h2 id="g17-sources-title">Releases and sources</h2>
        <p className="findings-note">Checked {formatUtc(data.check.checked_at)}. Archived release pages are compared as
          the versions published on their release dates; matching archived pages do not prove the historical bytes are
          unchanged. Release dates are as published, with no time zone stated.</p>
        <div className="table-scroll">
          <table className="findings-table g17-provenance">
            <thead><tr><th scope="col">Release</th><th scope="col">Source</th><th scope="col">SHA-256</th>
              <th scope="col">Retrieved</th><th scope="col">Consistency with the release summary</th></tr></thead>
            <tbody>{data.releases.flatMap((release) => release.sources.map((source, index) => (
              <tr key={source.file}>
                {index === 0 && <th scope="row" rowSpan={release.sources.length}>{release.release_date_as_stated}
                  {release.library && <small><Link to={release.library.href}>Library case</Link></small>}</th>}
                <td><a href={source.url} rel="noreferrer">{source.role}</a><small>{source.approval_id}</small></td>
                <td><code>{source.sha256}</code></td>
                <td>{source.retrieved_at ? formatUtc(source.retrieved_at) : "—"}</td>
                {index === 0 && <td rowSpan={release.sources.length}>{release.consistency.every((item) => item.equal)
                  ? `${release.consistency.length} rows equal in all months` : "differs"}</td>}
              </tr>
            )))}</tbody>
          </table>
        </div>
      </section>
      {data.releases.map((release, index) => (
        <Release key={release.release} release={release} index={index} />
      ))}
      <Chains data={data} />
      <BreadthTables data={data} />
    </>
  );
}

const RELATION_CLASS: Record<string, string> = {
  opposing: "is-opposing", same: "is-same", no_direction: "is-quiet", unavailable: "is-missing",
};

function Release({ release, index }: { release: G17Tables["releases"][number]; index: number }) {
  const comparisons = release.comparisons ?? [];
  const pairs = [...new Map(comparisons.map((item) => [`${item.row}|${item.parent}`, item])).values()];
  const cell = (pair: Comparison, month: string) => comparisons.find((item) => item.row === pair.row &&
    item.parent === pair.parent && item.month === month);
  return (
    <details className="card g17-release reveal" style={order(2 + index)} data-release={release.release}
             open={index === 0}>
      <summary><h2>{release.release_date_as_stated} release: comparisons</h2>
        <span className="findings-note">opposing {release.counts?.opposing ?? 0}, same {release.counts?.same ?? 0},
          no direction {release.counts?.no_direction ?? 0}, not printed {release.counts?.unavailable ?? 0}</span>
      </summary>
      <div className="table-scroll">
        <table className="findings-table g17-matrix">
          <thead><tr><th scope="col">Row against parent</th>{release.months.map((month) => (
            <th scope="col" key={month.key}>{month.label}<small>{MARKER[month.marker]}</small></th>
          ))}</tr></thead>
          <tbody>{pairs.map((pair) => (
            <tr key={`${pair.row}|${pair.parent}`}>
              <th scope="row">{rowName(pair.row, pair.row_naics)}<small>against {rowName(pair.parent, null)}</small></th>
              {release.months.map((month) => {
                const item = cell(pair, month.key);
                return item ? (
                  <td key={month.key} className={RELATION_CLASS[item.relation]} title={RELATION[item.relation]}>
                    {rate(item.row_rate)} / {rate(item.parent_rate)}<small>{RELATION[item.relation]}</small></td>
                ) : <td key={month.key}>—</td>;
              })}
            </tr>
          ))}</tbody>
        </table>
      </div>
    </details>
  );
}

function Chains({ data }: { data: G17Tables }) {
  return (
    <section className="card g17-chains reveal" style={order(6)} aria-labelledby="g17-chains-title">
      <h2 id="g17-chains-title">Published estimates by row and month</h2>
      <p className="findings-note">Each cell lists every selected release's printed estimate of that month, oldest
        release first ([p] marks a preliminary estimate; the others are revised), then the kind of each change between
        consecutive releases: reversed (the printed direction changed), to or from 0.0 (a printed 0.0 has no
        direction), revised (same direction, new value) or unchanged.</p>
      <div className="table-scroll">
        <table className="findings-table g17-matrix">
          <thead><tr><th scope="col">Row</th>{data.months.map((month) => (
            <th scope="col" key={month.key}>{month.label}</th>
          ))}</tr></thead>
          <tbody>{data.revision_rows.map((row) => (
            <tr key={row.path} data-path={row.path}>
              <th scope="row">{rowName(row.path, row.naics)}<small>{row.path}</small></th>
              {row.cells.map((cell) => (
                <td key={cell.month} className={cell.steps.includes("reversal") ? "is-opposing" : undefined}>
                  {cell.estimates.map((estimate) => `${rate(estimate.rate)}${estimate.marker === "p" ? " [p]" : ""}`)
                    .join(" → ") || "—"}
                  {cell.steps.filter(Boolean).length > 0 && (
                    <small>{cell.steps.map((step) => (step ? STEP[step] : "")).join(", then ")}</small>
                  )}
                </td>
              ))}
            </tr>
          ))}</tbody>
        </table>
      </div>
    </section>
  );
}

function BreadthTables({ data }: { data: G17Tables }) {
  const breadth = data.breadth;
  if (!breadth) return null;
  return (
    <section className="card g17-breadth-full reveal" style={order(7)} aria-labelledby="g17-breadth-full-title">
      <h2 id="g17-breadth-full-title">Manufacturing breadth by release</h2>
      {breadth.state !== "checked" ? <p className="findings-empty">{breadth.detail}</p> : (
        <>
          <p className="findings-note">Counts of the 19 NAICS manufacturing subsectors (11 durable, 8 nondurable) by
            printed direction, against Manufacturing (NAICS). Each release is shown on its own, so months of different
            release versions are never joined into one series. The bars show counts of subsectors, not shares of
            aggregate growth.</p>
          <Legend />
          {(breadth.releases ?? []).map((release) => (
            <div key={release.release} className="g17-breadth-release" data-release={release.release}>
              <h3>{release.release_date_as_stated} release <small><a href={release.url} rel="noreferrer">Table 1</a>
                {" "}<code>{release.sha256.slice(0, 12)}</code></small></h3>
              {release.state === "computed" ? (
                <>
                  <CountsTable months={release.months} caption={`As published in the ${release.release_date_as_stated} `
                    + "release"} />
                  <div className="table-scroll"><table className="findings-table g17-groups">
                    <caption>By group (up / down / 0.0 / not printed)</caption>
                    <thead><tr><th scope="col">Month</th><th scope="col">Durable (11)</th>
                      <th scope="col">Nondurable (8)</th><th scope="col">Change from the previous month</th></tr></thead>
                    <tbody>{release.months.map((month, index) => {
                      const shift = index > 0 ? release.shifts[index - 1] : null;
                      const group = (name: "durable" | "nondurable") => {
                        const g = month.groups[name];
                        return `${g.positive} / ${g.negative} / ${g.printed_zero} / ${g.missing}`;
                      };
                      return (
                        <tr key={month.month}><th scope="row">{month.month_label}</th><td>{group("durable")}</td>
                          <td>{group("nondurable")}</td>
                          <td>{shift ? (shift.compared ? `up ${shift.change.positive >= 0 ? "+" : ""}${shift.change.positive}`
                            + `, down ${shift.change.negative >= 0 ? "+" : ""}${shift.change.negative}`
                            + (shift.shift ? " (breadth shifted)" : "") : "not compared (a subsector not printed)") : "—"}
                          </td></tr>
                      );
                    })}</tbody>
                  </table></div>
                </>
              ) : <p className="findings-empty">Breadth not available: {release.detail}</p>}
            </div>
          ))}
          <h3>Revised breadth for the same month</h3>
          {(breadth.revisions ?? []).map((pair) => (
            <div key={`${pair.earlier.release}-${pair.later.release}`} className="table-scroll">
              <table className="findings-table g17-breadth-revisions"
                     data-pair={`${pair.earlier.release}-${pair.later.release}`}>
                <caption>{pair.earlier.release_date_as_stated} release to {pair.later.release_date_as_stated} release
                </caption>
                <thead><tr><th scope="col">Month</th><th scope="col">Earlier</th><th scope="col">Later</th>
                  <th scope="col">Switched direction</th><th scope="col">To or from 0.0</th>
                  <th scope="col">Breadth</th></tr></thead>
                <tbody>{pair.months.map((month) => (
                  <tr key={month.month} className={month.changed ? "is-changed" : undefined}>
                    <th scope="row">{month.month_label}<small>{month.earlier.marker === "p" ? "from preliminary"
                      : "earlier estimate revised"}</small></th>
                    <td>{month.earlier_text}</td><td>{month.later_text}</td>
                    <td>{month.reversals.map((item) => item.label).join("; ") || "—"}</td>
                    <td>{month.printed_zero_transitions.map((item) => item.label).join("; ") || "—"}</td>
                    <td>{!month.compared ? "not compared (coverage changed)" : month.changed ? "picture changed"
                      : month.counts_unchanged_members_switched ? "same counts, members switched" : "unchanged picture"}
                    </td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          ))}
        </>
      )}
    </section>
  );
}
