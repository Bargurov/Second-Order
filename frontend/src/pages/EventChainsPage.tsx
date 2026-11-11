import { useEffect, useState } from "react";
import { useLoad } from "../api";
import { Skeleton } from "../components/Chrome";
import { EventChainCard } from "../components/EventChainCard";
import { fetchEventChains, type EventChainsView } from "../eventChains";
import { Link } from "../router";
import "../library.css";
import "../policyResearch.css";
import "../thesis.css";
import "../eventChains.css";

export const PAGE_SENTENCE = "Each chain shows one possible path from a past event to a reason or risk of the copper "
  + "thesis. A chain is not evidence that the event caused anything and is not a forecast. Your reading is your own "
  + "view.";

/**
 * The copper event chains (/theses/copper/events, admin only). The reply is shown only after the fail-closed reader
 * (eventChains.ts) has accepted it. The last accepted view stays on screen while a reload runs, so unsent text in a
 * form is never lost to a reload.
 */
export function EventChainsPage() {
  const [loaded, retry] = useLoad(fetchEventChains, "copper-events");
  const [shown, setShown] = useState<EventChainsView | null>(null);
  useEffect(() => { document.title = "Copper event chains · Second Order"; }, []);
  useEffect(() => { if (loaded.state === "ready") setShown(loaded.data); }, [loaded]);
  if (shown === null) {
    if (loaded.state === "loading" || loaded.state === "ready") return <Skeleton />;
    return (
      <section className="state-panel" role="alert">
        <p>The copper event chains could not be read: {loaded.message}</p>
        <button type="button" className="button" onClick={retry}>Try again</button>
      </section>
    );
  }
  return (
    <article className="library-case ec-page" data-page="copper-events">
      <nav className="library-crumbs" aria-label="Case library">
        <Link to="/theses/copper">Copper thesis</Link>
        <Link to="/copper" className="desk-link" data-desk-link="">Copper desk</Link>
        <span>Event chains</span>
      </nav>
      <header className="library-case-header" aria-labelledby="ec-title">
        <p className="kicker">Copper thesis · event chains</p>
        <h1 id="ec-title">Copper event chains</h1>
        <p className="thesis-disclaimer" data-sentence="page">{PAGE_SENTENCE}</p>
      </header>
      {loaded.state === "error" && (
        <p className="ec-error-banner" role="alert">The chains could not be refreshed: {loaded.message}{" "}
          <button type="button" className="button" onClick={retry}>Try again</button></p>)}
      {shown.chains.length === 0 && <p className="ec-none">No event chain is published.</p>}
      {shown.chains.map((chain) => <EventChainCard key={chain.id} chain={chain} onReload={retry} />)}
    </article>
  );
}
