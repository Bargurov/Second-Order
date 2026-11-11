import { Fragment, useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { useLoad } from "../api";
import { Skeleton } from "../components/Chrome";
import {
  CompanyContext, DataTable, dateLine, Figure, Fold, KindBadge, BADGE_TITLE, Line, Lines, Scroll, SOURCE_SHORT, Stamp,
  Tag, useCompany, Withheld, Words, type BadgeKind,
} from "../components/CompanyBits";
import { CALC_HASH, calcOf, Scenarios } from "../components/CompanyScenarios";
import { TabList } from "../components/MetalsBits";
import {
  basisWords, cellText, fetchCompany, figureKind, figureText, isFigure, unitWords, type CompanyView, type FigureRecord,
  type Step,
} from "../companyResearch";
import { formatDay } from "../format";
import { Link } from "../router";
import "../library.css";
import "../metals.css";
import "../copperTools.css";
import "../company.css";

type Tab = "overview" | "business" | "numbers" | "mechanisms" | "scenarios" | "questions" | "method";
const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" }, { id: "business", label: "Business" }, { id: "numbers", label: "Numbers" },
  { id: "mechanisms", label: "Mechanisms" }, { id: "scenarios", label: "Scenarios" },
  { id: "questions", label: "Open questions" }, { id: "method", label: "Method & sources" }];
const TAB_IDS = TABS.map((tab) => tab.id);
const WITH_SUB: Tab[] = ["numbers", "scenarios"];

