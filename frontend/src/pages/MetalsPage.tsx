import { useEffect, useMemo, useState } from "react";
import { useLoad } from "../api";
import { Skeleton } from "../components/Chrome";
import { MetalsByMetal } from "../components/MetalDetail";
import { str, strings, TabList } from "../components/MetalsBits";
import { MetalsCompare, type OverviewMode, type Picked } from "../components/MetalsCompare";
import { MetalsMethod, PARTS, readSentence } from "../components/MetalsMethod";
import { MetalPicker } from "../components/MetalPicker";
import { fetchMetals, METAL_IDS, type Chapter, type MetalsView } from "../metals";
import { hashFor, picksFrom, searchFor, viewFrom, type MetalsTab } from "../metalsPicks";
import { Link } from "../router";
import "../library.css";
import "../thesis.css";
import "../metals.css";

const TAB_LABELS: { id: MetalsTab; label: string }[] = [
  { id: "overview", label: "Overview" }, { id: "by-metal", label: "By metal" }, { id: "method", label: "Method & sources" }];

/**
 * The metals comparison (/metals): for the metals a reader picks, where each is produced by country and stage, who
 * holds the known reserves, how concentrated both are, years of reserves at the 2025 rate, US import sources and
 * reliance, and, for the six IEA minerals, IEA demand by technology and supply by country, apart. Each metal also has
 * a snapshot and research parts: the supply chain by printed stage, concentration indicators with their coverage, IEA
 * energy-technology uses, structural exposure and sourced events, and assistant-written transmission chains whose every
 * link is labelled. Three tabs: the overview table (leaders or concentration), one metal at a time, and the method and
 * sources. The picks live in the address (?m=a,b), the tab and opened metal in its hash. The local API checks both
 * retained files against their acquisition records on every read; the reply is shown only after the fail-closed reader
 * (metals.ts, metalsStage2.ts) has recomputed every share, ranking, concentration and years figure and resolved every
 * research link again. The page computes nothing itself.
 */
export function MetalsPage() {
  const [loaded, retry] = useLoad(fetchMetals, "metals");
  useEffect(() => { document.title = "Metals · Second Order"; }, []);
  if (loaded.state === "loading") return <Skeleton />;
  if (loaded.state !== "ready") {
    return (
      <section className="state-panel" role="alert">
        <p>The metals comparison could not be read: {loaded.message}</p>
        <button type="button" className="button" onClick={retry}>Try again</button>
      </section>
    );
  }
  return <Metals view={loaded.data} />;
}

function Metals({ view }: { view: MetalsView }) {
  const frames = useMemo(() => view.usgs.chapters.map((item) => ({ id: item.id, name: str(item.name) || item.id })),
    [view]);
  const defaults = strings(view.deep);
  const [start] = useState(() => picksFrom(window.location.search, METAL_IDS, defaults));
  const [picks, setPicks] = useState<string[]>(start.picks);
  const [ignored, setIgnored] = useState(start.ignored);
  const [{ tab, metal }, setView] = useState(() => viewFrom(window.location.hash, start.picks));
  const [mode, setMode] = useState<OverviewMode>("leaders");
  const address = (search: string, hash: string) =>
    window.history.replaceState(window.history.state, "", `${window.location.pathname}${search}${hash}`);
  useEffect(() => {  // A hash typed or followed by hand opens its tab, as a click would.
    const follow = () => setView(viewFrom(window.location.hash, picks));
    window.addEventListener("hashchange", follow);
    return () => window.removeEventListener("hashchange", follow);
  }, [picks]);

  const choosePicks = (next: string[]) => {
    const kept = metal !== null && next.includes(metal) ? metal : null;
    setPicks(next);
    setIgnored(0);
    setView({ tab, metal: kept });
    address(searchFor(next), hashFor(tab, kept));
  };
  const chooseTab = (next: MetalsTab) => {
    setView({ tab: next, metal });
    address(window.location.search, hashFor(next, metal));
  };
  const openMetal = (id: string) => {
    setView({ tab: "by-metal", metal: id });
    address(window.location.search, hashFor("by-metal", id));
    window.requestAnimationFrame(() => document.getElementById("mt-tab-by-metal")?.scrollIntoView({ block: "nearest" }));
  };
  const openPicker = () => document.querySelector<HTMLButtonElement>(".mt-picker-button")?.click();

  const chapters = view.usgs.state === "available" ? view.usgs.chapters as Chapter[] : null;
  const picked: Picked[] = picks.map((id) => ({
    id, name: frames.find((item) => item.id === id)?.name ?? id,
    chapter: chapters?.find((item) => item.id === id) ?? null,
  }));
  const allShown = view.usgs.state === "available" && view.iea.state === "available";
  const panel = (id: MetalsTab) => ({ role: "tabpanel", id: `mt-panel-${id}`, "aria-labelledby": `mt-tab-${id}`,
    hidden: tab !== id, tabIndex: tab === id ? 0 : undefined, className: "mt-panel", "data-panel": id });
  return (
    <article className="library-case mt-page" data-metals="">
      <nav className="library-crumbs" aria-label="Case library">
        <Link to="/library">← Case library</Link>
        <Link to="/copper" className="desk-link" data-desk-link="">Copper desk</Link>
        <span>Metals</span>
      </nav>
      <header className="library-case-header mt-header" aria-labelledby="mt-title">
        <p className="kicker">Metals · Production and reserves</p>
        <h1 id="mt-title">Where metals come from</h1>
        <p className="mt-lead">Where each metal is produced, who holds the known reserves, and how concentrated both
          are.</p>
        <p className={`mt-status${allShown ? "" : " is-withheld"}`} data-read={allShown ? "available" : "withheld"}>
          <span className="mt-status-dot" aria-hidden="true" />
          {allShown ? <>USGS and IEA files match their acquisition records. <span className="mt-status-aside">No price
            view, projection or advice.</span></>
            : PARTS.map((part, at) => (
              <span key={part.key}>{at > 0 && "; "}{readSentence(view, part.key, part.label)}</span>))}
        </p>
      </header>

      <div className="mt-toolbar">
        <MetalPicker frames={frames} picks={picks} defaults={defaults} onChange={choosePicks} />
        {ignored > 0 && (
          <p className="mt-ignored" data-ignored={ignored} role="note">
            {ignored === 1 ? "One name in the address was" : `${ignored} names in the address were`} ignored: not a
            metal on this page, or repeated.</p>)}
      </div>

      <TabList label="Metals page" className="mt-tabs" tabs={TAB_LABELS} active={tab} onSelect={chooseTab}
               idFor={(id) => `mt-tab-${id}`} panelFor={(id) => `mt-panel-${id}`} />
      <section {...panel("overview")}>
        {tab === "overview" && <MetalsCompare view={view} picked={picked} mode={mode} onMode={setMode}
                                              onOpen={openMetal} onPick={openPicker} />}
      </section>
      <section {...panel("by-metal")}>
        {tab === "by-metal" && <MetalsByMetal view={view} picked={picked} opened={metal} onOpen={openMetal}
                                              onPick={openPicker} />}
      </section>
      <section {...panel("method")}>
        {tab === "method" && <MetalsMethod view={view} />}
      </section>
    </article>
  );
}
