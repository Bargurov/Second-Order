import type { ReactNode } from "react";
import {
  dayText, figureText, type BalanceTable, type Condition, type ElementCheck, type Figure, type Passage,
  type Reason, type Risk, type Statement, type ThesisSource, type ThesisView,
} from "../thesis";
import { comparisonText, editionText, readAsText, withinOneEdition } from "../thesisComparison";
import { totalNames } from "../thesisTotals";

/**
 * The thesis page's sections 2 to 12, except section 8 (ThesisExposure, which uses the parts exported here); ThesisPage
 * holds the header, the contents and the Sources footer. Every element
 * is shown only when the server found it available; otherwise its problems are shown in place of its content, and a
 * withheld title or series (null when it stated a figure, ruling R9) is a neutral placeholder, never invented text.
 * Numbers are shown as served: the page computes nothing.
 */

/** The reply and its sources by id, which every section reads. */
export interface Reading { view: ThesisView; sources: Map<string, ThesisSource> }
export const reading = (view: ThesisView): Reading =>
  ({ view, sources: new Map(view.sources.map((source) => [source.id, source])) });

/** The 12 sections in the spec's order: [key, title]. The header's anchor is "overview". */
export const SECTIONS = [
  ["header", "Overview"],
  ["view", "The view"],
  ["balance", "The balance in numbers"],
  ["differs", "Where this view differs from what others expect"],
  ["reasons", "Reasons"],
  ["risks", "Risks to the thesis"],
  ["conditions", "What would change the view"],
  ["exposure", "Who is exposed"],
  ["log", "View log"],
  ["price", "Price beside the view"],
  ["plain", "Plain-language notes"],
  ["not-claimed", "Not claimed"],
] as const;
type SectionKey = (typeof SECTIONS)[number][0];
export const anchorOf = (key: SectionKey) => (key === "header" ? "overview" : key);
const titleOf = (key: SectionKey) => SECTIONS.find(([name]) => name === key)![1];
/** Each plain note's section. */
const PLAIN_OF = { view: "view", balance: "balance", differs: "differs", reasons: "reasons", risks: "risks",
  conditions: "conditions", exposure: "exposure", log: "log", price: "price" } as const satisfies
  Record<keyof ThesisView["plain"], SectionKey>;
const LOG_KIND = { opened: "Opened", status: "Status", view: "View", confidence: "Confidence", note: "Note" };
const GAP_LABEL = { surplus: "Surplus", deficit: "Deficit", balanced: "Balanced" };
const LETTERS = "abcdefghijklmnopqrstuvwxyz";

/** The name before a label's colon ("Strengthening: the latest figure differs …" -> "Strengthening"). */
export const short = (label: string) => label.split(":")[0];
/** A source as the reader names it: publisher, then edition (as figureText names it), with its title when another
 * listed source has the same publisher and edition (editionText), so the two read apart. */
export const sourceName = (source: ThesisSource, r: Reading) =>
  `${source.publisher} ${editionText(source, r.view.sources)}`;
/** A served change in percent with its sign ("7.4" -> "+7.4%", "-2.0" -> "-2.0%", "0.0" -> "0.0%"). */
const signedPct = (pct: string) => (pct.startsWith("-") || /^0\.0+$/.test(pct) ? `${pct}%` : `+${pct}%`);

export function Placeholder({ what }: { what: string }) {
  return <span className="thesis-placeholder">{what} withheld with this part</span>;
}

export function Section({ id, plain, note, children }: { id: SectionKey; plain?: string; note?: ReactNode;
                                                   children: ReactNode }) {
  const index = SECTIONS.findIndex(([key]) => key === id);
  return (
    <section id={anchorOf(id)} className="library-section-block thesis-section" data-thesis-section={id}
             aria-labelledby={`${anchorOf(id)}-title`}>
      <p className="kicker">{String(index + 1).padStart(2, "0")}</p>
      <h2 id={`${anchorOf(id)}-title`}>{SECTIONS[index][1]}</h2>
      {plain && (
        <p className="thesis-plain">
          <span className="thesis-plain-label">In plain words</span>{" "}
          <span className="thesis-plain-text">{plain}</span>
        </p>
      )}
      {note && <p className="library-section-note">{note}</p>}
      {children}
    </section>
  );
}