/** The tab and its view a hash opens: "#numbers:nine-months", "#scenarios:cash-flow"; anything else is the overview. */
function fromHash(hash: string): { tab: Tab; numbers: string | null } {
  const [tab, sub] = hash.replace(/^#/, "").split(":");
  return TAB_IDS.includes(tab as Tab) ? { tab: tab as Tab, numbers: WITH_SUB.includes(tab as Tab) ? sub ?? null : null }
    : { tab: "overview", numbers: null };
}
const hashFor = (tab: Tab, numbers: string | null) =>
  tab === "overview" ? "" : `#${tab}${WITH_SUB.includes(tab) && numbers ? `:${numbers}` : ""}`;

/**
 * The FCX company page (/companies/fcx), admin only: how the copper price reaches Freeport-McMoRan's cash flow, from
 * the committed research package and its four retained documents, verified by the server on every read. The first
 * screen holds the summary, six figures and what changed; the business, the full tables, the mechanisms, the open
 * questions and the sources open by choice. Every number comes from a record: a reported figure (P), a company estimate
 * (F) or this project's computation (C), and clicking it opens its source, page and quote, or its formula. The reply is
 * shown only after the fail-closed reader (companyResearch.ts) has recomputed every computed figure; a figure resting on
 * a document that is missing or changed is withheld, and so is every line that names it. No valuation, no share price.
 */
export function CompanyPage() {
  const [loaded, retry] = useLoad(fetchCompany, "company-fcx");
  useEffect(() => { document.title = "Freeport-McMoRan · Second Order"; }, []);
  if (loaded.state === "loading") return <Skeleton />;
  if (loaded.state !== "ready") {
    return (
      <section className="state-panel" role="alert" data-company-error="">
        <p>The FCX research could not be shown: {loaded.message}</p>
        <button type="button" className="button" onClick={retry}>Try again</button>
      </section>
    );
  }
  return <Company view={loaded.data} reload={retry} />;
}

function Company({ view, reload }: { view: CompanyView; reload: () => void }) {
  const [{ tab, numbers }, setPlace] = useState(() => fromHash(window.location.hash));
  const [detail, setDetail] = useState<string | null>(null);
  const opener = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const follow = () => setPlace(fromHash(window.location.hash));
    window.addEventListener("hashchange", follow);
    return () => window.removeEventListener("hashchange", follow);
  }, []);
  const go = (next: Tab, sub: string | null = null) => {
    setPlace({ tab: next, numbers: sub });
    window.history.replaceState(window.history.state, "", `${window.location.pathname}${window.location.search}${hashFor(next, sub)}`);
  };
  const open = useCallback((id: string, from: HTMLElement | null) => {
    if (from) opener.current = from;
    setDetail(id);
  }, []);
  const close = useCallback(() => {
    setDetail(null);
    window.requestAnimationFrame(() => opener.current?.focus());
  }, []);
  const context = useMemo(() => ({ view, open, reload }), [view, open, reload]);
  const page = view.page;
  const allShown = view.verified === view.sources.length;
  const panel = (id: Tab) => ({ role: "tabpanel", id: `co-panel-${id}`, "aria-labelledby": `co-tab-${id}`,
    hidden: tab !== id, tabIndex: tab === id ? 0 : undefined, className: "mt-panel co-panel", "data-panel": id });
  return (
    <CompanyContext.Provider value={context}>
      <article className="library-case mt-page co-page" data-company="fcx">
        <nav className="library-crumbs" aria-label="Case library">
          <Link to="/library">← Case library</Link>
          <Link to="/copper" className="desk-link" data-desk-link="">Copper desk</Link>
          <span>{page.company.name}</span>
        </nav>
        <header className="library-case-header mt-header co-header" aria-labelledby="co-title">
          <p className="kicker">{page.company.kicker}</p>
          <h1 id="co-title">{page.company.name} ({page.company.short})</h1>
          <p className="mt-lead">{page.question}</p>
          <p className={`mt-status${allShown ? "" : " is-withheld"}`} data-read={allShown ? "available" : "withheld"}
             data-verified={view.verified}>
            <span className="mt-status-dot" aria-hidden="true" />
            {view.verified} of {view.sources.length} source files match their acquisition records.
            {!allShown && " Figures that rest on the others are not shown."} Figures to {formatDay(page.figures_to)}.{" "}
            <span className="mt-status-aside">No valuation, target price or advice.</span>
          </p>
        </header>

        <TabList label="Company page" className="mt-tabs co-tabs" tabs={TABS} active={tab} onSelect={(id) => go(id)}
                 idFor={(id) => `co-tab-${id}`} panelFor={(id) => `co-panel-${id}`} />
        <section {...panel("overview")}>{tab === "overview" && <Overview />}</section>
        <section {...panel("business")}>{tab === "business" && <Business />}</section>
        <section {...panel("numbers")}>{tab === "numbers" && <Numbers view={numbers} onView={(sub) => go("numbers", sub)} />}</section>
        <section {...panel("mechanisms")}>{tab === "mechanisms" && <Mechanisms />}</section>
        <section {...panel("scenarios")}>{tab === "scenarios" && <Scenarios mode={calcOf(numbers)}
          onMode={(mode) => go("scenarios", CALC_HASH[mode])} />}</section>
        <section {...panel("questions")}>{tab === "questions" && <Questions />}</section>
        <section {...panel("method")}>{tab === "method" && <Method />}</section>
      </article>
      {detail !== null && <FigureDetail id={detail} onClose={close} />}
    </CompanyContext.Provider>
  );
}

function Legend() {
  return (
    <p className="co-legend" data-legend="">
      {([["published", "Reported"], ["estimate", "Company estimate"], ["computed", "Computed by this project"]] as
        [BadgeKind, string][]).map(([kind, words]) => <span key={kind}><KindBadge kind={kind} /> {words}</span>)}
      <span>Click a figure for its source and page</span>
    </p>
  );
}

// ---------------------------------------------------------------- overview: the first screen

function Overview() {
  const { view } = useCompany();
  const page = view.page;
  return (
    <>
      <div className="co-first">
        <section className="co-summary" aria-labelledby="co-summary-title">
          <div className="co-section-head">
            <h2 id="co-summary-title">In brief</h2>
            <Stamp />
          </div>
          <div className="co-summary-text">
            {page.summary.map((block, at) => <Line key={at} block={block} tag={false} />)}
          </div>
          <Fold part="summary-more" title="The fuller summary" teaser="Business, costs, cash flow and FCX's share">
            <Lines blocks={page.summary_more} />
          </Fold>
        </section>
        <section aria-labelledby="co-figures-title" className="co-first-side">
          <div className="co-section-head"><h2 id="co-figures-title">Key figures</h2></div>
          <ul className="co-tiles">{page.tiles.map((tile) => <TileCard key={tile.id} tile={tile} />)}</ul>
          <Legend />
        </section>
        <section aria-labelledby="co-changes-title" className="co-changes-part">
          <div className="co-section-head">
            <h2 id="co-changes-title">What changed</h2>
            <p className="co-sub">Third quarter of 2026 against a year earlier</p>
          </div>
          <ul className="co-changes">{page.changes.map((change) => <ChangeItem key={change.id} change={change} />)}</ul>
        </section>
      </div>
      <Fold part="reading-guide" title="How to read these figures" teaser="Periods, bases and the one-off insurance gain">
        <Lines blocks={page.reading_guide} tag={false} />
      </Fold>
    </>
  );
}

