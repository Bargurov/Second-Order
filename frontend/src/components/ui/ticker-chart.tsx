import { cn } from "@/lib/utils";
import type { ChartPoint } from "@/lib/api";

interface TickerChartProps {
  data: ChartPoint[];
  eventDate: string;
  width?: number;
  height?: number;
  className?: string;
}

export function TickerChart({
  data,
  eventDate,
  width = 480,
  height = 120,
  className,
}: TickerChartProps) {
  if (data.length < 2) {
    return (
      <div className={cn("flex items-center justify-center rounded-xl border border-dashed border-border bg-secondary/20", className)}
           style={{ width, height }}>
        <span className="text-2xs text-muted-foreground">No chart data</span>
      </div>
    );
  }

  const pad = { top: 8, right: 8, bottom: 20, left: 8 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;

  const closes = data.map((d) => d.close);
  const lo = Math.min(...closes);
  const hi = Math.max(...closes);
  const range = hi - lo || 1;

  const xStep = innerW / (data.length - 1);

  const toX = (i: number) => pad.left + i * xStep;
  const toY = (v: number) => pad.top + innerH - ((v - lo) / range) * innerH;

  // Build polyline
  const points = data.map((d, i) => `${toX(i).toFixed(1)},${toY(d.close).toFixed(1)}`).join(" ");

  // Build area fill path
  const areaPath = [
    `M ${toX(0).toFixed(1)},${toY(data[0]!.close).toFixed(1)}`,
    ...data.slice(1).map((d, i) => `L ${toX(i + 1).toFixed(1)},${toY(d.close).toFixed(1)}`),
    `L ${toX(data.length - 1).toFixed(1)},${(pad.top + innerH).toFixed(1)}`,
    `L ${toX(0).toFixed(1)},${(pad.top + innerH).toFixed(1)}`,
    "Z",
  ].join(" ");

  // Event date marker
  const eventIdx = data.findIndex((d) => d.date >= eventDate);
  const eventX = eventIdx >= 0 ? toX(eventIdx) : null;

  // Determine line colour from overall trend
  const firstClose = data[0]!.close;
  const lastClose = data[data.length - 1]!.close;
  const up = lastClose >= firstClose;
  const strokeColor = up ? "#15803d" : "#b91c1c";
  const fillColor = up ? "rgba(21,128,61,0.06)" : "rgba(185,28,28,0.06)";

  // X-axis labels: first, event, last
  const labels: { x: number; text: string }[] = [
    { x: toX(0), text: data[0]!.date.slice(5) },
    { x: toX(data.length - 1), text: data[data.length - 1]!.date.slice(5) },
  ];
  if (eventX != null) {
    labels.splice(1, 0, { x: eventX, text: eventDate.slice(5) });
  }

  return (
    <svg
      width={width}
      height={height}
      className={cn("shrink-0", className)}
      viewBox={`0 0 ${width} ${height}`}
    >
      {/* Grid lines */}
      <line x1={pad.left} y1={pad.top + innerH} x2={pad.left + innerW} y2={pad.top + innerH}
            stroke="hsl(var(--border))" strokeWidth={0.5} />

      {/* Area fill */}
      <path d={areaPath} fill={fillColor} />

      {/* Price line */}
      <polyline
        points={points}
        fill="none"
        stroke={strokeColor}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {/* Event date marker */}
      {eventX != null && (
        <>
          <line
            x1={eventX} y1={pad.top} x2={eventX} y2={pad.top + innerH}
            stroke="hsl(var(--ring))"
            strokeWidth={1}
            strokeDasharray="3 2"
            opacity={0.5}
          />
          <circle cx={eventX} cy={toY(data[eventIdx!]!.close)} r={3}
                  fill="hsl(var(--ring))" opacity={0.7} />
        </>
      )}

      {/* End dot */}
      <circle
        cx={toX(data.length - 1)} cy={toY(lastClose)} r={2.5}
        fill={strokeColor}
      />

      {/* X-axis labels */}
      {labels.map((l, i) => (
        <text
          key={i}
          x={l.x}
          y={height - 4}
          textAnchor={i === 0 ? "start" : i === labels.length - 1 ? "end" : "middle"}
          className="fill-muted-foreground"
          style={{ fontSize: 9, fontFamily: "var(--font-mono, monospace)" }}
        >
          {l.text}
        </text>
      ))}
    </svg>
  );
}
