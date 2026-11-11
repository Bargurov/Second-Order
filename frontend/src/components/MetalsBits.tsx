import { useId, useState, type ReactNode } from "react";
import type { Chapter, Series, Top } from "../metals";
import { shortReason, type ReasonKind } from "../metalsWords";
import type { Picked } from "./MetalsCompare";

/** Text from a field the reader types but does not check: a string as it is, anything else as nothing. */
export const str = (value: unknown): string => (typeof value === "string" ? value : "");
/** The strings of a list the reader does not check; anything that is not a list is an empty one. */
export const strings = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item !== "") : [];
export const items = <T,>(value: unknown): T[] => (Array.isArray(value) ? (value as T[]) : []);

/** The chapter's 2025 Production series, in the file's order. */
export const production2025 = (chapter: Chapter): Series[] =>
  items<Series>(chapter.series).filter((series) => series.statistic === "Production" && series.year === "2025");

/** A picked metal's name in an overview table: it opens the metal under "By metal". */
export function MetalName({ pick, onOpen }: { pick: Picked; onOpen: (id: string) => void }) {
  return (
    <a className="mt-metal-link" href={`#by-metal:${pick.id}`} data-open-metal={pick.id}
       onClick={(event) => { event.preventDefault(); onOpen(pick.id); }}>{pick.name}</a>
  );
}

/** Why a value is not shown, in words. It never carries the value itself. */
export function Reason({ children }: { children: ReactNode }) {
  return <span className="mt-withheld" data-withheld="">{children}</span>;
}

/**
 * A figure that is not shown: a short label, and a button that opens the full reason in place (the server's words, or
 * the page's own). When the label would be the reason itself, the reason is shown as it is, with no button.
 */
