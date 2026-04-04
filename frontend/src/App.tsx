import { useState } from "react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Sidebar, type Page } from "@/components/layout/sidebar";
import { TopBar } from "@/components/layout/top-bar";
import { NewsInbox } from "@/components/pages/news-inbox";
import { AnalysisView } from "@/components/pages/analysis-view";
import { RecentEvents } from "@/components/pages/recent-events";

const PAGES: Record<Page, React.FC> = {
  inbox: NewsInbox,
  analyze: AnalysisView,
  events: RecentEvents,
};

export default function App() {
  const [page, setPage] = useState<Page>("inbox");
  const [collapsed, setCollapsed] = useState(false);

  const PageComponent = PAGES[page];

  return (
    <TooltipProvider delayDuration={0}>
      <div className="flex h-screen overflow-hidden">
        <Sidebar
          current={page}
          onNavigate={setPage}
          collapsed={collapsed}
        />
        <div className="flex flex-1 flex-col overflow-hidden">
          <TopBar
            page={page}
            sidebarCollapsed={collapsed}
            onToggleSidebar={() => setCollapsed((c) => !c)}
          />
          <main className="flex-1 overflow-auto p-6">
            <PageComponent />
          </main>
        </div>
      </div>
    </TooltipProvider>
  );
}
