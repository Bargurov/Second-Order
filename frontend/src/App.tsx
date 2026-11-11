import { lazy, Suspense, type ComponentType } from "react";
import { fetchIndex, useLoad } from "./api";
import { Page, TopBar } from "./components/Chrome";
import { AnalysesPage } from "./pages/AnalysesPage";
import { AssessmentPage } from "./pages/AssessmentPage";
import { DossierPage } from "./pages/DossierPage";
import { EventOverviewPage } from "./pages/EventOverviewPage";
import { HypothesesPage } from "./pages/HypothesesPage";
import { HypothesisPage } from "./pages/HypothesisPage";
import { LibraryCasePage } from "./pages/LibraryCasePage";
import { LibraryPage } from "./pages/LibraryPage";
import { LifecycleDossierPage } from "./pages/LifecycleDossierPage";
import { EventContextPage, MarketContextListPage } from "./pages/MarketContextPage";
import { MethodPage } from "./pages/MethodPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { TrackerPage } from "./pages/TrackerPage";
import { useLocation } from "./router";
import { matchRoute } from "./routes";

/** A page loaded on its first visit, kept out of the main bundle; a chunk that cannot be loaded (for example after a
 * rebuild while the page was open) says so instead of leaving the page blank. */
function deferred<P extends object>(load: () => Promise<ComponentType<P>>) {
  return lazy(() => load().then((page) => ({ default: page }), () => ({
    default: (() => <p role="alert">This page could not be loaded. Reload to try again.</p>) as ComponentType<P>,
  })));
}

const FindingsPage = deferred(() => import("./pages/FindingsPage").then((module) => module.FindingsPage));
const FindingsOccasionPage = deferred(() => import("./pages/FindingsOccasionPage")
  .then((module) => module.FindingsOccasionPage));
const G17TablesPage = deferred(() => import("./pages/G17TablesPage").then((module) => module.G17TablesPage));
const HistoricalCasePage = deferred(() => import("./pages/HistoricalCasePage")
  .then((module) => module.HistoricalCasePage));
const SnapshotPage = deferred(() => import("./pages/SnapshotPage").then((module) => module.SnapshotPage));
const PolicyResearchPage = deferred(() => import("./pages/PolicyResearchPage")
  .then((module) => module.PolicyResearchPage));
const ResearchAnalysisPage = deferred(() => import("./pages/ResearchAnalysisPage")
  .then((module) => module.ResearchAnalysisPage));
const ThesisPage = deferred(() => import("./pages/ThesisPage").then((module) => module.ThesisPage));
const CopperToolsPage = deferred(() => import("./pages/CopperToolsPage").then((module) => module.CopperToolsPage));
const EventChainsPage = deferred(() => import("./pages/EventChainsPage")
  .then((module) => module.EventChainsPage));
const CopperDeskPage = deferred(() => import("./pages/CopperDeskPage").then((module) => module.CopperDeskPage));
const ComparisonPage = deferred(() => import("./pages/ComparisonPage").then((module) => module.ComparisonPage));
const MetalsPage = deferred(() => import("./pages/MetalsPage").then((module) => module.MetalsPage));
const FuelsPage = deferred(() => import("./pages/FuelsPage").then((module) => module.FuelsPage));
const CompanyPage = deferred(() => import("./pages/CompanyPage").then((module) => module.CompanyPage));
const loadingPage = <p role="status">Loading the page…</p>;

