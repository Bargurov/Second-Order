import type { ReactNode } from "react";
import { statementDate, type Computed, type CopperToolsView, type Published } from "../copperTools";

/** What kind of number is shown: a figure from a retained source, a user's assumption, or a value fixed code computed. */
export function Kind({ kind, title }: { kind: "published" | "assumption" | "computed" | "missing"; title: string }) {
  const letter = { published: "P", assumption: "A", computed: "C", missing: "M" }[kind];
  return <span className="ct-kind" data-kind={kind} title={title} aria-label={title}>{letter}</span>;
}

/** A published figure by its id: its value as printed, or why it is withheld. */
export function FigureValue({ view, id, unit = true }: { view: CopperToolsView; id: string | null; unit?: boolean }) {
  if (id === null) return <span className="ct-missing">Not stated<Kind kind="missing" title="Missing: not stated in a retained source" /></span>;
  const figure = view.figures[id];
  if (figure.as_shown === null) {
    return <span className="ct-withheld" data-withheld={id}>Withheld<Kind kind="missing"
      title={`Not verified: ${view.labels.item_states[figure.state]}`} /></span>;
  }
  return (
    <span className="ct-value" data-figure={id}>
      {figure.as_shown}{unit && <span className="ct-unit"> {unitText(view, figure.unit, figure.as_shown)}</span>}
      <Kind kind="published" title={`Published · ${figure.measure} · ${figure.where}`} />
    </span>
  );
}

/** A figure of Bagdad's later statement, from the verified FCX records: "≈" where the company said approximately,
 * the printed figure, and a badge naming the document, its date and page; or why it is withheld. */
export function LinkedValue({ view, id }: { view: CopperToolsView; id: string }) {
  const entry = view.linked.records[id];
  if (entry.display === null) {
    return <span className="ct-withheld" data-linked={id}>Withheld<Kind kind="missing"
      title={entry.problem ?? "Withheld"} /></span>;
  }
  const shown = entry.unit?.startsWith("usd_") ? `$${entry.display}` : entry.display;
  const source = view.linked.sources[entry.source];
  const title = `Company estimate · ${source?.form ?? "document"}, ${statementDate(source?.date ?? null)}, p. ${entry.page}`;
  return (
    <span className="ct-value" data-linked={id}>
      {entry.approximate && "≈ "}{shown}<span className="ct-unit"> {unitText(view, entry.unit ?? "", shown)}</span>
      <Kind kind="published" title={title} />
    </span>
  );
}

/** A passage of Bagdad's later statement, quoted, with its document and page; or why it is withheld. */
export function LinkedQuote({ view, id }: { view: CopperToolsView; id: string }) {
  const entry = view.linked.records[id];
  if (entry.quote === null) return <span className="ct-withheld" data-linked={id}>Withheld: not verified</span>;
  const source = view.linked.sources[entry.source];
  return <span data-linked={id}><q>{entry.quote}</q>{" "}
    <span className="ct-cite">({source?.form ?? "document"}, p. {entry.page})</span></span>;
}

export function PublishedValue({ view, entry }: { view: CopperToolsView; entry: Published }) {
  return <FigureValue view={view} id={entry.figure} unit={false} />;
}

/** A computed value as the server shows it, with its equation; "≈" when the shown text is rounded for display. */
export function ComputedValue({ item, unit, view, signed = false }: { item: Computed | null | undefined; unit?: string;
  view?: CopperToolsView; signed?: boolean }) {
  if (!item) return <span className="ct-missing">—</span>;
  if (item.shown === null) {
    return <span className="ct-withheld">Withheld<Kind kind="missing"
      title={`Withheld: it uses ${item.withheld.length} figure(s) that are not verified`} /></span>;
  }
  const text = signed && !item.shown.startsWith("-") && item.shown !== "0" ? `+${item.shown}` : item.shown;
  return (
    <span className="ct-value" data-equation={item.equation}>
      {item.rounded ? "≈ " : ""}{text}{unit && view && <span className="ct-unit"> {unitText(view, unit)}</span>}
      {unit === "percent" && "%"}
      <Kind kind="computed" title={`Computed · ${item.equation}${item.rounded ? " · rounded for display; the exact value is kept" : ""}`} />
    </span>
  );
}

/** A unit as a reader says it after the printed figure; a figure printed with "$" is not given "dollars" again. */
export function unitText(view: CopperToolsView, unit: string, shown = ""): string {
  const dollars = shown.startsWith("$");
  if (unit === "percent") return "";
  if (unit === "kt") return "kt";
  if (unit === "usd_per_lb") return dollars ? "per lb" : "$/lb";
  if (dollars && unit === "usd_billion") return "billion";
  if (dollars && unit === "usd_million") return "million";
  return view.labels.units[unit] ?? unit;
}

export function Plain({ children }: { children: ReactNode }) {
  return <p className="ct-plain">{children}</p>;
}

export function SectionHead({ id, kicker, title, children }: { id: string; kicker: string; title: string;
  children?: ReactNode }) {
  return (
    <header className="ct-section-head">
      <p className="kicker">{kicker}</p>
      <h2 id={`${id}-title`}>{title}</h2>
      {children}
    </header>
  );
}
