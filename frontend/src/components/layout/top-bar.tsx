import { Button } from "@/components/ui/button";
import { PanelLeftClose, PanelLeft } from "lucide-react";
import type { Page } from "./sidebar";

const PAGE_TITLES: Record<Page, string> = {
  inbox: "News Inbox",
  analyze: "Analysis View",
  events: "Recent Events",
};

interface TopBarProps {
  page: Page;
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
}

export function TopBar({ page, sidebarCollapsed, onToggleSidebar }: TopBarProps) {
  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b bg-background px-4">
      <Button
        variant="ghost"
        size="icon"
        onClick={onToggleSidebar}
        aria-label="Toggle sidebar"
      >
        {sidebarCollapsed ? (
          <PanelLeft className="h-4 w-4" />
        ) : (
          <PanelLeftClose className="h-4 w-4" />
        )}
      </Button>

      <h1 className="text-base font-semibold">{PAGE_TITLES[page]}</h1>

      <div className="ml-auto flex items-center gap-2">
        <span className="text-xs text-muted-foreground">
          FastAPI backend &middot; localhost:8000
        </span>
      </div>
    </header>
  );
}
