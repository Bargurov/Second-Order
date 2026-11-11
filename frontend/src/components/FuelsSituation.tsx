import { useId } from "react";
import type { FuelsView, SplitView, WindowView } from "../fuels";
import {
  canSay, cannotSay, figureBadge, labelLineKind, levelText, mainWindow, newerText, SITUATION_COPY as COPY,
  retrievalText, smallShown, splitBar, splitDescription, splitScale, staleText, summaryLine, unavailableText,
  WINDOW_LABEL, windowDates,
  type SplitScale,
} from "../fuelsSituation";
import { changeMoney, changeNumber, changePercent } from "../fuelsText";
import { Kind, SectionHead } from "./CopperBits";
import { Explanation } from "./FuelsBits";

const ROWS = ["brent", "gasoline", "diesel", "basket", "crack"] as const;
const PARTS = ["crude", "crack", "basket"] as const;
/** The bar's drawing: a 320-unit scale with room either side for the basket mark. */
const BAR_WIDTH = 320;
const BAR_PAD = 6;
const BAR_HEIGHT = 30;
const BAR_TOP = 5;
const BAR_DEPTH = 15;

const isComputed = (w: WindowView) => w.state === "computed" && w.rows !== null && w.split !== null;
const at = (x: number) => (x + BAR_PAD).toFixed(2);

function Change({ w, name }: { w: WindowView; name: (typeof ROWS)[number] }) {
  const row = w.rows![name];
  return (
    <td data-row={name} data-shown={row.change.shown}>
      <span className="fu-change">{changeNumber(row.change)}</span>
      {row.pct && <span className="fu-pct">{changePercent(row.pct, row.change)}%</span>}
      <Kind {...figureBadge(name, "change", row)} />
    </td>
  );
}

function WindowHead({ w }: { w: WindowView }) {
  return (
    <th scope="row">
      <span className="fu-window-name">{WINDOW_LABEL[w.id]}</span>
      <span className="fu-window-dates">{windowDates(w)}</span>
    </th>
  );
}

function ColumnHeads() {
  return (
    <thead><tr><th scope="col">{COPY.columns.window}</th>
      {ROWS.map((name) => <th key={name} scope="col">{COPY.columns[name]} <span className="ct-unit">
        {COPY.units[name]}</span></th>)}</tr></thead>
  );
}

function WindowRow({ w }: { w: WindowView }) {
  const head = <WindowHead w={w} />;
  if (!isComputed(w)) {
    return <tr data-window={w.id} data-state="unavailable">{head}
      <td className="fu-window-reason" colSpan={ROWS.length}>{unavailableText(w)}</td></tr>;
  }
  return <tr data-window={w.id} data-state="computed">{head}{ROWS.map((name) => <Change key={name} w={w} name={name} />)}</tr>;
}

/** The values each computed window compares, from → to, in text: the windows table shows them only on hover. The
 * three spot prices' levels are published (P); the basket's and the crack's are computed (C). */
function Levels({ windows }: { windows: WindowView[] }) {
  return (
    <details className="fu-levels">
      <summary>{COPY.levelsSummary}</summary>
      <div className="ct-table-wrap">
        <table className="ct-table fu-levels-table" aria-label={COPY.levelsLabel}>
          <ColumnHeads />
          <tbody>{windows.map((w) => (
            <tr key={w.id} data-window={w.id}><WindowHead w={w} />
              {ROWS.map((name) => {
                const row = w.rows![name];
                return (
                  <td key={name} data-row={name} data-from={row.from.shown} data-to={row.to.shown}>
                    <span className="fu-level">{levelText(row)}</span><Kind {...figureBadge(name, "level", row)} />
                  </td>
                );
              })}</tr>))}</tbody>
        </table>
      </div>
    </details>
  );
}

