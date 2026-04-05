import { cn } from "@/lib/utils";

/** Format a percentage return value: "+2.50%" / "—" for null. */
export function pct(v: number | null | undefined): string {
  if (v == null) return "\u2014";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

/** Human-readable market cap: $1.2T / $45.3B / $800M */
export function fmtMktCap(v: number | null): string {
  if (v == null) return "\u2014";
  if (v >= 1e12) return `$${(v / 1e12).toFixed(1)}T`;
  if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(0)}M`;
  return `$${v.toLocaleString()}`;
}

/** Human-readable volume: 12.3M / 450K */
export function fmtVol(v: number | null): string {
  if (v == null) return "\u2014";
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(0)}K`;
  return String(v);
}

/** Compact coloured return value. */
export function RetVal({ v, className: cls }: { v: number | null | undefined; className?: string }) {
  return (
    <span className={cn(
      "font-num text-2xs",
      v != null && v > 0 && "val-pos",
      v != null && v < 0 && "val-neg",
      v == null && "text-muted-foreground",
      cls,
    )}>
      {pct(v)}
    </span>
  );
}
