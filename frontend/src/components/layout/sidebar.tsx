import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Newspaper,
  FlaskConical,
  Clock,
  Activity,
} from "lucide-react";

export type Page = "inbox" | "analyze" | "events";

const NAV_ITEMS: { id: Page; label: string; icon: React.ElementType }[] = [
  { id: "inbox", label: "News Inbox", icon: Newspaper },
  { id: "analyze", label: "Analysis", icon: FlaskConical },
  { id: "events", label: "Recent Events", icon: Clock },
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
        "flex h-full flex-col border-r bg-sidebar text-sidebar-foreground transition-[width] duration-200",
        collapsed ? "w-[52px]" : "w-56",
      )}
    >
      {/* Brand */}
      <div className="flex h-14 items-center gap-2 border-b px-3">
        <Activity className="h-5 w-5 shrink-0 text-sidebar-primary" />
        {!collapsed && (
          <span className="text-sm font-semibold tracking-tight">
            Second Order
          </span>
        )}
      </div>

      <Separator />

      {/* Navigation */}
      <ScrollArea className="flex-1 py-2">
        <nav className="flex flex-col gap-1 px-2">
          {NAV_ITEMS.map(({ id, label, icon: Icon }) => {
            const isActive = current === id;
            const btn = (
              <Button
                key={id}
                variant={isActive ? "secondary" : "ghost"}
                className={cn(
                  "w-full justify-start gap-2",
                  collapsed && "justify-center px-0",
                  isActive && "bg-sidebar-accent text-sidebar-accent-foreground",
                )}
                onClick={() => onNavigate(id)}
              >
                <Icon className="h-4 w-4 shrink-0" />
                {!collapsed && <span>{label}</span>}
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
      <div className="border-t px-3 py-2">
        {!collapsed && (
          <p className="text-[10px] text-muted-foreground">v0.1.0</p>
        )}
      </div>
    </aside>
  );
}