/** One window's split: the to-scale bar from its zero line in the barrel's hatching, and the figures as text beside it. */
function SplitBar({ w, scale }: { w: WindowView; scale: SplitScale }) {
  const id = useId().replace(/[^A-Za-z0-9_-]/g, "");
  const split = w.split as SplitView;
  const bar = splitBar(split, scale);
  const fills = { crude: `fu-split-crude-${id}`, crack: `fu-split-crack-${id}` };
  return (
    <li className="fu-split" data-window={w.id} data-label={split.label}>
      <p className="fu-split-name">{WINDOW_LABEL[w.id]}<span className="fu-window-dates">{windowDates(w)}</span></p>
      <svg className="fu-split-bar" viewBox={`0 0 ${BAR_WIDTH + 2 * BAR_PAD} ${BAR_HEIGHT}`} role="img"
           aria-label={splitDescription(w)} data-zero-x={at(bar.zeroX)} data-net-x={at(bar.netX)}>
        <defs>
          <pattern id={fills.crude} width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="4" height="4" className="fu-crude-ground" />
            <line x1="0" y1="0" x2="0" y2="4" className="fu-crude-hatch" />
          </pattern>
          <pattern id={fills.crack} width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)">
            <rect width="5" height="5" className="fu-crack-ground" />
            <line x1="0" y1="0" x2="0" y2="5" className="fu-crack-hatch" />
          </pattern>
        </defs>
        {(["crude", "crack"] as const).map((part) => (
          <rect key={part} className={`fu-split-part fu-split-${part}`} data-part={part} data-shown={split[part].shown}
                x={at(bar[part].x)} y={BAR_TOP} width={bar[part].w.toFixed(2)} height={BAR_DEPTH}
                fill={`url(#${fills[part]})`} />
        ))}
        <line className="fu-split-zero" x1={at(bar.zeroX)} x2={at(bar.zeroX)} y1="0" y2={BAR_TOP + BAR_DEPTH + 2} />
        <path className="fu-split-net" d={`M${at(bar.netX)},${BAR_TOP + BAR_DEPTH + 2} l-4,7 h8 z`} />
      </svg>
      <p className="fu-split-values">
        {PARTS.map((part) => (
          <span key={part} className="fu-split-value" data-part={part} data-shown={split[part].shown}>
            <span className="fu-swatch" data-part={part} aria-hidden="true" />
            {COPY.parts[part]} {changeMoney(split[part])}<Kind kind="computed" title={COPY.computedTitle} />
          </span>
        ))}
      </p>
    </li>
  );
}

function Computed({ view }: { view: FuelsView }) {
  const s = view.situation;
  const main = mainWindow(s);
  const computed = s.windows.filter(isComputed);
  const scale = splitScale(computed.map((w) => w.split as SplitView), BAR_WIDTH);
  const stale = staleText(s, view.snapshot.retrieved_at);
  const labels = new Map<string, string>(view.series.map((row) => [row.role, row.label]));
  return (
    <>
      <p className="fu-summary" data-window={main?.id ?? "none"} data-label={main?.split?.label ?? "none"}>
        {main ? <>{summaryLine(main)}<Kind kind="computed" title={COPY.labelTitle} /></> : COPY.noWindow}
      </p>
      {stale && <p className="fu-sit-note" data-note="stale">{stale}<Kind kind="computed" title={COPY.ageTitle} /></p>}
      {s.newer.map((entry) => (
        <p key={entry.role} className="fu-sit-note" data-note="newer" data-role={entry.role}>
          {newerText(labels.get(entry.role) ?? entry.role, entry.date, s.date as string)}</p>
      ))}
      <div className="ct-table-wrap">
        <table className="ct-table fu-windows" aria-label={COPY.tableLabel}>
          <ColumnHeads />
          <tbody>{s.windows.map((w) => <WindowRow key={w.id} w={w} />)}</tbody>
        </table>
      </div>
      {smallShown(computed) && <p className="fu-sit-note" data-note="small">{COPY.small}</p>}
      {retrievalText(view.snapshot.retrieved_at) && (
        <p className="fu-sit-note" data-note="retrieval">{retrievalText(view.snapshot.retrieved_at)}</p>)}
      {computed.length > 0 && <Levels windows={computed} />}
      {computed.length > 0 && (
        <>
          <h3>{COPY.splitHead}</h3>
          <p className="ct-note fu-bar-key">{COPY.barKey}</p>
          <ul className="fu-splits">{computed.map((w) => <SplitBar key={w.id} w={w} scale={scale} />)}</ul>
        </>
      )}
      {main?.split && (
        <details className="fu-can" data-window={main.id}>
          <summary>{COPY.canSummary}</summary>
          <h3>{COPY.canHead} · {WINDOW_LABEL[main.id]}</h3>
          <ul className="fu-can-say">{canSay(main).map((line, index, lines) => (
            <li key={line}>{line}{index < lines.length - 1 ? <Kind kind="computed" title={COPY.computedTitle} />
              : labelLineKind(main.split!.label) === "explanation" ? <Explanation />
              : <Kind kind="computed" title={COPY.labelTitle} />}</li>))}</ul>
          <h3>{COPY.cannotHead}</h3>
          <ul className="fu-cannot-say">{cannotSay(main.split.label).map((line) => <li key={line}>{line}</li>)}</ul>
        </details>
      )}
    </>
  );
}

/** Situation Now (spec section 4): the summary for the main window, the staleness and newer-series notes, the three
 * windows, the split bars and what they can and cannot show. Withheld, it shows only why, with no number. */
export function FuelsSituation({ view }: { view: FuelsView }) {
  const s = view.situation;
  return (
    <section id="situation" className="ct-section fu-section" aria-labelledby="situation-title" data-state={s.state}>
      <SectionHead id="situation" kicker={COPY.kicker} title={COPY.title}>
        <p className="ct-plain">{COPY.intro}</p>
      </SectionHead>
      {s.state === "computed" ? <Computed view={view} />
        : <div className="fu-sit-problem" data-situation="withheld"><p>{s.problem}</p></div>}
    </section>
  );
}
