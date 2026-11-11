import type { ReactNode } from "react";
import {
  CHART, CHART_NARROW, chartModel, contextRows, dayNumber, formatContextDate, type ChartView, type ContextRow,
} from "../marketContext";
import { useNarrow } from "./TransmissionMap";

const LINE_CLASS = ["context-line-short", "context-line-long"];  // By position: the 2-year, then the 10-year.

/**
 * The chart of daily H.15 yields in a window, shared by the case library's market context and an event's private
 * context. `marker` names the marked date ("Publication date", "Context date"); `legendExtra` adds legend lines.
 */
export function ContextChart({ view, marker, markerLegend, desc, legendExtra }: {
  view: ChartView;
  marker: string;
  markerLegend: string;
  desc: string;
  legendExtra?: ReactNode;
}) {
  const size = useNarrow() ? CHART_NARROW : CHART;
  const model = chartModel(view, size);
  const range = `${formatContextDate(view.window.start)} to ${formatContextDate(view.window.end)}`;
  const { width: W, height: H, top, bottom, left, right } = size;
  return (
    <figure className="chart context-chart">
      <svg viewBox={`0 0 ${W} ${H}`} data-width={W} role="img" aria-labelledby="context-chart-title context-chart-desc">
        <title id="context-chart-title">Daily 2-year and 10-year Treasury yields (H.15), {range}</title>
        <desc id="context-chart-desc">{desc}</desc>
        {model.yTicks.map((tick) => (
          <g key={tick.value} className="grid">
            <line x1={left} x2={W - right} y1={tick.y} y2={tick.y} />
            <text x={left - 8} y={tick.y + 3.5} textAnchor="end">{tick.label}</text>
          </g>
        ))}
        <text className="axis-label" x={4} y={12}>Yield, percent</text>
        {model.xTicks.map((tick) => (
          <g key={tick.date} className="axis-tick" data-date={tick.date}>
            <line x1={tick.x} x2={tick.x} y1={H - bottom} y2={H - bottom + 4} />
            <text x={tick.x} y={H - bottom + 17} textAnchor="middle">{tick.label}</text>
          </g>
        ))}
        <line className="publication context-publication" data-date={model.marker.date}
          x1={model.marker.x} x2={model.marker.x} y1={top - 12} y2={H - bottom} />
        <text className="publication-label" x={model.marker.x + 5} y={top - 4}>{marker}</text>
        {model.lines.map((line, row) => line.missing.map((date) => (
          <text key={`${line.id}-${date}`} className={`context-missing ${LINE_CLASS[row]}`} data-series={line.id}
            data-date={date} x={model.x(dayNumber(date))} y={H - bottom - 6 - row * 14} textAnchor="middle">
            <title>{`${line.label}: no value on ${formatContextDate(date)}, an expected session`}</title>
            × {line.tag}
          </text>
        )))}
        {model.lines.map((line, row) => line.conflicts.map((date) => (
          <text key={`${line.id}-${date}-conflict`} className={`context-missing context-conflict ${LINE_CLASS[row]}`}
            data-series={line.id} data-date={date} data-status="conflict" x={model.x(dayNumber(date))}
            y={H - bottom - 6 - row * 14} textAnchor="middle">
            <title>{`${line.label}: retrieval versions disagree on ${formatContextDate(date)}; no value is chosen`}</title>
            ≠ {line.tag}
          </text>
        )))}
        {model.lines.map((line, row) => line.segments.map((segment, i) => (
          <path key={`${line.id}-${i}`} className={`context-line ${LINE_CLASS[row]}`} data-series={line.id}
            d={segment.map((point, j) => `${j === 0 ? "M" : "L"} ${point.cx.toFixed(1)} ${point.cy.toFixed(1)}`).join(" ")} />
        )))}
        {model.lines.map((line, row) => line.points.map((point) => (
          <circle key={`${line.id}-${point.date}`} className={`context-point ${LINE_CLASS[row]}`} r={2.6}
            cx={point.cx} cy={point.cy} data-series={line.id} data-date={point.date} data-value={point.raw} />
        )))}
      </svg>
      <figcaption>
        <ul className="legend context-legend">
          {view.series.map((series, row) => (
            <li key={series.id}><span className={`context-key ${LINE_CLASS[row]}`} />{series.label} ({series.id})</li>
          ))}
          <li><span className="key key-publication" />{markerLegend}</li>
          <li><span className="context-key-missing">×</span>An expected session with no value: 2y or 10y names the series</li>
          {legendExtra}
          <li className="legend-note">
            Dates are New York calendar dates. Weekends and SIFMA holidays have no session and are not gaps.
          </li>
        </ul>
      </figcaption>
    </figure>
  );
}

/** One row per calendar date: each series' value as published, or the reason there is none, in words. */
export function ContextTable({ view, caption, markerTag, rows }: {
  view: ChartView;
  caption: string;
  markerTag: string;
  rows?: ContextRow[];
}) {
  return (
    <table id="context-data" className="context-table">
      <caption>{caption}</caption>
      <thead>
        <tr>
          <th scope="col">Date</th>
          {view.series.map((series) => <th scope="col" key={series.id}>{series.short_label}</th>)}
          <th scope="col">Notes</th>
        </tr>
      </thead>
      <tbody>
        {(rows ?? contextRows(view)).map((row) => (
          <tr key={row.date} data-date={row.date}
            className={row.publication ? "is-publication" : row.cells.some((cell) => cell.observed) ? "" : "is-quiet"}>
            <th scope="row">
              {row.label} <span className="context-weekday">{row.weekday}</span>
              {row.publication && <span className="context-publication-tag">{markerTag}</span>}
            </th>
            {row.cells.map((cell) => (
              <td key={cell.series} data-series={cell.series} data-status={cell.status}>{cell.text}</td>
            ))}
            <td className="context-note">{row.note}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