function TileCard({ tile }: { tile: CompanyView["page"]["tiles"][number] }) {
  const { view } = useCompany();
  const [open, setOpen] = useState(false);
  const noteId = useId();
  const record = view.records[tile.value] as FigureRecord;
  const compare = view.records[tile.compare] as FigureRecord;
  return (
    <li className="co-tile" data-tile={tile.id} data-state={record.state}>
      <p className="co-tile-label">{tile.label}<span className="co-tile-period"> · {record.period.label}</span></p>
      <p className="co-tile-value"><Figure id={tile.value} tone="tile" /></p>
      <p className="co-tile-unit">{unitWords(record.unit)} · {basisWords(record.basis)}</p>
      <p className="co-tile-compare">{tile.compare_label}: <Figure id={tile.compare} />
        <span className="co-sub"> · {compare.period.label}</span></p>
      {tile.note && <>
        <button type="button" className="co-tile-note-button" aria-expanded={open} aria-controls={noteId}
                data-note-button={tile.id} onClick={() => setOpen(!open)}>{tile.note_label ?? "Note"}</button>
        <p id={noteId} className="co-tile-note" hidden={!open}><Words block={tile.note} /></p>
      </>}
    </li>
  );
}

function ChangeItem({ change }: { change: CompanyView["page"]["changes"][number] }) {
  const [open, setOpen] = useState(false);
  const id = `co-change-${change.id}`;
  return (
    <li className="co-change" data-change={change.id} data-state={change.state}>
      <p><Tag kind={change.kind} /> <Words block={change} />{" "}
        <button type="button" className="co-more" aria-expanded={open} aria-controls={id}
                onClick={() => setOpen(!open)}>{open ? "Less" : "Why and how"}</button></p>
      <div id={id} className="co-change-detail" hidden={!open}>
        {change.passages.length > 0 && change.state === "available" && <QuoteList ids={change.passages} />}
        <Lines blocks={change.detail} />
      </div>
    </li>
  );
}

function QuoteList({ ids }: { ids: string[] }) {
  const { view } = useCompany();
  return <div className="co-quotes">{ids.map((pid) => {
    const passage = view.passages[pid];
    return passage.state === "available" ? <figure key={pid} className="co-quote" data-passage={pid}>
      <blockquote>“{passage.quote}”</blockquote>
      <figcaption>{SOURCE_SHORT[passage.source]}, page {passage.printed_page ?? passage.page}</figcaption>
    </figure> : <Withheld key={pid} problem={passage.problem} />;
  })}</div>;
}

// ---------------------------------------------------------------- business

function Business() {
  const { view } = useCompany();
  return (
    <>
      <h2 className="co-h2">The business</h2>
      <Stamp />
      {view.page.business.map((section) => (
        <Fold key={section.id} part={section.id} title={section.title} teaser={section.teaser}
              open={section.open === "yes" ? true : undefined}>
          {section.assets && <Assets assets={section.assets} />}
          <Lines blocks={section.blocks} />
        </Fold>))}
    </>
  );
}

