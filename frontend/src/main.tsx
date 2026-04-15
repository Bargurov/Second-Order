import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./index.css";
import App from "./App";
import { SharePage } from "@/components/pages/share-page";

// ---------------------------------------------------------------------------
// URL-aware shell selection
//
// The app uses state-based internal routing (no React Router), so to support
// shell-free shareable pages we inspect the URL path at mount time.
// A /share/:eventId path renders SharePage in isolation; all other paths
// get the full App shell as before.
// ---------------------------------------------------------------------------

const _sharePath = /^\/share\/(\d+)\/?$/.exec(window.location.pathname);

const root = document.getElementById("root")!;

if (_sharePath) {
  const eventId = parseInt(_sharePath[1] ?? "0", 10);
  const qc = new QueryClient({
    defaultOptions: {
      queries: { staleTime: 300_000, retry: 1, refetchOnWindowFocus: false },
    },
  });
  createRoot(root).render(
    <StrictMode>
      <QueryClientProvider client={qc}>
        <SharePage eventId={eventId} />
      </QueryClientProvider>
    </StrictMode>,
  );
} else {
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}
