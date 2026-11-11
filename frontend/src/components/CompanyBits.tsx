import { createContext, useContext, useId, useState, type ReactNode } from "react";
import {
  basisWords, cellText, figureKind, figureText, isFigure, unitWords, type Block, type BlockKind, type CompanyView,
  type FigureRecord, type Passage, type Row, type Table,
} from "../companyResearch";
import { formatDay } from "../format";
import { authorship } from "../fuelsNote";

/** The reply, the figure-detail opener and a fresh read of the page (after a document changed), for every part. */
export interface CompanyContextValue {
  view: CompanyView; open: (id: string, from: HTMLElement | null) => void; reload: () => void;
}
export const CompanyContext = createContext<CompanyContextValue | null>(null);
export function useCompany(): CompanyContextValue {
  const value = useContext(CompanyContext);
  if (value === null) throw new Error("CompanyContext is missing");
  return value;
}

export type BadgeKind = "published" | "estimate" | "computed" | "assumption" | "withheld";
const LETTER: Record<BadgeKind, string> = { published: "P", estimate: "F", computed: "C", assumption: "A", withheld: "M" };
export const BADGE_TITLE: Record<BadgeKind, string> = {
  published: "Reported: quoted from a retained company document",
  estimate: "Company estimate or outlook, not a result",
  computed: "Computed by this project from the records shown; not a company figure",
  assumption: "An assumption of this project",
  withheld: "Not shown: it rests on a source that is not verified",
};

/** What kind of number is shown (the copper tools' badge, with F for a company estimate). */
export function KindBadge({ kind }: { kind: BadgeKind }) {
  return <span className="ct-kind co-kind" data-kind={kind === "withheld" ? "missing" : kind} title={BADGE_TITLE[kind]}
               aria-hidden="true">{LETTER[kind]}</span>;
}

/** Who wrote the page's own texts, and whether the owner has reviewed them ("AI-drafted, not reviewed by the owner"). */
export function Stamp() {
  const { view } = useCompany();
  return <p className="co-stamp" data-review={view.page.review.state}>{authorship(view.page.review.author,
    view.page.review.state === "reviewed" ? view.page.review : null)}</p>;
}

/** The short name of a source, for passages and the figure detail. */
export const SOURCE_SHORT: Record<string, string> = {
  "10k-2025": "Form 10-K for 2025", "10q-2026q3": "Form 10-Q, third quarter 2026",
  "release-2026q3": "Results release, 27 Oct 2026", "news-2026-11-04": "Bagdad release, 4 Nov 2026",
};

/** A figure from its record: a button that opens the figure detail, or "Withheld" (its detail says why). */
export function Figure({ id, mode = null, tone = "prose" }: {
  id: string; mode?: "signed" | "size" | null; tone?: "prose" | "cell" | "tile";
}) {
  const { view, open } = useCompany();
  const record = view.records[id];
  if (!isFigure(record)) return null;
  const shown = record.state === "available";
  const text = !shown ? "Withheld" : tone === "prose" ? figureText(record, mode) : cellText(record, mode === "signed");
  const kind: BadgeKind = shown ? figureKind(record) : "withheld";
  return (
    <button type="button" className={`co-fig co-fig-${tone}`} data-figure={id} data-state={record.state}
            aria-label={`${text}: ${record.metric}, ${record.period.label}. ${BADGE_TITLE[kind]}. Open the detail`}
            onClick={(event) => open(id, event.currentTarget)}>
      <span className="co-fig-text">{text}</span><KindBadge kind={kind} />
    </button>
  );
}

/** Why something is not shown, in the server's fixed words; never a value. */
export function Withheld({ problem }: { problem: string | null }) {
  return <span className="co-withheld" data-withheld=""><KindBadge kind="withheld" />{" "}
    {problem ?? "Not shown: it rests on a source that is not verified on this machine."}</span>;
}

/** A text block's words and figures, inline; a withheld block shows only why. */
export function Words({ block }: { block: Block }) {
  if (block.state !== "available" || block.segments === null) return <Withheld problem={block.problem} />;
  return <>{block.segments.map((part, at) => "ref" in part
    ? <Figure key={at} id={part.ref} mode={part.mode} />
    : <span key={at}>{part.text}</span>)}</>;
}

export const TAG: Record<BlockKind, string> = {
  observation: "Reported", computed: "Computed", estimate: "Company estimate", company_reason: "Company's reason",
  reading: "AI reading, not reviewed", note: "Note",
};

/** What kind of statement a line is: reported, the company's reason or estimate, computed, or an AI reading. */
export function Tag({ kind }: { kind: BlockKind }) {
  return <span className="co-tag" data-tag={kind}>{TAG[kind]}</span>;
}

