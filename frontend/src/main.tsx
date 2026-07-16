import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./index.css";
import App from "./App";
import { SharePage } from "@/components/pages/share-page";
import { ErrorBoundary } from "@/components/error-boundary";
import { matchSharePath } from "@/lib/app-route";

// ---------------------------------------------------------------------------
// URL-aware shell selection
//
// The app uses state-based internal routing (no React Router), so to support
// shell-free shareable pages we inspect the URL path at mount time.
// A /share/:eventId path renders SharePage in isolation; all other paths
// get the full App shell, which resolves its own initial page (Market by
// default, Evidence Overview for the addressable /evidence route) through
// the same lib/app-route.ts seam.
// ---------------------------------------------------------------------------

const _shareEventId = matchSharePath(window.location.pathname);

const root = document.getElementById("root")!;

if (_shareEventId != null) {
  const eventId = _shareEventId;
  const qc = new QueryClient({
    defaultOptions: {
      queries: { staleTime: 300_000, retry: 1, refetchOnWindowFocus: false },
    },
  });
  createRoot(root).render(
    <StrictMode>
      <ErrorBoundary scope="app">
        <QueryClientProvider client={qc}>
          <SharePage eventId={eventId} />
        </QueryClientProvider>
      </ErrorBoundary>
    </StrictMode>,
  );
} else {
  createRoot(root).render(
    <StrictMode>
      <ErrorBoundary scope="app">
        <App />
      </ErrorBoundary>
    </StrictMode>,
  );
}