/** The problems of a withheld element, each source named by publisher and edition rather than by its id. The server
 * lists the sources not verified first (sorted), then each item not found, in item order (thesis.ts checks this). */
function problemLines(element: ElementCheck, r: Reading): string[] {
  const unread = element.sources.filter((id) => r.sources.get(id)?.state !== "verified").length;
  const itemSource = new Map(element.items.map((item) => [item.id, item.source]));
  return element.problems.map((line, index) => {
    const cut = line.indexOf(": ");
    const named = line.slice(0, cut);
    const source = r.sources.get(index < unread ? named : itemSource.get(named) ?? "");
    return cut > 0 && source ? `${sourceName(source, r)}: ${line.slice(cut + 2)}` : line;
  });
}

export function Withheld({ element, r }: { element: ElementCheck; r: Reading }) {
  const label = r.view.labels.element_states[element.state];
  const cut = label.indexOf(": ");
  return (
    <div className="thesis-withheld" role="note" data-withheld={element.state}>
      <p className="thesis-withheld-kicker">Withheld</p>
      <p className="thesis-withheld-state">
        {cut > 0 ? <><strong>{label.slice(0, cut)}:</strong> {label.slice(cut + 2)}</> : <strong>{label}</strong>}.
        Its content is not shown until its sources check again.
      </p>
      <ul>{problemLines(element, r).map((line, index) => <li key={index}>{line}</li>)}</ul>
    </div>
  );
}

export function FigureLine({ figure, r }: { figure: Figure; r: Reading }) {
  const source = r.sources.get(figure.source)!;
  return (
    <div className="thesis-figure" data-figure={figure.id}>
      <span className="thesis-figure-value">
        {figureText(figure, { publisher: source.publisher, edition: editionText(source, r.view.sources) })}</span>
      <span className="thesis-figure-meta">
        {figure.measure}{figure.scenario && ` · scenario: ${figure.scenario}`}
        {figure.basis && ` · basis: ${figure.basis}`} · {figure.where}
      </span>
      {figure.quote && <blockquote className="thesis-figure-quote">{figure.quote}</blockquote>}
    </div>
  );
}

function PassageLine({ passage, r }: { passage: Passage; r: Reading }) {
  return (
    <figure className="policy-quote thesis-passage" data-passage={passage.id}>
      <blockquote>{passage.quote}</blockquote>
      <figcaption>{sourceName(r.sources.get(passage.source)!, r)} · {passage.where}</figcaption>
    </figure>
  );
}

/** What a statement or a mover cites, in citation order. */
export function Cited({ cites, figures, passages, r }: { cites: string[]; figures: Figure[]; passages: Passage[];
                                                  r: Reading }) {
  const byId = new Map<string, Figure | Passage>([...figures, ...passages].map((item) => [item.id, item]));
  return (
    <ul className="thesis-cited">
      {cites.map((id) => {
        const item = byId.get(id)!;
        return <li key={id}>{"value" in item ? <FigureLine figure={item} r={r} /> : <PassageLine passage={item} r={r} />}</li>;
      })}
    </ul>
  );
}

/** A statement with its status label; what it rests on is listed, or folded away when the element shows its figures
 * elsewhere (a reason's measure, an amount). */
export function StatementBlock({ statement, r, lead = false, fold = false }: { statement: Statement; r: Reading;
                                                                         lead?: boolean; fold?: boolean }) {
  const evidence = <Cited cites={statement.cites} figures={statement.figures} passages={statement.passages} r={r} />;
  return (
    <div className={`thesis-statement${lead ? " is-lead" : ""}`}>
      <p className="thesis-statement-text">
        <span className={`policy-status policy-status-${statement.status}`} data-statement-status={statement.status}>
          {r.view.labels.statuses[statement.status]}
        </span>{" "}
        {statement.text}
      </p>
      {statement.cites.length > 0 && (fold ? (
        <details className="thesis-rests">
          <summary>Rests on {statement.cites.length} cited {statement.cites.length === 1 ? "item" : "items"}</summary>
          {evidence}
        </details>
      ) : (
        <div className="thesis-rests"><p className="thesis-part">Rests on</p>{evidence}</div>
      ))}
    </div>
  );
}

