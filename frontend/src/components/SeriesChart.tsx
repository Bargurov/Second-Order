import { useState, type PointerEvent } from "react";
import { linear, monthStarts, niceTicks, paddedExtent } from "../chart";
import { anchorDay, formatDay, formatUtc, horizonLegend, monthLabel } from "../format";
import type { AnchorKey, LegResult, SeriesView } from "../types";

const W = 720;
const H = 290;
const M = { top: 30, right: 16, bottom: 30, left: 50 };
const DAY = 86_400_000;

interface Props {
  series: SeriesView;
  result: LegResult;
  /** Recorded anchors keyed like the series points (New York dates for a daily-date series). */
  anchors: Partial<Record<AnchorKey, string>>;
  publishedAt: string;
  /** New York publication date; a daily-date series marks publication as that whole date. */
  publishedDate: string | null;
  replay: boolean;
}

export function SeriesChart({ series, result, anchors, publishedAt, publishedDate, replay }: Props) {
  const [hover, setHover] = useState<number | null>(null);
  const daily = series.time_basis === "daily_date";
  const points = series.points.map(([at, value]) => ({ at, time: Date.parse(at), value }));
  const values = points.flatMap((point) => (point.value === null ? [] : [point.value]));
  const publicationDay = daily && publishedDate ? Date.parse(publishedDate) : null;
  const published = publicationDay ?? Date.parse(publishedAt);
  const x = linear([points[0].time, points[points.length - 1].time], [M.left, W - M.right]);
  const [low, high] = paddedExtent(values, 0.12);
  const y = linear([low, high], [H - M.bottom, M.top]);
  const digits = series.quote_unit === "level" ? 1 : 2;

  const path = points
    .map((point, i) => {
      if (point.value === null) return "";
      const move = i === 0 || points[i - 1].value === null ? "M" : "L";
      return `${move} ${x(point.time).toFixed(1)} ${y(point.value).toFixed(1)}`;
    })
    .join(" ");

  const find = (key: AnchorKey) => points.find((point) => point.at === anchors[key]);
  const event = find("event_anchor");
  const score = find("score_anchor");
  const target = find("target_at");
  const months = monthStarts(points[0].time, points[points.length - 1].time);

  const onMove = (pointer: PointerEvent<SVGRectElement>) => {
    const bounds = pointer.currentTarget.ownerSVGElement?.getBoundingClientRect();
    if (!bounds) return;
    const time = points[0].time + (((pointer.clientX - bounds.left) / bounds.width) * W - M.left) /
      (W - M.left - M.right) * (points[points.length - 1].time - points[0].time);
    let nearest = 0;
    points.forEach((point, i) => {
      if (Math.abs(point.time - time) < Math.abs(points[nearest].time - time)) nearest = i;
    });
    setHover(points[nearest].value === null ? null : nearest);
  };

  const hovered = hover === null ? null : points[hover];
  const marker = (point: { time: number; value: number | null } | undefined) =>
    point && point.value !== null ? { cx: x(point.time), cy: y(point.value) } : null;
  const eventMark = marker(event);
  const scoreMark = marker(score);
  const targetMark = marker(target);

  return (
    <figure className="chart">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`${series.label} around the event, with anchors marked${daily ? ", by New York observation date" : ""}`}
      >
        {niceTicks(low, high, 5).map((tick) => (
          <g key={tick} className="grid">
            <line x1={M.left} x2={W - M.right} y1={y(tick)} y2={y(tick)} />
            <text x={M.left - 8} y={y(tick) + 3.5} textAnchor="end">
              {tick.toFixed(digits)}
            </text>
          </g>
        ))}
        {months.map((time, i) => (
          <g key={time} className="axis-tick">
            <line x1={x(time)} x2={x(time)} y1={H - M.bottom} y2={H - M.bottom + 4} />
            <text x={x(time)} y={H - M.bottom + 17} textAnchor="middle">
              {monthLabel(time, i === 0 || new Date(time).getUTCMonth() === 0)}
            </text>
          </g>
        ))}
        {score && target && (
          <rect
            className="scored-window"
            x={x(score.time)}
            y={M.top}
            width={Math.max(2, x(target.time) - x(score.time))}
            height={H - M.top - M.bottom}
          />
        )}
        {publicationDay === null ? (
          <line className="publication" x1={x(published)} x2={x(published)} y1={M.top - 14} y2={H - M.bottom} />
        ) : (
          <rect
            className="publication-day"
            x={x(publicationDay - DAY / 2)}
            y={M.top - 14}
            width={Math.max(2, x(publicationDay + DAY / 2) - x(publicationDay - DAY / 2))}
            height={H - M.bottom - M.top + 14}
          />
        )}
        <text className="publication-label" x={x(published) + 5} y={M.top - 6}>
          Published
        </text>
        <path className="series-line" d={path} />
        {eventMark && <circle className="mark-event" r={5.5} {...eventMark} />}
        {scoreMark && <circle className="mark-score" r={3} {...scoreMark} />}
        {targetMark && (
          <rect
            className={`mark-target verdict-${result.verdict}`}
            x={targetMark.cx - 4.5}
            y={targetMark.cy - 4.5}
            width={9}
            height={9}
            transform={`rotate(45 ${targetMark.cx} ${targetMark.cy})`}
          />
        )}
        {hovered && hovered.value !== null && (
          <g className="hover" pointerEvents="none">
            <line x1={x(hovered.time)} x2={x(hovered.time)} y1={M.top} y2={H - M.bottom} />
            <circle cx={x(hovered.time)} cy={y(hovered.value)} r={3} />
            <g transform={`translate(${Math.min(x(hovered.time) + 8, W - M.right - 118)} ${M.top + 4})`}>
              <rect width={114} height={36} rx={2} />
              <text x={8} y={15}>{formatDay(hovered.at)}</text>
              <text x={8} y={29} className="hover-value">{hovered.value.toFixed(digits)}</text>
            </g>
          </g>
        )}
        <rect
          className="hit-area"
          x={M.left}
          y={M.top}
          width={W - M.left - M.right}
          height={H - M.top - M.bottom}
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
        />
      </svg>
      <figcaption>
        <ul className="legend">
          <li>
            <span className={`key ${publicationDay === null ? "key-publication" : "key-publication-day"}`} />
            Published · {formatUtc(publishedAt)}
            {publicationDay !== null && publishedDate ? ` (New York date ${formatDay(publishedDate)}, shaded)` : ""}
          </li>
          <li>
            <span className="key key-event" />
            Event anchor · {anchorDay(anchors, "event_anchor") ?? "—"},{" "}
            {daily ? "last observation dated before the publication date" : "last observation before publication"}
          </li>
          <li>
            <span className="key key-score" />
            Score anchor · {anchorDay(anchors, "score_anchor") ?? "—"}
            {replay
              ? ", same as the event anchor in a simulated replay"
              : daily
                ? ", first observation dated after the freeze date"
                : ""}
          </li>
          <li>
            <span className={`key key-target verdict-${result.verdict}`} />
            {horizonLegend(anchorDay(anchors, "target_at"), result.horizon)}
          </li>
          {daily && (
            <li className="legend-note">Dates are New York observation dates; no intraday observation time is shown.</li>
          )}
        </ul>
      </figcaption>
    </figure>
  );
}