function Assets({ assets }: { assets: NonNullable<CompanyView["page"]["business"][number]["assets"]> }) {
  return (
    <Scroll label="Key assets and ownership">
      <table className="mt-table co-table">
        <caption>Key assets and ownership</caption>
        <thead><tr><th scope="col">Asset</th><th scope="col">Where</th><th scope="col">What it is</th>
          <th scope="col" className="mt-num">FCX's interest</th><th scope="col">How it is reported</th></tr></thead>
        <tbody>{assets.map((asset) => (
          <tr key={asset.name}><th scope="row">{asset.name}</th><td>{asset.place}</td><td>{asset.what}</td>
            <td className="mt-num">{asset.record ? <Figure id={asset.record} tone="cell" /> : "Wholly owned"}</td>
            <td>{asset.reported}</td></tr>))}</tbody>
      </table>
    </Scroll>
  );
}

// ---------------------------------------------------------------- numbers

function Numbers({ view: chosen, onView }: { view: string | null; onView: (id: string) => void }) {
  const { view } = useCompany();
  const numbers = view.page.numbers;
  const active = numbers.views.find((item) => item.id === chosen) ?? numbers.views[0];
  const [register, setRegister] = useState(false);
  return (
    <>
      <h2 className="co-h2">Numbers</h2>
      <p className="co-plain">Quarter, nine months and year are separate views; a change is shown only between periods of
        the same length. Each row holds one basis.</p>
      <TabList label="Period" className="mt-chooser co-chooser" tabs={numbers.views.map((item) => ({ id: item.id,
        label: item.label }))} active={active.id} onSelect={onView} idFor={(id) => `co-view-${id}`}
               panelFor={(id) => `co-view-panel-${id}`} />
      <div role="tabpanel" id={`co-view-panel-${active.id}`} aria-labelledby={`co-view-${active.id}`}
           className="co-view" data-view={active.id}>
        <DataTable table={active.main} change />
        {active.more.map((table) => (
          <Fold key={table.title} part={`${active.id}-${table.title}`} title={table.title}>
            <DataTable table={table} change={table.columns[table.columns.length - 1] === "Change"} />
          </Fold>))}
      </div>
      <h3 className="co-h3">At dates, and the company's outlook</h3>
      {numbers.dated.map((table) => (
        <Fold key={table.title} part={table.title} title={table.title}><DataTable table={table} /></Fold>))}
      <Fold part="difference" title="Where the release and the 10-Q differ" teaser="Operating cash flows for 2025">
        <Lines blocks={numbers.difference} />
      </Fold>
      <Fold part="register" title="Every figure" teaser={`All ${Object.keys(view.records).length} records, filterable`}
            onToggle={setRegister}>
        {register && <Register />}
      </Fold>
    </>
  );
}

function Register() {
  const { view } = useCompany();
  const [source, setSource] = useState("all");
  const [kind, setKind] = useState("all");
  const [find, setFind] = useState("");
  const [limit, setLimit] = useState(100);
  const figures = Object.values(view.records).filter(isFigure);
  const matches = figures.filter((record) => (source === "all" || (record.kind === "published" ? record.source
    : "computed") === source) && (kind === "all" || figureKind(record) === kind)
    && (find === "" || `${record.metric} ${record.id} ${record.period.label}`.toLowerCase().includes(find.toLowerCase())));
  return (
    <div className="co-register" data-register="">
      <div className="co-filters">
        <label>Source <select value={source} onChange={(event) => setSource(event.target.value)}>
          <option value="all">All</option>
          {view.sources.map((item) => <option key={item.id} value={item.id}>{SOURCE_SHORT[item.id]}</option>)}
          <option value="computed">Computed by this project</option></select></label>
        <label>Kind <select value={kind} onChange={(event) => setKind(event.target.value)}>
          <option value="all">All</option><option value="published">Reported</option>
          <option value="estimate">Company estimate</option><option value="computed">Computed</option></select></label>
        <label>Find <input type="search" value={find} onChange={(event) => setFind(event.target.value)} /></label>
      </div>
      <p className="co-sub" role="status">{matches.length} of {figures.length} figures</p>
      <Scroll label="Every figure">
        <table className="mt-table co-table">
          <caption>Every figure</caption>
          <thead><tr><th scope="col">Figure</th><th scope="col">Period</th><th scope="col" className="mt-num">Value</th>
            <th scope="col">Unit and basis</th></tr></thead>
          <tbody>{matches.slice(0, limit).map((record) => (
            <tr key={record.id}><th scope="row">{record.metric}</th><td>{record.period.label}</td>
              <td className="mt-num"><Figure id={record.id} tone="cell" /></td>
              <td className="co-unit-cell">{unitWords(record.unit)} · {basisWords(record.basis)}</td></tr>))}</tbody>
        </table>
      </Scroll>
      {matches.length > limit && <button type="button" className="button co-show-all"
                                          onClick={() => setLimit(matches.length)}>Show all {matches.length}</button>}
    </div>
  );
}

