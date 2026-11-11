import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// The Admin build's entry (index.html): the shared shell mounts the operator app and the Admin screens for an admin
// session. Fonts are bundled locally so the Dossier renders identically offline.
import "@fontsource/newsreader/400.css";
import "@fontsource/newsreader/500.css";
import "@fontsource/newsreader/400-italic.css";
import "@fontsource/instrument-sans/400.css";
import "@fontsource/instrument-sans/500.css";
import "@fontsource/instrument-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "./styles.css";
import { AdminApp } from "./admin/AdminApp";
import { Shell } from "./shell/Shell";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Shell build="admin" render={({ session, signOut }) => <AdminApp session={session} signOut={signOut} />} />
  </StrictMode>,
);