export function Why({ reason, kind = "rank", label, context }: {
  reason: string | null | undefined; kind?: ReasonKind; label?: string; context?: string;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const text = str(reason) || "Not shown";
  const short = label ?? shortReason(text, kind);
  if (short === text) return <Reason>{text}</Reason>;
  return (
    <span className={`mt-why${short === "Unit in doubt" ? " mt-why-unit" : ""}`} data-why="">
      <span className="mt-why-label" data-withheld="">{short}</span>
      <button type="button" className="mt-why-button" aria-expanded={open} aria-controls={id}
              aria-label={`Why? ${short}${context ? `, ${context}` : ""}`} onClick={() => setOpen(!open)}>Why?</button>
      <span id={id} className="mt-why-text" data-why-text="" hidden={!open}>{text}</span>
    </span>
  );
}

/** A short note beside a figure, opened by a small button (the years caveat beside each years figure). */
export function Aside({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span className="mt-aside" data-aside="">
      <button type="button" className="mt-aside-button" aria-expanded={open} aria-controls={id} aria-label={label}
              title={label} onClick={() => setOpen(!open)}><span aria-hidden="true">i</span></button>
      <span id={id} className="mt-aside-text" hidden={!open}>{children}</span>
    </span>
  );
}

/** A share as the server shows it ("74.2" becomes "74.2%"), or its short reason. */
export function Share({ shown, reason }: { shown: string | null | undefined; reason: string | null | undefined }) {
  if (typeof shown === "string") return <span className="mt-share">{shown}%</span>;
  return <Why reason={reason} kind="share" />;
}

/** The largest named country of a ranking with its share, or why the ranking is withheld. */
export function Leader({ top, context }: { top: Top; context?: string }) {
  if (top.shown === null) return <Why reason={top.reason} kind="rank" context={context} />;
  const first = str(items<string>(top.countries)[0]);
  return <><span className="mt-country">{first}</span> <Share shown={top.shown} reason={null} /></>;
}

/** The combined share of the three largest named countries, with their names, or why it is withheld. */
export function TopThree({ top, context }: { top: Top; context?: string }) {
  if (top.shown === null) return <Why reason={top.reason} kind="rank" context={context} />;
  return <><Share shown={top.shown} reason={null} /><span className="mt-sub">{strings(top.countries).join(", ")}</span></>;
}

/** Why a value is not shown: a short label and the specific reason beside it. The label says "Not in the retained
 * sources" where the data is absent, and "Not shown" where the source holds it but it cannot be ranked or compared. */
export function Missing({ children, label = "Not in the retained sources" }: {
  children: ReactNode; label?: "Not in the retained sources" | "Not shown";
}) {
  return <span className="mt-missing" data-missing=""><span className="mt-missing-label">{label}</span>
    <span className="mt-sub">{children}</span></span>;
}

/** Whether the IEA projects a year (every year after 2025). */
export const projected = (year: string) => year > "2025";
/** An IEA percentage as shown ("28.8" becomes "28.8%"), or a dash when the sheet gives none. */
export const percentOf = (value: unknown) => (typeof value === "string" ? `${value}%` : "—");

/** A column heading for a year, marked when the IEA projects it. */
export function YearHead({ year, extra }: { year: string; extra?: string }) {
  return (
    <th scope="col" className="mt-num" data-year={year}>
      {year}{projected(year) && <span className="mt-proj">IEA projection</span>}
      {extra && <span className="mt-sub">{extra}</span>}
    </th>
  );
}

/** One value of an IEA year: data-projection marks every cell of a year after 2025. */
export function YearCell({ year, rowSpan, children }: { year: string; rowSpan?: number; children: ReactNode }) {
  return <td className="mt-num" data-year={year} data-projection={projected(year) ? "" : undefined}
             rowSpan={rowSpan}>{children}</td>;
}

/** A wide table, scrolling inside its own frame so the page never scrolls sideways. Its name is a frame's words, and
 * `year`, the year a control picked (an IEA year: the page's own label), ends it, marked so a check can tell it apart. */
export function Scroll({ label, year, children }: { label: string; year?: string; children: ReactNode }) {
  return <div className="mt-table-wrap" role="region" aria-label={year === undefined ? label : `${label}, ${year}`}
              data-label-year={year} tabIndex={0}>{children}</div>;
}

/** One part of a metal, closed until opened: its title, an optional flag, and a short line on what it holds. */
export function Fold({ part, title, flag, teaser, children }: {
  part: string; title: string; flag?: string | null; teaser?: string; children: ReactNode;
}) {
  return (
    <details className="mt-fold" data-part={part}>
      <summary>
        <span className="mt-fold-title">{title}</span>
        {flag && <span className="mt-flag" data-flag="">{flag}</span>}
        {teaser && <span className="mt-fold-teaser">{teaser}</span>}
      </summary>
      <div className="mt-fold-body">{children}</div>
    </details>
  );
}

/** Tabs (one of them selected): arrow keys, Home and End move between them and select, as the ARIA tabs pattern. */
export function TabList<T extends string>({ label, tabs, active, onSelect, idFor, panelFor, className }: {
  label: string; tabs: readonly { id: T; label: ReactNode }[]; active: T; onSelect: (id: T) => void;
  idFor: (id: T) => string; panelFor: (id: T) => string; className: string;
}) {
  const move = (key: string) => {
    const at = tabs.findIndex((tab) => tab.id === active), last = tabs.length - 1;
    const next = key === "ArrowRight" ? (at >= last ? 0 : at + 1) : key === "ArrowLeft" ? (at <= 0 ? last : at - 1)
      : key === "Home" ? 0 : key === "End" ? last : -1;
    if (next < 0) return false;
    onSelect(tabs[next].id);
    document.getElementById(idFor(tabs[next].id))?.focus();
    return true;
  };
  return (
    <div role="tablist" aria-label={label} className={className}
         onKeyDown={(event) => { if (move(event.key)) event.preventDefault(); }}>
      {tabs.map((tab) => (
        <button key={tab.id} type="button" role="tab" id={idFor(tab.id)} data-tab={tab.id}
                aria-selected={tab.id === active} aria-controls={panelFor(tab.id)} tabIndex={tab.id === active ? 0 : -1}
                onClick={() => onSelect(tab.id)}>{tab.label}</button>))}
    </div>
  );
}