// ---------------------------------------------------------------- mechanisms

const LINK_WORDS: Record<Step["link"], string> = {
  stated: "Stated in a source", conditional: "Conditional mechanism", not_measured: "Not measured" };

function Mechanisms() {
  const { view } = useCompany();
  const m = view.page.mechanisms;
  const first = m.sensitivities.slice(0, 2), rest = m.sensitivities.slice(2);
  return (
    <>
      <h2 className="co-h2">From the copper price to cash</h2>
      <Stamp />
      <ol className="co-chain">{m.steps.map((step) => (
        <li key={step.id} className="co-step" data-link={step.link} data-step={step.id}>
          <h3>{step.title} <span className="co-link-tag" data-link={step.link}>{LINK_WORDS[step.link]}</span></h3>
          <Lines blocks={step.blocks} />
        </li>))}</ol>

      <section aria-labelledby="co-sens-title" className="co-sens">
        <h3 id="co-sens-title" className="co-h3">The company's published sensitivities, as published</h3>
        <ul className="co-cards">{first.map((item) => <SensitivityCard key={item.id} item={item} />)}</ul>
        <Line block={m.sensitivity_note} />
        <Fold part="more-sensitivities" title="More published sensitivities" teaser="Gold, molybdenum, noncontrolling
          interests and provisional pricing">
          <ul className="co-cards">{rest.map((item) => <SensitivityCard key={item.id} item={item} />)}</ul>
        </Fold>
      </section>
      <BagdadCard />
    </>
  );
}

function SensitivityCard({ item }: { item: CompanyView["page"]["mechanisms"]["sensitivities"][number] }) {
  const { view } = useCompany();
  const record = view.records[item.record] as FigureRecord;
  return (
    <li className="co-card" data-sensitivity={item.id}>
      <p className="kicker">{item.measure}</p>
      <p className="co-card-value"><Figure id={item.record} /></p>
      <p className="co-card-per">{record.metric}</p>
      <dl className="co-card-terms">
        <dt>Price change</dt><dd>{item.period_text}</dd>
        <dt>Effect on</dt><dd>{item.effect_on}</dd>
      </dl>
      {item.passages && <QuoteFold ids={item.passages} />}
      <p className="co-caption">This is the company's figure for this measure under these conditions. It is not an
        earnings, EBITDA or share-price sensitivity.</p>
    </li>
  );
}

function QuoteFold({ ids }: { ids: string[] }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <>
      <button type="button" className="co-quote-button" aria-expanded={open} aria-controls={id}
              onClick={() => setOpen(!open)}>{open ? "Hide the company's words" : "The company's words"}</button>
      <div id={id} hidden={!open}><QuoteList ids={ids} /></div>
    </>
  );
}

