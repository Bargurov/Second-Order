import { linear, niceTicks } from "../chart";
import { anchorDay, formatNumber, unitDigits } from "../format";
import type { AnchorKey, LegResult, ReferenceView } from "../types";

const W = 520;
const H = 250;
const M = { top: 34, right: 14, bottom: 34, left: 34 };

interface Props {
  reference: ReferenceView;
  result: LegResult;
  anchors: Partial<Record<AnchorKey, string>>;
  unit: string;
  expected: "up" | "down";
}

/** Bars of the exact reference moves the scorer ranked against; counts and rank come from the server. */
export function ReferenceHistogram({ reference, result, anchors, unit, expected }: Props) {
  const { edges, counts } = reference.histogram;
  const event = reference.event_signed_move;
  const x = linear([edges[0], edges[edges.length - 1]], [M.left, W - M.right]);
  const peak = Math.max(...counts);
  const y = linear([0, peak], [H - M.bottom, M.top]);
  const digits = unitDigits(unit);
  const eventX = x(event);
  const labelRight = eventX < W - 150;

  return (
    <figure className="chart histogram">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Reference distribution with this event's signed move marked">
        {niceTicks(0, peak, 3).map((tick) => (
          <g key={tick} className="grid">
            <line x1={M.left} x2={W - M.right} y1={y(tick)} y2={y(tick)} />
            <text x={M.left - 6} y={y(tick) + 3.5} textAnchor="end">{tick}</text>
          </g>
        ))}
        {counts.map((count, i) => {
          const left = x(edges[i]);
          const right = x(edges[i + 1]);
          const side = (edges[i] + edges[i + 1]) / 2 < event ? "below" : "above";
          return (
            <rect
              key={i}
              className={`bar ${side}`}
              x={left + 0.5}
              y={y(count)}
              width={Math.max(0.5, right - left - 1)}
              height={H - M.bottom - y(count)}
            >
              <title>{`${count} windows between ${formatNumber(edges[i], digits)} and ${formatNumber(edges[i + 1], digits)}`}</title>
            </rect>
          );
        })}
        {edges[0] < 0 && edges[edges.length - 1] > 0 && (
          <g className="zero">
            <line x1={x(0)} x2={x(0)} y1={M.top - 4} y2={H - M.bottom} />
            <text x={x(0)} y={H - M.bottom + 26} textAnchor="middle">0</text>
          </g>
        )}
        {niceTicks(edges[0], edges[edges.length - 1], 6)
          .filter((tick) => tick !== 0)
          .map((tick) => (
            <text key={tick} className="axis-label" x={x(tick)} y={H - M.bottom + 26} textAnchor="middle">
              {formatNumber(tick, tick % 1 === 0 ? 0 : digits)}
            </text>
          ))}
        <line className="baseline" x1={M.left} x2={W - M.right} y1={H - M.bottom} y2={H - M.bottom} />
        <g className={`event-marker verdict-${result.verdict}`}>
          <line x1={eventX} x2={eventX} y1={M.top - 18} y2={H - M.bottom} />
          <text x={labelRight ? eventX + 6 : eventX - 6} y={M.top - 8} textAnchor={labelRight ? "start" : "end"}>
            {`This event · ${formatNumber(event, digits)}`}
          </text>
        </g>
      </svg>
      <figcaption>
        <p>
          Signed {unit} moves over {result.horizon}-session windows; positive means the expected
          direction ({expected}). {reference.values.length} windows ending{" "}
          {anchorDay(anchors, "reference_end") ?? "before publication"} (
          {result.non_overlapping_reference_windows} non-overlapping).
        </p>
        <p className="rank-line">
          <span>{reference.below} below</span>
          <span>{reference.equal} equal</span>
          <span>{reference.above} above</span>
          <span>
            → percentile rank <strong>{result.percentile_rank?.toFixed(3) ?? "—"}</strong>
          </span>
        </p>
      </figcaption>
    </figure>
  );
}
