import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Newspaper,
  FlaskConical,
  Clock,
  Target,
  Activity,
} from "lucide-react";

export type Page = "inbox" | "analyze" | "events" | "backtest";

const NAV_ITEMS: { id: Page; label: string; icon: React.ElementType }[] = [
  { id: "inbox", label: "Feed", icon: Newspaper },
  { id: "analyze", label: "Analysis", icon: FlaskConical },
  { id: "events", label: "Research Archive", icon: Clock },
  { id: "backtest", label: "Backtest", icon: Target },
];

interface SidebarProps {
  current: Page;
  onNavigate: (page: Page) => void;
  collapsed?: boolean;
}

export function Sidebar({ current, onNavigate, collapsed = false }: SidebarProps) {
  return (
    <aside
      className={cn(
        "flex h-full shrink-0 flex-col border-r border-sidebar-border/90 bg-sidebar text-sidebar-foreground transition-[width] duration-200",
        collapsed ? "w-14" : "w-60",
      )}
    >
      {/* Brand */}
      <div
        className={cn(
          "border-b border-sidebar-border px-3",
          collapsed ? "flex h-14 items-center justify-center" : "flex h-16 flex-col justify-center gap-0.5",
        )}
      >
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 shrink-0 text-sidebar-primary" />
          {!collapsed && (
            <span className="truncate text-[13px] font-semibold tracking-tight">
              Second Order
            </span>
          )}
        </div>
        {!collapsed && (
          <p className="pl-6 text-[11px] text-muted-foreground">
            Macro event research
          </p>
        )}
      </div>

      {/* Navigation */}
      <ScrollArea className="flex-1 py-3">
        {!collapsed && (
          <div className="px-3 pb-2">
            <p className="section-kicker">Workspace</p>
          </div>
        )}
        <nav className="flex flex-col gap-1 px-2">
          {NAV_ITEMS.map(({ id, label, icon: Icon }) => {
            const isActive = current === id;
            const btn = (
              <Button
                key={id}
                variant={isActive ? "secondary" : "ghost"}
                size="sm"
                className={cn(
                  "h-9 w-full justify-start rounded-xl text-[12px]",
                  collapsed && "justify-center px-0",
                  isActive && "bg-sidebar-accent text-sidebar-accent-foreground shadow-[inset_0_0_0_1px_rgba(15,23,42,0.04)]",
                )}
                onClick={() => onNavigate(id)}
              >
                <Icon className="h-3.5 w-3.5 shrink-0" />
                {!collapsed && <span className="truncate">{label}</span>}
              </Button>
            );

            if (collapsed) {
              return (
                <Tooltip key={id}>
                  <TooltipTrigger asChild>{btn}</TooltipTrigger>
                  <TooltipContent side="right">{label}</TooltipContent>
                </Tooltip>
              );
            }
            return btn;
          })}
        </nav>
      </ScrollArea>

      {/* Footer */}
      <div className="border-t border-sidebar-border px-3 py-2">
        {!collapsed && (
          <div className="space-y-0.5">
            <p className="section-kicker">Local-first</p>
            <p className="font-num text-2xs text-muted-foreground">v0.1.0</p>
          </div>
        )}
      </div>
    </aside>
  );
}