export function App() {
  const { pathname, search } = useLocation();
  const [index, retryIndex] = useLoad(fetchIndex, "index");
  const route = matchRoute(pathname);

  let content;
  if (route.page === "index") {
    content = <TrackerPage index={index} onRetry={retryIndex} search={search} />;
  } else if (route.page === "method") {
    content = <MethodPage index={index} />;
  } else if (route.page === "dossier") {
    content = <DossierPage key={route.id} id={route.id} search={search} index={index} />;
  } else if (route.page === "library") {
    content = <LibraryPage search={search} />;
  } else if (route.page === "library-case") {
    content = <LibraryCasePage key={route.id} id={route.id} />;
  } else if (route.page === "historical-case") {
    content = <Suspense fallback={loadingPage}><HistoricalCasePage key={route.id} id={route.id} /></Suspense>;
  } else if (route.page === "research") {
    content = <Suspense fallback={loadingPage}><PolicyResearchPage key={route.id} id={route.id} /></Suspense>;
  } else if (route.page === "bis-snapshot") {
    content = <Suspense fallback={loadingPage}><SnapshotPage /></Suspense>;
  } else if (route.page === "analyses") {
    content = <AnalysesPage search={search} />;
  } else if (route.page === "market-context") {
    content = <MarketContextListPage />;
  } else if (route.page === "market-context-event") {
    content = <EventContextPage key={`${route.kind}:${route.id}`} kind={route.kind} id={route.id} />;
  } else if (route.page === "hypotheses") {
    content = <HypothesesPage />;
  } else if (route.page === "hypothesis") {
    content = <HypothesisPage key={route.id} id={route.id} />;
  } else if (route.page === "hypothesis-assessment") {
    content = <AssessmentPage key={`${route.id}:${route.evaluationId}`} id={route.id} evaluationId={route.evaluationId} />;
  } else if (route.page === "hypothesis-dossier") {
    content = <LifecycleDossierPage key={`${route.id}:${route.evaluationId}`} id={route.id}
                                    evaluationId={route.evaluationId} search={search} />;
  } else if (route.page === "findings") {
    content = <Suspense fallback={loadingPage}><FindingsPage /></Suspense>;
  } else if (route.page === "findings-g17") {
    content = <Suspense fallback={loadingPage}><G17TablesPage /></Suspense>;
  } else if (route.page === "findings-occasion") {
    content = <Suspense fallback={loadingPage}><FindingsOccasionPage key={route.day} day={route.day} /></Suspense>;
  } else if (route.page === "event-overview") {
    content = <EventOverviewPage key={`${route.kind}:${route.id}`} kind={route.kind} id={route.id} />;
  } else if (route.page === "research-analysis") {
    content = <Suspense fallback={loadingPage}><ResearchAnalysisPage key={route.captureId}
                                                                    captureId={route.captureId} /></Suspense>;
  } else if (route.page === "thesis") {
    content = <Suspense fallback={loadingPage}><ThesisPage key={`${route.id}:${route.version ?? "latest"}`}
                                                            id={route.id} version={route.version} /></Suspense>;
  } else if (route.page === "copper-tools") {
    content = <Suspense fallback={loadingPage}><CopperToolsPage /></Suspense>;
  } else if (route.page === "copper-events") {
    content = <Suspense fallback={loadingPage}><EventChainsPage /></Suspense>;
  } else if (route.page === "copper-desk") {
    content = <Suspense fallback={loadingPage}><CopperDeskPage /></Suspense>;
  } else if (route.page === "copper-comparison") {
    content = <Suspense fallback={loadingPage}><ComparisonPage key={route.id} id={route.id} /></Suspense>;
  } else if (route.page === "metals") {
    content = <Suspense fallback={loadingPage}><MetalsPage /></Suspense>;
  } else if (route.page === "fuels") {
    content = <Suspense fallback={loadingPage}><FuelsPage /></Suspense>;
  } else if (route.page === "company") {
    content = <Suspense fallback={loadingPage}><CompanyPage /></Suspense>;
  } else {
    const what = route.reason === "malformed"
      ? `The address ${pathname} contains an invalid percent-encoded sequence.`
      : `Nothing is served at ${pathname}.`;
    content = <NotFoundPage key={pathname} index={index} what={what} />;
  }

  return (
    <>
      <TopBar
        index={index}
        section={route.page === "index" || route.page === "bis-snapshot" ? "tracker" : route.page === "not-found" ? null
          : route.page === "library-case" || route.page === "historical-case" || route.page === "research"
            || route.page === "thesis" || route.page === "copper-tools" || route.page === "copper-events"
            || route.page === "metals"
            || route.page === "company" ? "library"
          : route.page === "copper-desk" || route.page === "copper-comparison" ? "copper"
          : route.page === "market-context-event" ? "market-context"
          : route.page === "event-overview" || route.page === "research-analysis" ? "event"
          : route.page === "hypothesis" || route.page === "hypothesis-assessment" || route.page === "hypothesis-dossier"
            ? "hypotheses" : route.page === "findings-occasion" || route.page === "findings-g17" ? "findings" : route.page}
        currentId={route.page === "dossier" ? route.id : undefined}
      />
      <Page>{content}</Page>
      <footer className="site-footer">
        <p>
          Second Order · local research tool, not trading advice. Nothing is frozen, downloaded, evaluated or prepared automatically: each needs its own explicit approval.
        </p>
      </footer>
    </>
  );
}
