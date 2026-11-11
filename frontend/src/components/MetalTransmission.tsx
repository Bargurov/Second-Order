import type { Chapter } from "../metals";
import { coverageText, LINK_LABELS, linkCounts, linkIndicators, type MetalParts } from "../metalsSections";
import type { Chain, Link as ChainLink, RiskChapter } from "../metalsStage2";
import { Link } from "../router";
import { Passage, Withheld } from "./MetalsBlocks";
import { Fold, Why } from "./MetalsBits";
import type { Picked } from "./MetalsCompare";

const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
/** Said once per chain, above the lists that follow its links. */
export const READING = "Who is exposed, who may gain or lose and what could soften it: not measured, and not stated by "
  + "a retained source.";

/**
 * Economic transmission: the assistant-written chains for this metal under the fixed written-by sentence. Each link is
 * labelled measured (a figure on this page, or why it is not shown), stated by a source (the quote with its source and
 * place, or why it is withheld) or a hypothesis; then who is directly and indirectly exposed, who may gain or lose and
 * through which mechanism, what could soften the effect, and what the data shows against what is assumed. A measured
 * HHI keeps the named countries' coverage beside its range, from the series its ref names.
 */
export function Transmission({ pick, parts }: { pick: Picked; parts: MetalParts }) {
  const { research } = parts;
  const note = research.shown ? research.value : null;
  const chains = note?.chains ?? [];
  const usgs = parts.risk.shown && pick.chapter !== null ? { chapter: pick.chapter, risk: parts.risk.value } : null;
  const teaser = !research.shown ? "notes withheld" : chains.length === 0 ? "no chain written"
    : `${count(chains.length, "chain", "chains")} · assistant-written`;
  return (
    <Fold part="transmission" title="Economic transmission" teaser={teaser}>
      <p className="mt-written" data-written-by="">{parts.writtenBy}</p>
      {!research.shown ? <Withheld problem={research.problem} />
        : chains.length === 0 ? <p className="mt-none">No transmission chain is written for this metal.</p>
          : chains.map((chain) => <ChainView key={chain.id} chain={chain} metal={pick.id} usgs={usgs} />)}
      {note?.thesis === "copper" && (
        <p className="mt-thesis-link" data-thesis-link="">Company exposure, from the firms' own filings, is on{" "}
          <Link to="/theses/copper">the copper thesis</Link>, in its exposure section.</p>)}
      {note?.thesis === "copper" && (
        <p className="mt-thesis-link" data-events-link="">Past events that bear on the copper thesis are on{" "}
          <Link to="/theses/copper/events">the copper event chains</Link>.</p>)}
    </Fold>
  );
}

type Usgs = { chapter: Chapter; risk: RiskChapter } | null;

function ChainView({ chain, metal, usgs }: { chain: Chain; metal: string; usgs: Usgs }) {
  const counts = linkCounts(chain.links);
  const id = `mt-${metal}-chain-${chain.id}`;
  return (
    <article className="mt-chain" data-chain={chain.id} aria-labelledby={id}>
      <h4 id={id} className="mt-chain-title">{chain.title}</h4>
      <p className="mt-chain-start"><span className="mt-chain-key">Starting point, assumed</span>{chain.disruption}</p>
      <p className="mt-chain-count">{count(chain.links.length, "link", "links")}: {counts.measured} measured,{" "}
        {counts.stated} stated by a source{counts.withheld > 0
          && `, ${count(counts.withheld, "quote", "quotes")} withheld on this read`},{" "}
        {count(counts.hypothesis, "hypothesis", "hypotheses")}</p>
      <ol className="mt-links">{chain.links.map((link, at) => <LinkView key={at} link={link} usgs={usgs} />)}</ol>
      <p className="mt-chain-reading" data-reading=""><span className="mt-chain-key">The assistant's reading</span>{READING}</p>
      <div className="mt-chain-grid">
        <div>
          <h5>Directly exposed</h5>
          <ul className="mt-list mt-list-tight">{chain.direct.map((item, at) => <li key={at}>{item}</li>)}</ul>
        </div>
        <div>
          <h5>Indirectly exposed</h5>
          <ul className="mt-list mt-list-tight">{chain.indirect.map((item, at) => <li key={at}>{item}</li>)}</ul>
        </div>
      </div>
      <h5>Who may gain or lose, and through what</h5>
      <ul className="mt-gains">{chain.gains_losses.map((item, at) => (
        <li key={at} data-direction={item.direction}>
          <span className={`mt-dir${item.direction === "may gain" ? " is-gain" : " is-loss"}`}>
            {item.direction === "may gain" ? "May gain" : "May lose"}</span>
          <span className="mt-gain-body"><strong className="mt-gain-who">{item.who}</strong>
            <span className="mt-gain-how">{item.mechanism}</span></span>
        </li>))}
      </ul>
      <h5>What could soften it</h5>
      <ul className="mt-list mt-list-tight">{chain.mitigants.map((item, at) => <li key={at}>{item}</li>)}</ul>
      <div className="mt-chain-grid mt-learned">
        <div data-learned="">
          <h5>What the data shows</h5>
          <p>{chain.learned}</p>
        </div>
        <div data-assumed="">
          <h5>What is assumed</h5>
          <p>{chain.assumed}</p>
        </div>
      </div>
    </article>
  );
}

function LinkView({ link, usgs }: { link: ChainLink; usgs: Usgs }) {
  // A measured HHI shows the named countries' coverage beside its range: the series is the one its ref names.
  const indicators = link.kind === "measured" && link.shown !== null && usgs !== null
    ? linkIndicators(link.ref, usgs.chapter, usgs.risk) : null;
  return (
    <li className="mt-link" data-kind={link.kind}>
      <span className={`mt-badge mt-badge-${link.kind}`}>{LINK_LABELS[link.kind]}</span>
      <span className="mt-link-body">
        <span className="mt-link-text">{link.text}</span>
        {link.kind === "measured" && (link.shown !== null
          ? <span className="mt-link-value" data-measured="">{link.shown}
            {indicators !== null && indicators.named_share !== null && (
              <span className="mt-sub" data-coverage="">{coverageText(indicators.named_share, indicators.over_total)}</span>)}
          </span>
          : <Why reason={link.unavailable} kind="figure" context={link.text} />)}
        {link.kind === "stated" && <Passage cited={{ passage: link.passage, evidence: link.evidence }} />}
      </span>
    </li>
  );
}
