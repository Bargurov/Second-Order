import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

interface SectionHeaderProps {
  kicker?: string;
  title: string;
  subtitle?: string;
  action?: ReactNode;
  className?: string;
}

export function SectionHeader({
  kicker,
  title,
  subtitle,
  action,
  className,
}: SectionHeaderProps) {
  return (
    <div className={cn("flex items-start justify-between gap-4", className)}>
      <div className="min-w-0">
        {kicker && (
          <p className="section-kicker mb-1">{kicker}</p>
        )}
        <h2 className="font-headline truncate text-sm font-semibold leading-snug tracking-[-0.01em] text-foreground">
          {title}
        </h2>
        {subtitle && (
          <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>
        )}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}
