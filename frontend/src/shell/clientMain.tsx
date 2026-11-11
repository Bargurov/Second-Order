// The Client build's entry (client.html). It carries the shared shell, the user and onboarding contracts, the public
// pages a signed-out visitor sees and the Client app only: no Admin module, operator page, model or provider name, price
// table or cost text is bundled here.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/newsreader/400.css";
import "@fontsource/newsreader/500.css";
import "@fontsource/newsreader/400-italic.css";
import "@fontsource/instrument-sans/400.css";
import "@fontsource/instrument-sans/500.css";
import "@fontsource/instrument-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "../styles.css";
import { ClientApp } from "../client/ClientApp";
import { PublicApp } from "../public/PublicApp";
import { Shell } from "./Shell";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Shell build="client" render={(props) => <ClientApp {...props} />}
           signedOut={(props) => <PublicApp {...props} />} />
  </StrictMode>,
);
