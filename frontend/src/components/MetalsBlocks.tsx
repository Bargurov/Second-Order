import type { ReactNode } from "react";
import { ABOUT } from "../metalsNotes";
import { coverageText, hhiText, passagePlace, relianceOneOf, relianceText } from "../metalsSections";
import type { CitedPassage, Indicators, RiskChapter } from "../metalsStage2";
import { Aside, Reason, Why } from "./MetalsBits";

export const USGS_LABEL = "USGS · Mineral Commodity Summaries 2026";
export const IEA_LABEL = "IEA · Critical Minerals Dataset 2026";
export const QUOTED_LABEL = "Quoted from retained sources";
/** What the quoted blocks say of themselves: who chose the passages, and that each quote is checked on this read. */
export const QUOTED_NOTE = "Passages chosen by the assistant; each quote is checked against its retained source on this "
  + "read, and withheld when it cannot be.";
/** The events block's own words: past events from dated reports, not a news feed. */
export const EVENTS_NOTE = `${QUOTED_NOTE} Each event is a past one, dated as its source dates it, from the report named `
  + "under it; this is not a news feed.";

/**
 * One source's block inside a research section: named by its source in a small label and set apart by a rule, so a
 * USGS block, an IEA block and a block of quoted passages never read as one table.
 */
export function SourceBlock({ source, label, note, children }: {
  source: "usgs" | "iea" | "quoted"; label: string; note?: ReactNode; children: ReactNode;
}) {
  return (
    <div className={`mt-src mt-src-${source}`} data-block={source}>
      <p className="mt-src-label">{label}</p>
      {note && <p className="mt-src-note">{note}</p>}
      {children}
    </div>
  );
}

/** A withheld part inside a block: its problem, once, and no value. */
export function Withheld({ problem }: { problem: string }) {
  return <p className="mt-src-withheld" data-withheld-part=""><Reason>Withheld: {problem}</Reason></p>;
}

/** A heading's "About" note for an indicator: its formula, source, year and limit, one click away. */
export function About({ name, which }: { name: string; which: keyof typeof ABOUT }) {
  return <span className="mt-about"><Aside label={`About ${name}`}>{ABOUT[which]}</Aside></span>;
}

/** An HHI with both bounds and the named countries' coverage beside it, or why it is not shown. */
export function Hhi({ item, context, prefix = false }: { item: Indicators; context?: string; prefix?: boolean }) {
  if (item.hhi_low === null || item.hhi_high === null || item.named_share === null) {
    return <Why reason={item.reason} kind="rank" context={context} />;
  }
  return (
    <span className="mt-hhi" data-hhi="">
      <span className="mt-share">{prefix ? "HHI " : ""}{hhiText(item.hhi_low, item.hhi_high)}</span>
      <span className="mt-sub">{coverageText(item.named_share, item.over_total)}</span>
    </span>
  );
}

/** A passage quoted from a retained source with its source named (title, publisher, edition) and its place, or why its
 * quote is withheld: behind "Why?", or in place (`reason`) where the reason is what a list is for. An event gives its
 * kind and `when`, the date its verified quote gives, in its caption. */
export function Passage({ cited, kind, when, reason = false }: {
  cited: CitedPassage; kind?: string; when?: string; reason?: boolean;
}) {
  const { evidence } = cited;
  const place = passagePlace(evidence);
  if (evidence.state === "verified" && evidence.quote !== null) {
    return (
      <figure className="mt-quote" data-passage={evidence.id} data-state="verified">
        {kind && <figcaption className="mt-quote-kind">{kind}{when && <>{" "}<span className="mt-dot" aria-hidden="true">·</span>{" "}
          <span className="mt-quote-when" data-when="">{when}</span></>}</figcaption>}
        <blockquote><p>{evidence.quote}</p></blockquote>
        <p className="mt-quote-source">{place}</p>
      </figure>
    );
  }
  return (
    <div className="mt-quote is-withheld" data-passage={evidence.id} data-state={evidence.state}>
      {kind && <p className="mt-quote-kind">{kind}</p>}
      {reason ? <Reason>Quote withheld: {evidence.problem}</Reason>
        : <Why reason={evidence.problem} label="Quote withheld" context={kind ?? evidence.id} />}
      {place !== null && <p className="mt-quote-source">{place}</p>}
    </div>
  );
}

/**
 * US net import reliance for 2025 as printed: the chapter's first 2025 row (ruling R10). Where the chapter prints more
 * than one 2025 figure (`count`), it is named by its commodity as printed and says it is one of them; `basis` (its
 * printed detail, or null to leave it out) and `about` stand beside it.
 */
export function RelianceFigure({ reliance, count, basis, about }: {
  reliance: NonNullable<RiskChapter["us"]["reliance"]>; count: number; basis: string | null; about?: ReactNode;
}) {
  return (
    <span className="mt-reliance" data-reliance="">
      {count > 1 && <><span className="mt-country" data-commodity="">{reliance.commodity}</span>{" "}</>}
      <span className="mt-printed">{relianceText(reliance.value)}</span>{about}
      {basis !== null && <span className="mt-sub">{basis}</span>}
      {count > 1 && <span className="mt-sub" data-one-of="">{relianceOneOf(count)}</span>}
    </span>
  );
}

/** A list of quoted passages, or the words for none. */
export function Passages({ list, none }: { list: CitedPassage[]; none: string }) {
  if (list.length === 0) return <p className="mt-none">{none}</p>;
  return <div className="mt-quotes">{list.map((cited) => <Passage key={cited.passage} cited={cited} />)}</div>;
}
