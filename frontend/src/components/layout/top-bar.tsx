import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  PanelLeftClose,
  PanelLeft,
  Search,
} from "lucide-react";
import { api } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import type { Page } from "./sidebar";

const PAGE_META: Record<Page, { group: string; title: string }> = {
  market:    { group: "Workspace", title: "Market" },
  // Back-compat alias — App.tsx routes ``overview`` to the same
  // MarketOverview surface as ``market`` so older callers still resolve.
  overview:  { group: "Workspace", title: "Market" },
  portfolio: { group: "Workspace", title: "Portfolio"      },
  headlines: { group: "Workspace", title: "Headlines"      },
  analyze:   { group: "Workspace", title: "Analyze"        },
  events:    { group: "Research",  title: "Archive"        },
  backtest:  { group: "Research",  title: "Backtest"       },
};

interface TopBarProps {
  page: Page;
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
}

export function TopBar({ page, sidebarCollapsed, onToggleSidebar }: TopBarProps) {
  const meta = PAGE_META[page];

  const { isSuccess, isError } = useQuery({
    queryKey: qk.health(),
    queryFn: () => api.health(),
    refetchInterval: 30_000,
    retry: false,
  });
  const apiStatus: "live" | "offline" | "pending" =
    isSuccess ? "live" : isError ? "offline" : "pending";

  const statusTone =
    apiStatus === "live"
      ? "text-primary"
      : apiStatus === "offline"
      ? "text-destructive"
      : "text-on-surface-variant/70";

  const statusLabel =
    apiStatus === "live" ? "live" : apiStatus === "offline" ? "offline" : "syncing";

  return (
    <header
      className={cn(
        "flex h-14 shrink-0 items-center gap-3 px-3 md:px-5",
        "border-b border-border/40",
        "bg-background/85 backdrop-blur-md",
      )}
    >
      <Button
        variant="ghost"
        size="icon"
        className="h-7 w-7 rounded-md text-on-surface-variant/70 hover:text-on-surface hover:bg-white/[0.04]"
        onClick={onToggleSidebar}
        aria-label="Toggle sidebar"
      >
        {sidebarCollapsed ? (
          <PanelLeft className="h-3.5 w-3.5" />
        ) : (
          <PanelLeftClose className="h-3.5 w-3.5" />
        )}
      </Button>

      {/* Breadcrumb */}
      <div className="flex min-w-0 items-center gap-2 text-[12px]">
        <span className="text-on-surface-variant/60">{meta.group}</span>
        <span className="text-on-surface-variant/40">›</span>
        <span className="font-medium text-on-surface">{meta.title}</span>
      </div>

      {/* Search pill */}
      <div
        className={cn(
          "ml-3 hidden h-8 items-center gap-2 rounded-md px-2.5 md:flex",
          "w-[320px] max-w-[36vw]",
          "bg-white/[0.025] border border-border/40",
          "text-on-surface-variant/65",
        )}
        aria-hidden
      >
        <Search className="h-3 w-3 text-on-surface-variant/45" />
        <span className="truncate text-[12px]">
          Search studies, tickers, mechanisms…
        </span>
        <span
          className={cn(
            "ml-auto font-num tabular-nums text-[10.5px]",
            "rounded-sm border border-border/40 bg-white/[0.04] px-1.5 py-px",
            "text-on-surface-variant/65",
          )}
        >
          ⌘K
        </span>
      </div>

      {/* Right cluster */}
      <div className="ml-auto flex items-center gap-3 text-[11.5px]">
        <div className="hidden items-center gap-1.5 sm:flex">
          <span
            className={cn(
              "h-1.5 w-1.5 rounded-full",
              apiStatus === "live"
                ? "bg-primary shadow-[0_0_6px_rgba(147,209,211,0.55)] animate-pulse"
                : apiStatus === "offline"
                ? "bg-destructive"
                : "bg-on-surface-variant/40",
            )}
          />
          <span className={cn("font-mono tabular-nums uppercase tracking-[0.06em]", statusTone)}>
            {statusLabel}
          </span>
        </div>
      </div>
    </header>
  );
}