function BagdadCard() {
  const { view } = useCompany();
  const bagdad = view.page.mechanisms.bagdad;
  const news = view.sources.find((source) => source.id === "news-2026-11-04");
  const day = news ? formatDay(news.date) : "";
  return (
    <section className="co-bagdad" aria-labelledby="co-bagdad-title" data-bagdad="">
      <h3 id="co-bagdad-title" className="co-h3">The Bagdad expansion</h3>
      <div className="co-bagdad-part" data-part="decided">
        <p className="co-badge" data-badge="decision">Decision, as stated by the company on {day}</p>
        <Lines blocks={bagdad.decided} tag={false} />
      </div>
      <div className="co-bagdad-part" data-part="estimates">
        <p className="co-badge" data-badge="estimate">Company estimate · stated {day}. Not a result.</p>
        <dl className="co-estimates">{bagdad.estimates.map((item) => (
          <div key={item.record}><dt>{item.label}</dt><dd><Figure id={item.record} /></dd></div>))}</dl>
        <Lines blocks={bagdad.estimate_notes} tag={false} />
      </div>
      <Fold part="bagdad-computed" title="Computed from the company's estimates" teaser="Funding by year and size, as
        this project's arithmetic">
        <dl className="co-estimates">{bagdad.computed.map((item) => (
          <div key={item.record}><dt>{item.label}</dt><dd><Figure id={item.record} /></dd></div>))}</dl>
      </Fold>
      <Fold part="bagdad-changed" title="How the estimate changed" teaser="February, October and November">
        <DataTable table={{ title: "The company's Bagdad statements on four dates", columns: bagdad.change_columns,
          rows: bagdad.change_rows }} />
        <Line block={bagdad.change_note} />
      </Fold>
      <Fold part="bagdad-history" title="The mine"><Lines blocks={bagdad.history} tag={false} /></Fold>
    </section>
  );
}

// ---------------------------------------------------------------- questions and method

function Questions() {
  const { view } = useCompany();
  return (
    <>
      <h2 className="co-h2">Open questions</h2>
      <Stamp />
      {view.page.questions.map((group) => (
        <section key={group.id} aria-labelledby={`co-q-${group.id}`} data-questions={group.id}>
          <h3 id={`co-q-${group.id}`} className="co-h3">{group.title}</h3>
          <Lines blocks={group.items} tag={false} />
        </section>))}
    </>
  );
}

function Method() {
  const { view } = useCompany();
  return (
    <>
      <h2 className="co-h2">Method and sources</h2>
      <ul className="co-sources">{view.sources.map((source) => (
        <li key={source.id} data-source={source.id} data-state={source.state}>
          <p className="co-source-title"><a className="library-external" href={source.url} target="_blank"
                                            rel="noreferrer">{source.title}</a></p>
          <p className="co-source-meta">{source.form} · period to {formatDay(source.period_end)} · {dateLine(source.date,
            source.date_kind)}</p>
          <p className="co-source-state" data-state={source.state}><strong>{source.state === "verified" ? "Verified"
            : source.state === "missing" ? "Missing" : "Changed"}:</strong> {source.detail}</p>
          <Fold part={`source-${source.id}`} title="Details">
            <dl className="co-source-details">
              <dt>Date</dt><dd>{source.date_kind}</dd>
              <dt>Host</dt><dd>{source.host}</dd>
              <dt>Retrieved</dt><dd>{source.retrieved_at}</dd>
              <dt>Size</dt><dd>{source.bytes.toLocaleString("en-US")} bytes</dd>
              <dt>SHA-256</dt><dd><code>{source.sha256}</code></dd>
              <dt>Acquisition</dt><dd>{source.acquisition}</dd>
              <dt>Terms</dt><dd>{source.terms}</dd>
            </dl>
          </Fold>
        </li>))}</ul>
      {view.requests.length > 0 && (
        <p className="co-plain" data-requests="">A request that was refused is kept as a record, not as a source:{" "}
          {view.requests.map((request) => `approval ${request.approval_id}, attempt ${request.n}, HTTP ${
            request.http_status ?? "none"} (${request.outcome})`).join("; ")}.</p>)}
      <h3 className="co-h3">How figures are checked</h3>
      <Lines blocks={view.page.method.checks} tag={false} />
      <h3 className="co-h3">Kinds</h3>
      <dl className="co-kinds">
        {(["published", "estimate", "computed", "withheld"] as BadgeKind[]).map((kind) => (
          <div key={kind}><dt><KindBadge kind={kind} /></dt><dd>{BADGE_TITLE[kind]}</dd></div>))}
        {(["observation", "company_reason", "estimate", "reading"] as const).map((kind) => (
          <div key={kind}><dt><Tag kind={kind} /></dt><dd>{kind === "reading"
            ? "The assistant's interpretation, an AI draft that the owner has not reviewed"
            : kind === "observation" ? "What the documents report" : kind === "company_reason"
              ? "The company's own explanation, with its words behind the Source button"
              : "What the company plans or estimates; not a result"}</dd></div>))}
      </dl>
      <h3 className="co-h3">What this page does not do</h3>
      <Lines blocks={view.page.method.not_doing} tag={false} />
    </>
  );
}

