import { useEffect, useState } from "react";
import { useLoad } from "../api";
import { Skeleton } from "../components/Chrome";
import { Plain, SectionHead } from "../components/CopperBits";
import { CopperCoverage } from "../components/CopperCoverage";
import { CopperProducers } from "../components/CopperProducers";
import { CHAIN, CHAIN_NOTE, LINK_STATUSES } from "../copperQuestion";
import { fetchCopperTools, type CopperToolsView, type RecordItem } from "../copperTools";
import { formatUtc, shortHash } from "../format";
import { Link } from "../router";
import "../library.css";
import "../policyResearch.css";
import "../thesis.css";
import "../copperTools.css";

const SCENARIO_LABEL: Record<string, string> = { cps: "Current Policies", steps: "Stated Policies", hd: "High Demand" };
const NOT_CLAIMED = ["No price view, and no direction of any price.", "No projection by this project.",
  "No shortage, surplus, deficit or balance claim.", "No cost curve and no marginal mine.",
  "No incentive price of this project's own.", "No statement about any company's shares.",
  "No claim that AI moves copper demand."];

/**
 * The copper tools (/theses/copper/tools, operator build): a coverage calculator on the IEA Critical Minerals Dataset
 * 2026 and a published producer unit-cost comparison. The local API checks every retained source on this machine
 * against its acquisition record and every figure where it is cited; the reply is shown only after the fail-closed
 * reader (copperTools.ts) has recomputed every computed value. The page computes nothing itself.
 */
export function CopperToolsPage() {
  const [loaded, retry] = useLoad(fetchCopperTools, "copper-tools");
  useEffect(() => { document.title = "Copper tools · Second Order"; }, []);
  if (loaded.state === "loading") return <Skeleton />;
  if (loaded.state !== "ready") {
    return (
      <section className="state-panel" role="alert">
        <p>The copper tools could not be read: {loaded.message}</p>
        <button type="button" className="button" onClick={retry}>Try again</button>
      </section>
    );
  }
  return <Tools view={loaded.data} />;
}