/** A collapsed legend of a status vocabulary, worded as the server labels it. */
function Legend({ labels }: { labels: Record<string, string> }) {
  return (
    <details className="thesis-legend">
      <summary>How the statuses are read</summary>
      <dl>{Object.entries(labels).map(([key, label]) => (
        <div key={key}><dt><span className={`thesis-tag thesis-tag-${key}`}>{short(label)}</span></dt><dd>{label}</dd></div>
      ))}</dl>
    </details>
  );
}

// ---------------------------------------------------------------- 2. the view

export function ViewSection({ r }: { r: Reading }) {
  const element = r.view.view;
  return (
    <Section id="view" plain={r.view.plain.view}>
      <div className="thesis-view-element" data-element="view" data-state={element.state}>
        {element.state === "available" ? <StatementBlock statement={element.statement!} r={r} lead />
          : <Withheld element={element} r={r} />}
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------- 3. the balance

export function BalanceSection({ r }: { r: Reading }) {
  return (
    <Section id="balance" plain={r.view.plain.balance}>
      {r.view.balance.tables.map((table) => <BalanceView key={table.id} table={table} r={r} />)}
    </Section>
  );
}

function BalanceView({ table, r }: { table: BalanceTable; r: Reading }) {
  return (
    <article className="thesis-table" id={`table-${table.id}`} data-table={table.id} data-state={table.state}
             aria-labelledby={`table-${table.id}-title`}>
      <p className="thesis-part">{table.gap === "computed" ? "Gap computed: one publication, basis and scenario"
        : "Side by side: no gap computed"}</p>
      <h3 id={`table-${table.id}-title`}>{table.title ?? <Placeholder what="Title" />}</h3>
      {table.state === "available" ? <BalanceGrid table={table} r={r} /> : <Withheld element={table} r={r} />}
    </article>
  );
}

/** Years across, lines down, as balance tables are read: the published lines, the demand and supply rows (each named by
 * the measure its figures state, thesisTotals) and, when the gap is computed, the gap and weeks of demand. Each figure
 * carries a mark naming its publication, scenario, basis and unit when the table draws on more than one. */
function BalanceGrid({ table, r }: { table: BalanceTable; r: Reading }) {
  const rows = table.rows!;
  const computed = table.gap === "computed";
  const names = totalNames(rows);
  const labels = [...new Set(rows.flatMap((row) => row.lines.map((line) => line.label)))];
  const shown = rows.flatMap((row) => [...row.lines.map((line) => line.figure), row.demand_total, row.supply_total]);
  const keyOf = (figure: Figure) => JSON.stringify([figure.source, figure.scenario, figure.basis, figure.unit]);
  const keys = [...new Set(shown.map(keyOf))];
  const basis = (key: string) => {
    const figure = shown.find((item) => keyOf(item) === key)!;
    return `${sourceName(r.sources.get(figure.source)!, r)}${figure.scenario ? `, scenario ${figure.scenario}` : ""}` +
      `${figure.basis ? `, basis ${figure.basis}` : ""}; ${r.view.labels.units[figure.unit]}`;
  };
  const cell = (figure: Figure | undefined, key: string) => figure === undefined
    ? <td key={key} className="thesis-none">Not given</td>
    : (
      <td key={key} title={`${figure.measure} · ${figure.where}`}>
        {figure.as_shown}
        {keys.length > 1 && <sup className="thesis-mark">{LETTERS[keys.indexOf(keyOf(figure))]}</sup>}
      </td>
    );
  const unique = [...new Map(shown.map((figure) => [figure.id, figure])).values()];
  return (
    <>
      {!computed && <p className="thesis-why-not"><span className="policy-label">No gap computed</span>{table.why_not}</p>}
      <div className="thesis-scroll">
        <table className="thesis-balance">
          <thead>
            <tr>
              <th scope="col"><span className="visually-hidden">Line</span></th>
              {rows.map((row) => (
                <th key={row.year} scope="col" data-year={row.year}>
                  {row.year}<span className="thesis-kind">{row.kind === "projection" ? "Projection" : "Historical"}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {labels.map((label) => (
              <tr key={label}><th scope="row">{label}</th>
                {rows.map((row) => cell(row.lines.find((line) => line.label === label)?.figure, row.year))}</tr>
            ))}
            <tr className="is-total" data-total="demand"><TotalName name={names.demand} side="Demand" />
              {rows.map((row) => cell(row.demand_total, row.year))}</tr>
            <tr className="is-total" data-total="supply"><TotalName name={names.supply} side="Supply" />
              {rows.map((row) => cell(row.supply_total, row.year))}</tr>
            {computed && (
              <>
                <tr className="is-gap"><th scope="row">Surplus or deficit<span>supply less demand</span></th>
                  {rows.map((row) => (
                    <td key={row.year} data-gap-year={row.year}>{row.gap}
                      <span className="thesis-gap-label">{GAP_LABEL[row.label!]}</span></td>
                  ))}</tr>
                <tr className="is-gap"><th scope="row">Weeks of demand<span>the gap, in weeks of that year's demand</span></th>
                  {rows.map((row) => <td key={row.year} data-weeks-year={row.year}>{row.weeks}</td>)}</tr>
              </>
            )}
          </tbody>
        </table>
      </div>
      <ul className="thesis-bases">
        {keys.map((key, index) => (
          <li key={key}>{keys.length > 1 ? <sup className="thesis-mark">{LETTERS[index]}</sup> : "All figures: "}
            {basis(key)}</li>
        ))}
      </ul>
      <details className="thesis-where">
        <summary>Where each of the {unique.length} figures is cited</summary>
        <ul className="thesis-cited">{unique.map((figure) => <li key={figure.id}><FigureLine figure={figure} r={r} /></li>)}</ul>
      </details>
    </>
  );
}

/** A demand or supply row's name: the measure its figures state or, when they share none, only its side. */
function TotalName({ name, side }: { name: string | null; side: string }) {
  return <th scope="row">{name ?? <>{side}<span>no one measure: each figure names its own</span></>}</th>;
}

// ---------------------------------------------------------------- 4. where this view differs

export function DiffersSection({ r }: { r: Reading }) {
  return (
    <Section id="differs" plain={r.view.plain.differs}>
      {r.view.differs.map((entry) => (
        <article key={entry.id} className="thesis-card" id={`differs-${entry.id}`} data-differs={entry.id}
                 data-state={entry.state}>
          {entry.state !== "available" ? <Withheld element={entry} r={r} /> : (
            <>
              <p className="thesis-part">{entry.differs ? "Differs from what others expect"
                : "Does not differ from what others expect"}</p>
              <StatementBlock statement={entry.about!} r={r} fold />
              <div className="thesis-others">
                <p className="thesis-part">What others expect</p>
                <ul className="thesis-cited">{entry.others!.map((other) => (
                  <li key={other.cite}><span className="thesis-other-label">{other.label}</span>
                    {other.figure ? <FigureLine figure={other.figure} r={r} /> : <PassageLine passage={other.passage!} r={r} />}</li>
                ))}</ul>
              </div>
            </>
          )}
        </article>
      ))}
    </Section>
  );
}

// ---------------------------------------------------------------- 5 and 6. reasons and risks

export function ClaimsSection({ r, kind }: { r: Reading; kind: "reason" | "risk" }) {
  const claims: (Reason | Risk)[] = kind === "reason" ? r.view.reasons : r.view.risks;
  const labels = kind === "reason" ? r.view.labels.reason_states : r.view.labels.risk_states;
  return (
    <Section id={kind === "reason" ? "reasons" : "risks"} plain={kind === "reason" ? r.view.plain.reasons : r.view.plain.risks}>
      <Legend labels={labels} />
      <div className="thesis-claims">
        {claims.map((claim) => <ClaimCard key={claim.id} claim={claim} kind={kind} labels={labels} r={r} />)}
      </div>
    </Section>
  );
}

function ClaimCard({ claim, kind, labels, r }: { claim: Reason | Risk; kind: "reason" | "risk";
                                                 labels: Record<string, string>; r: Reading }) {
  const own = kind === "reason" ? { "data-reason": claim.id } : { "data-risk": claim.id };
  return (
    <article className="thesis-card thesis-claim" id={`${kind}-${claim.id}`} {...own} data-state={claim.state}
             aria-labelledby={`${kind}-${claim.id}-title`}>
      <header className="thesis-claim-head">
        <h3 id={`${kind}-${claim.id}-title`}>{claim.title ?? <Placeholder what="Title" />}</h3>
        {claim.state === "available" && (
          <p className="thesis-claim-status">
            <span className={`thesis-tag thesis-tag-${claim.status}`} data-status-of={claim.status}
                  title={labels[claim.status!]}>{short(labels[claim.status!])}</span>
            {claim.change_pct !== null && (
              <span className="thesis-change"><span className="thesis-change-label">change</span> {signedPct(claim.change_pct)}</span>
            )}
          </p>
        )}
      </header>
      <p className="thesis-claim-plain">{claim.plain}</p>
      {claim.state !== "available" ? <Withheld element={claim} r={r} /> : (
        <>
          <StatementBlock statement={claim.statement!} r={r} fold />
          {claim.measure ? <Measure claim={claim} labels={labels} r={r} /> : (
            <p className="thesis-untracked">No retained figure measures this risk, so no status is computed for it.</p>
          )}
        </>
      )}
    </article>
  );
}

/** A measured reason's or risk's two figures, the comparison they make, the exact rule its status is read by (in the
 * reply's own status words, from `labels`) and what moved it last. */
function Measure({ claim, labels, r }: { claim: Reason | Risk; labels: Record<string, string>; r: Reading }) {
  const measure = claim.measure!;
  const moved = claim.moved_by!;
  return (
    <dl className="thesis-measure">
      <div><dt>Latest</dt><dd><FigureLine figure={measure.latest} r={r} /></dd></div>
      <div><dt>Previous</dt><dd><FigureLine figure={measure.previous} r={r} /></dd></div>
      <div><dt>Comparison</dt>
        <dd data-comparison={withinOneEdition(measure) ? "one-edition" : "two-editions"}>
          {comparisonText(measure, r.sources)}</dd></div>
      <div><dt>Read as</dt><dd data-read-as>{readAsText(measure, labels)}</dd></div>
      <div><dt>Moved last by</dt>
        <dd>{moved.publisher} {moved.edition}</dd></div>
    </dl>
  );
}

// ---------------------------------------------------------------- 7. what would change the view

export function ConditionsSection({ r }: { r: Reading }) {
  const labels = r.view.labels.condition_states;
  return (
    <Section id="conditions" plain={r.view.plain.conditions}>
      <Legend labels={labels} />
      <ol className="thesis-claims thesis-conditions">
        {r.view.conditions.map((condition, index) => (
          <li key={condition.id} className="thesis-card" id={`condition-${condition.id}`} data-condition={condition.id}
              data-state={condition.state}>
            <p className="thesis-part">Condition {index + 1}</p>
            {condition.state !== "available" ? <Withheld element={condition} r={r} /> : <ConditionBody
              condition={condition} label={labels[condition.status!]} r={r} />}
          </li>
        ))}
      </ol>
    </Section>
  );
}

function ConditionBody({ condition, label, r }: { condition: Condition; label: string; r: Reading }) {
  const figure = condition.figure!;
  return (
    <>
      <p className="thesis-claim-status">
        <span className={`thesis-tag thesis-tag-${condition.status}`} data-condition-status={condition.status}
              title={label}>{short(label)}</span>
      </p>
      <p className="thesis-condition-text">{condition.text}</p>
      <dl className="thesis-measure">
        <div><dt>Threshold</dt><dd>{condition.comparator === "above" ? "Above" : "Below"} {condition.threshold}{" "}
          {r.view.labels.units[figure.unit]}; a figure equal to it is not past it</dd></div>
        <div><dt>The figure it names</dt><dd><FigureLine figure={figure} r={r} /></dd></div>
      </dl>
    </>
  );
}

// ---------------------------------------------------------------- 9 to 12

export function LogSection({ r }: { r: Reading }) {
  const claim = (id: string): [string, string | null] | null => {
    const reason = r.view.reasons.find((item) => item.id === id);
    if (reason) return [`reason-${id}`, reason.title];
    const risk = r.view.risks.find((item) => item.id === id);
    return risk ? [`risk-${id}`, risk.title] : null;
  };
  return (
    <Section id="log" plain={r.view.plain.log}
             note="Dated entries, oldest first. A later version adds entries; it never rewrites earlier ones.">
      <ol className="thesis-log">
        {r.view.log.map((entry, index) => (
          <li key={index} data-kind={entry.kind}>
            <p className="thesis-log-day">{dayText(entry.date)}</p>
            <div>
              <p className="thesis-log-kind">{LOG_KIND[entry.kind]}</p>
              <p className="thesis-log-text">{entry.text}</p>
              {entry.refs.length > 0 && (
                <p className="thesis-log-refs">About{" "}
                  {entry.refs.map((ref, i) => {
                    const [anchor, title] = claim(ref) ?? [null, null];
                    return <span key={ref}>{i > 0 && " · "}{anchor ? <a href={`#${anchor}`}>
                      {title ?? <Placeholder what="Title" />}</a> : ref}</span>;
                  })}
                </p>
              )}
            </div>
          </li>
        ))}
      </ol>
    </Section>
  );
}

export function PriceSection({ r }: { r: Reading }) {
  const record = r.view.price_record;
  return (
    <Section id="price" plain={r.view.plain.price}>
      <p className="thesis-record-note" role="note">A record, not evidence that the view is right</p>
      <div className="thesis-card" data-price={record.id} data-state={record.state}>
        <h3>{record.series ?? <Placeholder what="The series name" />}</h3>
        {record.state !== "available" ? <Withheld element={record} r={r} /> : (
          <dl className="thesis-measure">
            <div><dt>Latest retained when the thesis opened</dt>
              <dd><FigureLine figure={record.opening!} r={r} /></dd></div>
            <div><dt>Latest retained</dt><dd><FigureLine figure={record.latest!} r={r} /></dd></div>
          </dl>
        )}
      </div>
      <p className="library-section-note">
        The opening and latest figures are shown side by side; no score or verdict is drawn from them.
      </p>
    </Section>
  );
}

export function PlainSection({ r }: { r: Reading }) {
  const plain = r.view.plain;
  return (
    <Section id="plain" note="The one-line notes shown under each heading, gathered here to read on their own.">
      <dl className="thesis-glossary">
        {(Object.keys(PLAIN_OF) as (keyof typeof PLAIN_OF)[]).map((key) => (
          <div key={key}><dt>{titleOf(PLAIN_OF[key])}</dt><dd>{plain[key]}</dd></div>
        ))}
        {r.view.reasons.map((reason) => (
          <div key={`reason-${reason.id}`}><dt>Reason · {reason.title ?? <Placeholder what="Title" />}</dt>
            <dd>{reason.plain}</dd></div>
        ))}
        {r.view.risks.map((risk) => (
          <div key={`risk-${risk.id}`}><dt>Risk · {risk.title ?? <Placeholder what="Title" />}</dt>
            <dd>{risk.plain}</dd></div>
        ))}
      </dl>
    </Section>
  );
}

export function NotClaimedSection({ r }: { r: Reading }) {
  return (
    <Section id="not-claimed" note="Deliberately not claimed anywhere on this page:">
      <ul className="library-points">{r.view.not_claimed.map((claim) => <li key={claim}>{claim}</li>)}</ul>
    </Section>
  );
}
