import { cn } from "@/lib/utils";

interface SparklineProps {
  /** Normalised values 0–1 */
  data: number[];
  width?: number;
  height?: number;
  className?: string;
  /** Positive = green stroke, negative = red, zero/null = muted */
  direction?: number | null;
}

export function Sparkline({
  data,
  width = 64,
  height = 20,
  className,
  direction,
}: SparklineProps) {
  if (!data || data.length < 2) {
    return (
      <svg
        width={width}
        height={height}
        className={cn("shrink-0 opacity-20", className)}
        viewBox={`0 0 ${width} ${height}`}
      >
        <line
          x1={0} y1={height / 2} x2={width} y2={height / 2}
          stroke="currentColor"
          strokeWidth={1}
          strokeDasharray="2 2"
        />
      </svg>
    );
  }

  const pad = 1;
  const innerW = width - pad * 2;
  const innerH = height - pad * 2;
  const step = innerW / (data.length - 1);

  const points = data
    .map((v, i) => {
      const clamped = Math.max(0, Math.min(1, v));
      const x = pad + i * step;
      const y = pad + innerH - clamped * innerH;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  // Stroke colour from direction
  let strokeClass: string;
  if (direction != null && direction > 0) {
    strokeClass = "stroke-[#4ade80]"; // val-pos
  } else if (direction != null && direction < 0) {
    strokeClass = "stroke-[#f87171]"; // val-neg
  } else {
    strokeClass = "stroke-current text-muted-foreground";
  }

  // End dot at the last point
  const lastX = pad + (data.length - 1) * step;
  const lastVal = Math.max(0, Math.min(1, data[data.length - 1] ?? 0.5));
  const lastY = pad + innerH - lastVal * innerH;

  return (
    <svg
      width={width}
      height={height}
      className={cn("shrink-0", className)}
      viewBox={`0 0 ${width} ${height}`}
    >
      <polyline
        points={points}
        fill="none"
        className={strokeClass}
        strokeWidth={1.25}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle
        cx={lastX.toFixed(1)}
        cy={lastY.toFixed(1)}
        r={1.5}
        className={cn("fill-current", strokeClass)}
      />
    </svg>
  );
}