function Tools({ view }: { view: CopperToolsView }) {
  const [records, setRecords] = useState<RecordItem[]>(view.scenarios.records);
  const verified = view.sources.filter((source) => source.state === "verified").length;
  return (
    <article className="library-case ct-page" data-tools="copper">
      <nav className="library-crumbs" aria-label="Case library">
        <Link to="/theses/copper">← Copper thesis</Link>
        <Link to="/copper" className="desk-link" data-desk-link="">Copper desk</Link>
        <span>Tools</span>
      </nav>
      <header className="library-case-header ct-header" aria-labelledby="ct-title">
        <p className="kicker">01 · Copper tools</p>
        <h1 id="ct-title">Copper coverage and producer costs</h1>
        <p className="thesis-disclaimer">Tools, not a view. Nothing here is a projection by this project.</p>
        <p className="thesis-check" data-check={view.catalog.verified === view.catalog.items ? "available" : "withheld"}>
          <strong>On this read:</strong> {view.catalog.verified} of {view.catalog.items} figures and passages found where
          cited; {verified} of {view.sources.length} sources match their acquisition records. A figure that is not
          verified withholds everything that uses it.</p>
        <p className="ct-legend">Every number is marked: <span className="ct-kind" data-kind="published">P</span> published
          in a retained source, <span className="ct-kind" data-kind="assumption">A</span> your assumption,{" "}
          <span className="ct-kind" data-kind="computed">C</span> computed by fixed code (≈ when rounded for display; the
          exact value is kept), <span className="ct-kind" data-kind="missing">M</span> missing.</p>
      </header>

      <section id="question" className="library-section-block ct-section ct-question" aria-labelledby="question-title">
        <SectionHead id="question" kicker="02 · The wider question"
                     title="Where copper sits in the AI and electrification question">
          <Plain>{CHAIN_NOTE}</Plain>
        </SectionHead>
        <ol className="ct-chain">{CHAIN.map((link) => (
          <li key={link.id} data-link={link.id} data-status={link.status}>
            <span className="ct-chain-id">{link.id}</span> {link.text}
            <span className="ct-chain-status" title={LINK_STATUSES[link.status]}>{LINK_STATUSES[link.status].split(":")[0]}</span>
            {link.links.map((item) => <Link key={item.href + item.label} to={item.href}>{item.label}</Link>)}
          </li>))}</ol>
      </section>

      <section id="boundary" className="library-section-block ct-section" aria-labelledby="boundary-title">
        <SectionHead id="boundary" kicker="03 · The accounting boundary" title="What each quantity counts">
          <Plain>Refined copper is mostly mined copper one step later, so adding the two counts the same metal twice.</Plain>
        </SectionHead>
        <pre className="ct-diagram" aria-label="Copper flows from mines and scrap to use">{[
          "ore → MINE OUTPUT M ────────→ smelting and refining → PRIMARY REFINED",
          "old scrap ─┬→ secondary refining ────────────────────→ SECONDARY REFINED",
          "new scrap ─┘                                           ↓ refined use",
          "            └→ direct melt at mills ───────────────────→ FIRST USE → FINAL DEMAND"].join("\n")}</pre>
        <p className="ct-note">Retained here: world demand (the IEA does not state which of refined use, first use or final
          demand it counts), counted mine supply, and the IEA refining series, shown apart. Not retained: world
          recycling, stocks and their changes.</p>
      </section>

      <CopperCoverage view={view} onSaved={setRecords} />

      <section id="records" className="library-section-block ct-section" aria-labelledby="records-title">
        <SectionHead id="records" kicker="Saved scenarios" title="Records on this machine, checked again on this read" />
        {records.length === 0 ? <p className="ct-note">No scenario has been saved on this machine.</p> : (
          <ul className="ct-records">{records.map((record) => (
            <li key={record.id} data-record={record.id} data-state={record.state}>
              <strong>{record.label ?? "Unreadable record"}</strong>{record.baseline &&
                <> · {SCENARIO_LABEL[record.baseline.scenario]} {record.baseline.year}</>}
              {" "}· <code>{shortHash(record.id, 12)}</code>{record.created_at && <> · saved {formatUtc(record.created_at)}</>}
              <span className="ct-record-state">{view.scenarios.labels[record.state]}</span>
              {record.problems.length > 0 && <ul>{record.problems.map((problem) => <li key={problem}>{problem}</li>)}</ul>}
            </li>))}</ul>)}
        {view.scenarios.other_versions > 0 && <p className="ct-note">{view.scenarios.other_versions} record(s) of another
          version are kept and not shown.</p>}
      </section>

      <CopperProducers view={view} />

      <section id="not-claimed" className="library-section-block ct-section" aria-labelledby="not-claimed-title">
        <SectionHead id="not-claimed" kicker="11 · Not claimed" title="What these tools do not say" />
        <ul className="ct-not-claimed">{NOT_CLAIMED.map((text) => <li key={text}>{text}</li>)}</ul>
      </section>

      <footer id="sources" className="library-section-block thesis-sources" aria-labelledby="sources-title">
        <p className="kicker">Where every figure comes from</p>
        <h2 id="sources-title">Sources</h2>
        <ol className="thesis-source-list">{view.sources.map((source) => (
          <li key={source.id} data-source={source.id} data-state={source.state}>
            <p className="thesis-source-name"><strong>{source.publisher}</strong> · {source.title}</p>
            <dl className="thesis-source-facts">
              <div><dt>Edition</dt><dd>{source.edition}</dd></div>
              <div><dt>State</dt><dd className="thesis-source-state">{source.detail}</dd></div>
              <div><dt>Terms</dt><dd>{source.terms.licence}. {source.terms.note}</dd></div>
              <div><dt>Retrieved</dt><dd>{formatUtc(source.retrieved_at)}, {source.origin === "get"
                ? "by one GET of the address below" : "downloaded by the owner and retained"}</dd></div>
              <div><dt>File</dt><dd><a className="library-external" href={source.url} target="_blank"
                rel="noreferrer">{source.url}</a><span className="thesis-hash">SHA-256 {shortHash(source.sha256, 16)}</span></dd></div>
            </dl>
          </li>))}</ol>
      </footer>
    </article>
  );
}
