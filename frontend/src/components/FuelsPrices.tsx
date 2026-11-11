import { formatDay } from "../format";
import type { FuelsView, SeriesView } from "../fuels";
import { sparklinePath } from "../fuelsBarrel";
import { publishedText } from "../fuelsNote";
import { BARREL_LABELS, behindText, money, UNIT_SHORT } from "../fuelsText";
import { Kind, SectionHead } from "./CopperBits";

const TILE_ROLES = ["brent", "gasoline", "diesel"] as const;
const SPARK_WIDTH = 200;
const SPARK_HEIGHT = 36;

const capital = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

/** A one-line trend in ink over exactly the covered dates, captioned with where it starts; nothing when fewer than two
 * observations have a value. */
function Spark({ points }: { points: [string, string | null][] }) {
  const path = sparklinePath(points, SPARK_WIDTH, SPARK_HEIGHT);
  const first = points.find(([, value]) => value !== null)?.[0];
  if (path === "" || first === undefined) return null;
  return (
    <figure className="fu-spark">
      <svg viewBox={`0 -2 ${SPARK_WIDTH} ${SPARK_HEIGHT + 4}`} preserveAspectRatio="none" aria-hidden="true">
        <path d={path} />
      </svg>
      <figcaption>since {formatDay(first)}</figcaption>
    </figure>
  );
}

function Missing({ title, problem }: { title: string; problem: string | null }) {
  return (
    <>
      <p className="fu-tile-value fu-tile-missing"><Kind kind="missing" title={title} /> {title}</p>
      {problem && <p className="fu-tile-problem">{problem}</p>}
    </>
  );
}

function SeriesTile({ row, states }: { row: SeriesView; states: Record<string, string> | undefined }) {
  const latest = row.latest;
  return (
    <li className="fu-tile" data-tile={row.role} data-state={row.state}>
      <p className="fu-tile-label">{row.label} · {UNIT_SHORT[row.unit]}</p>
      {latest ? (
        <>
          <p className="fu-tile-value">{money(latest.shown)}<Kind kind="published"
            title={`Published by EIA · ${row.series_id}`} /></p>
          <p className="fu-tile-dates">observed {formatDay(latest.date)} · {publishedText(latest.published_on)}</p>
          {row.behind && <p className="fu-behind" data-behind={row.behind.days}>{behindText(row.behind, true)}</p>}
        </>
      ) : <Missing title={states?.[row.state] ?? "Missing"} problem={row.problem} />}
      <Spark points={row.history} />
      <p className="fu-tile-meta">{capital(row.cadence)} observations, published {row.publication} by EIA</p>
      {latest && typeof row.attribution === "string" && <p className="fu-attribution">{row.attribution}</p>}
    </li>
  );
}

function CrackTile({ view }: { view: FuelsView }) {
  const { barrel } = view;
  const crack = barrel.crack;
  return (
    <li className="fu-tile" data-tile="crack" data-state={barrel.state}>
      <p className="fu-tile-label">{BARREL_LABELS.crack} · $/bbl</p>
      {crack && barrel.date ? (
        <>
          <p className="fu-tile-value">{money(crack.shown)}<Kind kind="computed"
            title={`Computed · ${barrel.definition.crack}`} /></p>
          <p className="fu-tile-dates">observed {formatDay(barrel.date)} · {publishedText(barrel.published_on)}</p>
        </>
      ) : <Missing title="Withheld" problem={barrel.problem} />}
      <Spark points={view.crack_history} />
      <p className="fu-tile-meta">Daily, on the dates all three inputs share</p>
      <p className="fu-attribution">Computed from the three series above (3-2-1, spot)</p>
    </li>
  );
}

/** Spot price tiles for the three inputs and the crack, then the coverage strip of the other series on the chain. */
export function FuelsPrices({ view }: { view: FuelsView }) {
  const byRole = new Map(view.series.map((row) => [row.role, row]));
  const bySeries = new Map(view.series.map((row) => [row.series_id, row]));
  const states = view.labels.series_states;
  return (
    <section id="prices" className="ct-section fu-section" aria-labelledby="prices-title">
      <SectionHead id="prices" kicker="Prices · spot, as published" title="Prices along the chain">
        <p className="ct-plain">Spot prices from EIA's open data API, and the crack computed from three of
          them. Each price is refreshed only by the operator's command, and each line covers only the dates retained.</p>
      </SectionHead>
      <ul className="fu-tiles">
        {TILE_ROLES.map((role) => {
          const row = byRole.get(role);
          return row ? <SeriesTile key={role} row={row} states={states} /> : null;
        })}
        <CrackTile view={view} />
      </ul>
      <h3>Coverage</h3>
      <ul className="fu-coverage" aria-label="Coverage">
        {view.coverage.map((entry) => {
          const row = entry.series_id === null ? undefined : bySeries.get(entry.series_id);
          const latest = row?.latest ?? null;
          return (
            <li key={entry.id} data-coverage={entry.id} data-state={entry.state}>
              <span className="fu-coverage-label">{entry.label}</span>
              {row && latest ? (
                <>
                  <span className="fu-coverage-value">{money(latest.shown)} <span className="ct-unit">
                    {UNIT_SHORT[row.unit]}</span><Kind kind="published" title={`Published by EIA · ${row.series_id}`} />
                  </span>
                  <span className="fu-coverage-date">observed {formatDay(latest.date)}</span>
                  {row.behind && <span className="fu-behind" data-behind={row.behind.days}>
                    {behindText(row.behind, false)}</span>}
                  {typeof row.attribution === "string" && <span className="fu-coverage-credit">{row.attribution}</span>}
                </>
              ) : (
                <>
                  <span className="fu-coverage-value"><Kind kind="missing" title="Missing: no value is shown" /></span>
                  {entry.problem && <span className="fu-coverage-problem">{entry.problem}</span>}
                </>
              )}
              <span className="fu-coverage-meta">{capital(entry.cadence)} · {entry.source}
                {entry.series_id && <> · {entry.series_id}</>}</span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