/** A passage as quoted: the company's words, with its source and printed page. */
export function Quote({ passage }: { passage: Passage }) {
  const { view } = useCompany();
  const source = view.sources.find((item) => item.id === passage.source);
  if (passage.state !== "available" || passage.quote === null) return <Withheld problem={passage.problem} />;
  return (
    <figure className="co-quote" data-passage={passage.id}>
      <blockquote>“{passage.quote}”</blockquote>
      <figcaption>{SOURCE_SHORT[passage.source] ?? source?.title}, page {passage.printed_page ?? passage.page}</figcaption>
    </figure>
  );
}

/** One statement: its tag, its words, and the company's words behind it, opened on request. */
export function Line({ block, tag = true, as = "div" }: { block: Block; tag?: boolean; as?: "div" | "li" }) {
  const { view } = useCompany();
  const [open, setOpen] = useState(false);
  const id = useId();
  const quotes = block.state === "available" ? block.passages : [];
  const Element = as;
  return (
    <Element className="co-line" data-kind={block.kind} data-state={block.state}>
      <p>
        {tag && <><Tag kind={block.kind} />{" "}</>}<Words block={block} />
        {quotes.length > 0 && <>{" "}<button type="button" className="co-quote-button" aria-expanded={open}
          aria-controls={id} onClick={() => setOpen(!open)}>{open ? "Hide the source" : "Source"}</button></>}
      </p>
      {quotes.length > 0 && <div id={id} className="co-quotes" hidden={!open}>
        {quotes.map((pid) => <Quote key={pid} passage={view.passages[pid]} />)}</div>}
    </Element>
  );
}

export function Lines({ blocks, tag = true }: { blocks: Block[]; tag?: boolean }) {
  return <ul className="co-lines">{blocks.map((block, at) => <Line key={at} block={block} tag={tag} as="li" />)}</ul>;
}

/** A part closed until opened: the metals page's fold. */
export function Fold({ part, title, teaser, open, onToggle, children }: {
  part: string; title: string; teaser?: string; open?: boolean; onToggle?: (open: boolean) => void; children: ReactNode;
}) {
  return (
    <details className="mt-fold co-fold" data-part={part} open={open}
             onToggle={(event) => onToggle?.((event.currentTarget as HTMLDetailsElement).open)}>
      <summary>
        <span className="mt-fold-title">{title}</span>
        {teaser && <span className="mt-fold-teaser">{teaser}</span>}
      </summary>
      <div className="mt-fold-body">{children}</div>
    </details>
  );
}

/** A wide table, scrolling inside its own frame so the page never scrolls sideways. */
export function Scroll({ label, children }: { label: string; children: ReactNode }) {
  return <div className="mt-table-wrap co-table-wrap" role="region" aria-label={label} tabIndex={0}>{children}</div>;
}

const firstFigure = (view: CompanyView, row: Row): FigureRecord | null => {
  for (const id of row.ids) {
    const record = id ? view.records[id] : undefined;
    if (isFigure(record)) return record;
  }
  return null;
};

/** A table of records: each row one basis and one unit (the change column carries its own), each cell a figure. */
export function DataTable({ table, change = false }: { table: Table; change?: boolean }) {
  const { view } = useCompany();
  const valueColumns = change ? table.columns.length - 1 : table.columns.length;
  return (
    <Scroll label={table.title}>
      <table className="mt-table co-table">
        <caption>{table.title}</caption>
        <thead>
          <tr>
            <th scope="col">Line</th>
            {table.columns.map((column) => <th key={column} scope="col" className="mt-num">{column}</th>)}
            <th scope="col">Unit and basis</th>
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row) => {
            const first = firstFigure(view, row);
            return [
              <tr key={row.label} data-row={row.label}>
                <th scope="row">{row.label}</th>
                {row.ids.map((id, at) => (
                  <td key={at} className="mt-num">{id ? <Figure id={id} tone="cell" mode={at >= valueColumns ? "signed"
                    : null} /> : <span className="co-dash" aria-label="not given">—</span>}</td>))}
                <td className="co-unit-cell">{first ? `${unitWords(first.unit)} · ${basisWords(first.basis)}` : ""}</td>
              </tr>,
              row.note ? (
                <tr key={`${row.label}-note`} className="co-row-note" data-note={row.label}>
                  <td colSpan={row.ids.length + 2}><Words block={row.note} /></td>
                </tr>) : null,
            ];
          })}
        </tbody>
      </table>
    </Scroll>
  );
}

/** The day a source is dated, with what kind of date it is, in words. */
export function dateLine(date: string, kind: string): string {
  const what = kind.startsWith("signature date") ? "signature date" : kind.startsWith("dateline") ? "dateline"
    : "date";
  return `${formatDay(date)} (${what})`;
}