// ---------------------------------------------------------------- the figure detail

function FigureDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const { view, open } = useCompany();
  const record = view.records[id];
  const panel = useRef<HTMLElement | null>(null);
  useEffect(() => { panel.current?.focus(); }, [id]);
  useEffect(() => {
    const key = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [onClose]);
  if (!isFigure(record)) return null;
  const shown = record.state === "available";
  const kind: BadgeKind = shown ? figureKind(record) : "withheld";
  const source = record.kind === "published" ? view.sources.find((item) => item.id === record.source) : undefined;
  return (
    <aside className="co-detail" aria-labelledby="co-detail-title" tabIndex={-1} ref={panel} data-detail={id}>
      <header className="co-detail-head">
        <p className="kicker">Figure detail</p>
        <button type="button" className="co-detail-close" onClick={onClose}>Close</button>
      </header>
      <h2 id="co-detail-title">{record.metric}</h2>
      <p className="co-detail-value">{shown ? figureText(record) : "Not shown"} <KindBadge kind={kind} /></p>
      <dl className="co-detail-list">
        <dt>Kind</dt><dd>{BADGE_TITLE[kind]}</dd>
        <dt>Period</dt><dd>{record.period.label}{record.period.start ? ` (${record.period.start} to ${record.period.end})`
          : ` (to ${record.period.end})`}</dd>
        <dt>Unit</dt><dd>{record.unit}</dd>
        <dt>Basis</dt><dd>{basisWords(record.basis)}</dd>
        {!shown && <><dt>Why it is not shown</dt><dd data-problem="">{record.problem}</dd></>}
        {record.kind === "published" && source && <>
          <dt>Source</dt><dd>{source.title}</dd>
          <dt>Date</dt><dd>{dateLine(source.date, source.date_kind)}</dd>
          <dt>Page</dt><dd>{record.printed_page ?? record.page} (file page {record.page})</dd>
          {record.location && <><dt>Where</dt><dd>{record.location}{shown && record.row ? `; row "${record.row}"` : ""}
            {shown && record.column ? `; column "${record.column}"` : ""}</dd></>}
          {shown && record.quote && <><dt>Quote</dt><dd><blockquote className="co-detail-quote">“{record.quote}”</blockquote></dd></>}
        </>}
        {record.kind === "computed" && <>
          <dt>Formula</dt><dd><code>{record.formula}</code></dd>
          <dt>Inputs</dt><dd><ul className="co-inputs">{Object.entries(record.inputs).map(([name, ref]) => {
            const input = view.records[ref] as FigureRecord | undefined;
            return <li key={name}><code>{name}</code> ={" "}
              <button type="button" className="co-link-button" onClick={() => open(ref, null)}>{input?.metric ?? ref}, {
                input?.period.label}</button>{input && input.state === "available" ? `: ${cellText(input)}` : ""}</li>;
          })}</ul></dd>
          <dt>Rounding</dt><dd>{record.decimals} decimal places, half to even, from exact inputs</dd>
          {shown && record.basis_mix && <><dt>Bases</dt><dd>{record.basis_mix}</dd></>}
          {shown && record.period_mix && <><dt>Periods</dt><dd>{record.period_mix}</dd></>}
          {shown && record.unit_mix && <><dt>Units</dt><dd>{record.unit_mix}</dd></>}
          {(record.assumptions ?? []).map((aid) => {
            const assumption = view.records[aid];
            if (assumption?.kind !== "assumption") return null;
            return <Fragment key={aid}><dt>Assumption</dt><dd className="co-assumption" data-assumption={aid}>{
              assumption.state === "available" && assumption.statement !== null ? assumption.statement
                : <Withheld problem={assumption.problem} />}</dd></Fragment>;
          })}
        </>}
        {shown && record.note && <><dt>Note</dt><dd>{record.note}</dd></>}
        <dt>Record</dt><dd><code>{record.id}</code></dd>
      </dl>
    </aside>
  );
}
