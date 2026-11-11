import { useEffect, type CSSProperties, type ReactNode } from "react";
import type { Loaded } from "../api";
import { NOT_EVALUATED, VERDICT_LABEL } from "../format";
import {
  DOCUMENTED_RULES, DOSSIER_LABELS, LEG_LABELS, PROSPECTIVE_CLASS, SCORE_ANCHORS, TIMELINE_SCOPE, UNSCORED_INTERVAL,
  rulesStatus,
} from "../method";
import { safeDecode } from "../routes";
import type { DossierIndex } from "../types";

const order = (i: number) => ({ "--i": i }) as CSSProperties;

const SECTIONS = [
  ["question", "The question"],
  ["classes", "Evidence classes"],
  ["legs", "Map and legs"],
  ["anchors", "Anchors and horizons"],
  ["labels", "Scoring and labels"],
  ["status", "Not yet evaluated or pending"],
  ["data", "Data and its limits"],
  ["drafting", "Drafting and track record"],
  ["findings", "Treasury findings pilot"],
  ["industry", "Industry findings (G.17)"],
  ["electricity", "Electricity by sector (EIA)"],
  ["cross", "Cross-source comparisons"],
  ["scope", "What is not shown"],
] as const;

type SectionId = (typeof SECTIONS)[number][0];

function Section({ id, index, children }: { id: SectionId; index: number; children: ReactNode }) {
  const title = SECTIONS[index][1];
  return (
    <section id={id} className="method-section" aria-labelledby={`${id}-title`}>
      <p className="kicker">{String(index + 1).padStart(2, "0")}</p>
      <h2 id={`${id}-title`}>{title}</h2>
      {children}
    </section>
  );
}

/**
 * A direct link or refresh with #section scrolls there once the page has rendered, and again once the
 * web fonts have loaded, because their reflow moves the section after the first scroll.
 */
function useHashTarget() {
  useEffect(() => {
    const id = safeDecode(window.location.hash.slice(1));
    const target = id ? document.getElementById(id) : null;
    if (!target) return;
    target.scrollIntoView();
    let active = true;
    document.fonts?.ready.then(() => active && target.scrollIntoView());
    return () => {
      active = false;
    };
  }, []);
}

export function MethodPage({ index }: { index: Loaded<DossierIndex> }) {
  useEffect(() => {
    document.title = "Method · Second Order";
  }, []);
  useHashTarget();
  const rules = rulesStatus(index.state === "ready" ? index.data.active_rules_version : null);

  return (
    <article className="method">
      <header className="method-header reveal" style={order(0)}>
        <p className="kicker">Method</p>
        <h1>How a frozen hypothesis is checked</h1>
        <p className="lede">
          One question: did later market observations align with the measurable implications of a hypothesis frozen
          before the scored move? This page describes what the code does today.
        </p>
        <p className={`rules-status${rules.matches === false ? " is-mismatch" : ""}`} role="note">{rules.text}</p>
      </header>

      <div className="method-layout">
        <nav className="method-toc reveal" style={order(1)} aria-label="On this page">
          <p className="kicker">On this page</p>
          <ol>
            {SECTIONS.map(([id, title]) => (
              <li key={id}><a href={`#${id}`}>{title}</a></li>
            ))}
          </ol>
        </nav>

        <div className="method-body reveal" style={order(2)}>
          <Section id="question" index={0}>
            <p>
              A hypothesis names a published event, the channels it expects the event to move, and market observables
              that should then move in a stated direction over a stated horizon. Once frozen it cannot be edited; a
              revision is a new record.
            </p>
            <p>
              A label says whether later observations were <em>consistent</em> with that hypothesis. It is not proof
              that the event caused the move: other news, positioning, anticipation and term premium move the same
              prices, the transmission map is a hypothesis rather than a demonstrated mechanism, and the labels are
              descriptive thresholds, not significance tests.
            </p>
          </Section>

          <Section id="classes" index={1}>
            <dl className="method-pair">
              <div className="card">
                <dt>Prospective</dt>
                <dd>{PROSPECTIVE_CLASS}</dd>
              </div>
              <div className="card">
                <dt>Retrospective replay</dt>
                <dd>
                  Written after the event, with a simulated freeze at publication and scoring from the last
                  observation before it. The outcome was already known: a replay illustrates the method; it is not a
                  forecast.
                </dd>
              </div>
            </dl>
            <p>
              Prospective and replay results are never pooled, because their anchors measure different responses.
              Showcase cases illustrate the lifecycle and never enter research scores. Research summaries use the
              primary legs of research cases only, one evidence class and one rules configuration at a time. Research
              intake is closed, so there are no research results.
            </p>
          </Section>

          <Section id="legs" index={2}>
            <p>The transmission map has four kinds of node:</p>
            <ul className="method-list">
              <li><strong>Event</strong>: the published event.</li>
              <li><strong>Channel</strong>: a step on the claimed path. Unscored.</li>
              <li><strong>Observable</strong>: a measured implication. Each has exactly one leg.</li>
              <li><strong>Explanatory</strong>: a competing explanation or context. Unscored; never has a leg.</li>
            </ul>
            <p>
              A hypothesis has two to four legs on distinct observables, exactly one of them <strong>primary</strong>.
              Each leg states a direction, one horizon (1, 5 or 20 observations), a falsifier and whether the headline
              already reports the move. The Dossier label follows the primary leg; <strong>secondary</strong> legs can
              only qualify it. Falsifiers are explanatory text and are not adjudicated automatically. Units, anchor
              policy and data source come from a closed registry, not from the hypothesis.
            </p>
          </Section>

          <Section id="anchors" index={3}>
            <p>{TIMELINE_SCOPE}</p>
            <ol className="timeline card"
                aria-label="A prospective leg whose score anchor follows the freeze, from reference history to horizon end">
              <li className="timeline-span span-reference">
                <strong>Reference history</strong>
                <span>Up to {DOCUMENTED_RULES.reference_days} same-horizon windows ending at the event anchor</span>
              </li>
              <li className="timeline-point">
                <strong>Event anchor</strong>
                <span>Last observation before publication</span>
              </li>
              <li className="timeline-span span-unscored">
                <strong>Initial reaction · unscored</strong>
                <span>Publication and freeze fall here</span>
              </li>
              <li className="timeline-point">
                <strong>Score anchor</strong>
                <span>First observation after the freeze</span>
              </li>
              <li className="timeline-span span-scored">
                <strong>Scored window</strong>
                <span>Ends at the horizon end, h observations later</span>
              </li>
            </ol>
            <p>
              The <strong>event anchor</strong> is the last observation before publication; for date-only series, the
              last observation dated before the publication date. Reference history ends there, so the event's own
              reaction never becomes ordinary history.
            </p>
            <p>The <strong>score anchor</strong>, where the scored move starts, depends on the observable and the case:</p>
            <ul className="method-list">
              {SCORE_ANCHORS.map(({ applies, anchor }) => (
                <li key={applies}><strong>{applies}</strong>: {anchor}</li>
              ))}
            </ul>
            <p>{UNSCORED_INTERVAL}</p>
            <p>
              The horizon counts observations on the series' own grid: explained calendar gaps leave the grid,
              unexplained gaps stay in it as missing values, and horizons are never compressed.
            </p>
          </Section>

          <Section id="labels" index={4}>
            <p>
              The measured change times the expected direction (+1 up, −1 down) is the <strong>signed move</strong>. It
              is ranked against the reference windows, transformed the same way:{" "}
              <span className="formula">rank = (windows below + ½ × windows equal) ÷ windows</span>. At least{" "}
              {DOCUMENTED_RULES.min_windows} usable windows are required; that is an availability gate, not a precision
              claim. Equity legs use abnormal returns from a market model fitted against SPY, so their label is relative
              to the market rather than the stock's absolute direction.
            </p>
            <dl className="label-list card">
              {LEG_LABELS.map(({ verdict, meaning }) => (
                <div key={verdict}>
                  <dt><span className={`verdict-chip verdict-${verdict}`}>{VERDICT_LABEL[verdict]}</span></dt>
                  <dd>{meaning}</dd>
                </div>
              ))}
            </dl>
            <p>The Dossier follows its primary leg, with two qualified cases:</p>
            <dl className="label-list card">
              {DOSSIER_LABELS.map(({ verdict, meaning }) => (
                <div key={verdict}>
                  <dt><span className={`verdict-chip verdict-${verdict}`}>{VERDICT_LABEL[verdict]}</span></dt>
                  <dd>{meaning}</dd>
                </div>
              ))}
            </dl>
            <p>
              For each scored primary leg, up to {DOCUMENTED_RULES.placebo_dates} control dates from the preceding year
              are scored the same way, each with its own reference history. Their rates show how often the rule fires
              on ordinary dates; they are a measured baseline, not a significance test.
            </p>
            <div className="table-scroll">
              <table className="rules-table">
                <caption>Rules {DOCUMENTED_RULES.version}</caption>
                <tbody>
                  <tr><th scope="row">Supported needs a rank of at least</th><td>{DOCUMENTED_RULES.upper.toFixed(2)}</td></tr>
                  <tr><th scope="row">Contradicted needs a rank of at most</th><td>{DOCUMENTED_RULES.lower.toFixed(2)}</td></tr>
                  <tr><th scope="row">Reference windows</th><td>up to {DOCUMENTED_RULES.reference_days}</td></tr>
                  <tr><th scope="row">Usable windows required</th><td>{DOCUMENTED_RULES.min_windows}</td></tr>
                  <tr>
                    <th scope="row">Market-model estimation (equities)</th>
                    <td>
                      {DOCUMENTED_RULES.estimation_days} returns, ending {DOCUMENTED_RULES.estimation_gap} observations
                      before the event anchor
                    </td>
                  </tr>
                  <tr><th scope="row">Placebo control dates</th><td>up to {DOCUMENTED_RULES.placebo_dates}</td></tr>
                </tbody>
              </table>
            </div>
          </Section>

          <Section id="status" index={5}>
            <dl className="method-pair">
              <div className="card">
                <dt><span className="verdict-chip state-unevaluated">{NOT_EVALUATED}</span></dt>
                <dd>
                  No evaluation is stored. The case is frozen and nothing has been measured, so its Dossier shows no
                  chart, ranking or label.
                </dd>
              </div>
              <div className="card">
                <dt><span className="verdict-chip verdict-pending">{VERDICT_LABEL.pending}</span></dt>
                <dd>
                  An evaluation is stored, but its scored window was incomplete when it ran. The record keeps its anchors
                  and reason. A later evaluation is a new record, never an edit.
                </dd>
              </div>
            </dl>
            <p>
              Freezing and evaluation are always explicit steps. The Dossier and this page read prepared files only:
              they never evaluate, import data, call a model or schedule work. The Hypotheses page freezes only on an
              explicit approval of one freeze preview, and assesses only on an explicit approval of one assessment
              preview ("Evaluate and prepare Dossier"), which evaluates that one hypothesis, records the result beside
              any earlier ones and prepares its Dossier. The server sets the assessment's cutoff from the inputs: the
              end, in New York, of each leg's target date, or the outcome snapshot's receipt time if later. The
              preview shows what will be assessed, not the result, so no result is seen before it is kept. Opening a
              page only reads.
            </p>
          </Section>

          <Section id="data" index={6}>
            <p>
              <strong>Pinned snapshots.</strong> The source-bound observables, Treasury constant-maturity yields, are
              measured from pinned snapshots of one provider each: FRED (DGS2 and DGS10) or the Federal Reserve Board's
              H.15 release package (its 2-year and 10-year series, under their own observable IDs). A leg is never
              measured on another provider's data. A baseline snapshot is bound at freeze, and every date before the
              publication date comes only from it. An outcome snapshot is named at evaluation, and every date from the
              publication date on comes from it; it is imported, or its release package downloaded, only by an explicit
              approval, and never fills the baseline's history. Each snapshot keeps the observation date and the time we held the data
              apart; a FRED snapshot also has its requested vintage date, while the Board's package has no historical
              vintage, so its receipt time shows possession, not first publication. A stored evaluation is authoritative:
              preparation rebuilds it from the pinned snapshots, recorded rules and evaluation clock, and refuses to show
              it unless the rebuild matches exactly.
            </p>
            <p>
              <strong>Overlapping windows.</strong> With a 5-observation horizon, neighbouring reference windows share
              four of five observations, so {DOCUMENTED_RULES.reference_days} windows hold far fewer independent
              observations; each Dossier also
              reports the non-overlapping count. Placebo controls overlap too. None of these counts is an independent
              sample size.
            </p>
            <p>
              <strong>Daily dates.</strong> These yields are compared by America/New_York date. Treasury quotes them at
              or near 3:30 PM with no documented bound, so no intraday time is claimed: the publication-day reaction
              cannot be separated from the rest of that day, and a prospective leg starts at the first date after the
              freeze date. These legs cannot enter research summaries, which require verified observation timestamps,
              and two maturities of one yield curve are not independent evidence. A day's yields reach FRED or the
              release package a day or so later, so every new freeze applies freshness policy B: the baseline must
              classify, for every leg, the last expected session before the publication date. A session the source
              states without a value counts as covered and stays missing, and reference history is never completed from
              outcome data. Records frozen before the policy are read and evaluated exactly as stored.
            </p>
            <p>
              <strong>Fixture replays.</strong> The two showcase replays are fictional events measured on committed
              FICTIONAL demonstration series (demo-market-0.1): every number is invented by a deterministic generator,
              nothing is a market observation, and their illustrative day-end timestamps are refused for a research
              score. A research hypothesis cannot name these series, and the research scoreboard never counts them.
            </p>
            <p className="attribution">
              This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of St. Louis.
            </p>
          </Section>

          <Section id="drafting" index={7}>
            <p>
              An offline drafting adapter can turn an event's metadata and source text into a draft. The model supplies
              only the summary, map and legs; code sets the event, class, usage and engine record and hashes the exact
              request. The response is validated strictly, and any failure refuses the draft, with no repair and no
              fallback hypothesis.
            </p>
            <p>
              The drafting command only previews a request or validates a saved response. The only live path is a
              two-case pilot on synthetic cases, which needs an explicit key and confirmation and sends each case at
              most once. New Tracker requests use the H.15 drafting contract (draft-prompt-6, which offers the Board's
              H.15 IDs); a request saved under the earlier contract keeps its FRED IDs and is never rebuilt. The
              Hypotheses page freezes a manual hypothesis, whose engine record states how it was authored, or a real
              provider draft under the H.15 contract whose current review is marked Human-reviewed, with only the
              corrections review permits applied. Human review is not approval: the freeze is its own explicit step.
              Manual means outside the model adapter, not that no AI was involved. The command-line freeze helper
              accepts manual drafts only, and the lower-level freeze command does not check the provider.
            </p>
            <p>
              <strong>There is no validated model track record.</strong> Showcase cases demonstrate the lifecycle; they
              do not measure model performance.
            </p>
          </Section>

          <Section id="findings" index={8}>
            <p>
              The Findings page is a retrospective, single-market pilot that needs no hypothesis or note. One explicit
              check reads the newest accepted H.15 release package kept on this computer and the retained events, and
              measures daily Treasury yields around each dated Federal Reserve monetary-policy, BLS employment or BLS CPI
              release. It contacts no provider, calls no model and writes only its own records; opening a page only
              reads. A newer package is used only by the next check, and a result whose exact observations, date and
              definitions are unchanged is reused, with the newer package recorded as its provenance too.
            </p>
            <p>
              <strong>Events.</strong> Records of one release are joined only when publisher, canonical address and date
              agree, and every originating record stays linked; recurring titles are never merged. Each date shows its
              basis: supplied when the event was captured, confirmed by you in the Inbox, the publisher's feed timestamp
              (unconfirmed metadata) or recorded by the case library's editor (not independently verified). Releases
              dated the same New York day share one measurement, because daily data cannot tell them apart.
            </p>
            <p>
              <strong>Windows and ranks.</strong> On the grid of the six yield series (3-month, 2-, 5- and 10-year
              nominal; 5- and 10-year inflation-indexed), W1 runs from the session before the event date to the first
              session after it and W5 to the fifth; both include the event date's own session, so they show everything
              that moved yields then and never isolate a response to the announcement. PRE covers the five sessions
              before. Each change, in basis points from the source's exact values, is ranked by absolute size against
              the 250 windows of the same span that end on or before the measured window's start;{" "}
              <span className="formula">rank = (smaller + ½ × equal) ÷ eligible windows</span>, and at least 200 eligible
              windows are required. A missing endpoint leaves a change unavailable; nothing is interpolated or shifted.
            </p>
            <p>
              <strong>Rules.</strong> R1 (offsetting real-yield and breakeven changes under an ordinary nominal change),
              R2 (one component dominating a large nominal change, with its share stated), R3 (a large 2s10s slope
              change) and R4 (a large move before the event with an ordinary one after, or the reverse) are exploratory:
              they were designed after inspecting this dataset. Each occasion's twelve rule checks are met, not met or
              not evaluable, and an occasion where none is met is shown with its numbers. How often a check is met on
              200 comparison sessions (drawn by a recorded seed from 2005 to 2025, excluding any whose windows contain
              the date of an occasion measured here) describes how common the pattern is; it is not a p-value or a chance probability.
            </p>
            <p>
              The yields are one lineage (Treasury curves republished by the Board and FRED), so series compared here
              never corroborate each other. Findings are context, not research evidence: they never enter hypotheses,
              evaluations or research summaries.
            </p>
          </Section>

          <Section id="industry" index={9}>
            <p>
              A second, separate evidence type on the Findings page reads Table 1 and the release summary of retained
              Federal Reserve G.17 releases (industrial production). Only pages kept by the approved acquisitions are
              used, each with its recorded SHA-256; every page must state the G.17 identity, its own release date, a
              last update on that date, the expected table and units (percent change, seasonally adjusted) and six
              consecutive monthly columns marked revised or preliminary, and Table 1 must agree with the release summary.
            </p>
            <p>
              Rows are identified by their full path in the table (section and parent rows) and their NAICS code, never
              by label alone; broad Manufacturing and Manufacturing (NAICS) are different rows. Within one release,
              Manufacturing, Mining and Utilities are compared with Total IP, and each NAICS subsector with its durable
              or nondurable parent, for the same reference month. Across consecutive releases, the same row and month are
              compared as revisions. Values are the published rates as printed, compared with exact decimals; a printed
              0.0 has no resolvable direction, differences are in percentage points, and nothing uses index levels,
              weights or contributions to the total. Revisions are changes in published estimates, not activity between
              release dates, and archived pages compared as published versions do not prove that the historical bytes
              are unchanged.
            </p>
            <p>
              <strong>Manufacturing breadth.</strong> For each release and month, the 19 NAICS manufacturing subsectors
              (11 durable, 8 nondurable, identified by path and code) are counted as printed up, down, 0.0 or not
              printed, beside the Manufacturing (NAICS) rate. Shares of the 19 and a majority (more than half, so 10 or
              more) are stated only when all 19 are printed. Three comparisons stay apart: the aggregate against most
              subsectors in one release and month; consecutive months within one release; and the same month in
              consecutive releases, with the subsectors that switched direction. The counts are unweighted: not
              contributions, weights or the whole economy, and mining, utilities and other (non-NAICS) manufacturing
              are outside the universe.
            </p>
          </Section>

          <Section id="electricity" index={10}>
            <p>
              A third, separate evidence type reads the EIA Monthly Energy Review Table 7.6 kept on this computer by the
              approved acquisitions: the CSV (the only source of values), the printed table (PDF, the source of the
              definitions, transcribed from its page image and bound to its SHA-256) and the Monthly Energy Review page.
              The CSV must carry exactly the eight published series with their codes, descriptions and unit (million
              kilowatthours), one row per series and date, monthly and annual rows kept apart, and every value a plain
              decimal or "Not Available".
            </p>
            <p>
              Retail sales to the residential, commercial and industrial sectors are compared, each month from July 2025
              to June 2026, with the same month a year earlier, in million kWh and percent; January–June 2026 is compared
              with January–June 2025 by summing each sector's six months first. A change of +1% or more is up, −1% or
              less is down (both inclusive, decided on exact values), anything between is little changed; a month is a
              finding when one sector is up and another down. The 1% band is a fixed, transparent product filter, not
              statistical significance, an empirically calibrated threshold or proof of materiality, and zero findings
              is a valid result. Transportation (railway sales only) and total retail sales are context; direct use and
              electric vehicle estimates are excluded. The four sectors are checked against total retail sales within
              the rounding of five values published to 0.001 million kWh, and contributions to the change in the total
              are shown only where that holds.
            </p>
            <p>
              These are retail sales, not total electricity consumption, not adjusted for weather, calendar or prices,
              and they say nothing about economic output or causes. Whether a value is preliminary is not marked in the
              data, a single retained acquisition is not a revision history, and the PDF's September 2026 edition is not
              assigned to the CSV, which states none.
            </p>
          </Section>

          <Section id="cross" index={11}>
            <p>
              A last part of the Findings page sets the two retained sources side by side for the same periods: EIA
              industrial retail electricity sales beside G.17 Manufacturing (NAICS) output, and G.17 electric utility
              output beside the customer breakdown of EIA total retail sales. The periods are the fourth quarters of
              2023, 2024 and 2025 against the previous fourth quarter (EIA October–December totals, all three months
              required in both years) and each 12-month period a retained G.17 release prints; a period the EIA file does
              not reach is shown as not covered, and no other month is used in its place. G.17 values are read from the
              table's own header structure, as printed, from the latest retained release that prints the period, with
              every release's value beside it.
            </p>
            <p>
              The comparisons are descriptive. Signs say only whether each reported change is above or below zero, with
              no threshold, and a G.17 rate printed as 0.0 has no direction; they are not the ±1% categories above. No
              growth rates are subtracted or combined. Retail purchases are not total consumption, an output index is not
              kilowatthours, G.17 is seasonally adjusted and the EIA sales are not, the EIA industrial class is not NAICS
              manufacturing, and the vintages differ. Whether the Federal Reserve's measures draw on EIA data is not
              stated in the retained material, so agreement between them is not treated as corroboration. The customer
              breakdown decomposes EIA total retail sales only, and explanations such as industry mix, weather or
              self-generation are listed as possibilities the observations do not establish.
            </p>
          </Section>

          <Section id="scope" index={12}>
            <p>
              No research results are shown, because research intake is closed; no support or contradiction rates are
              computed from showcase cases. A hypothesis frozen and assessed from the Hypotheses page is a prospective
              showcase: its daily-date observations do not meet the research timestamp gate, and its assessments are
              listed by record time, never summarised into a success rate or presented as validated forecasting
              performance. Nothing here is a trading signal or a recommendation.
            </p>
            <p>
              The earlier v1 Research Lab is a separate project kept in a sibling local repository (geo_mechanism_project,
              source snapshot <code>a36960107e02</code>). It has no public link yet. The full specification is SPEC.md in
              this repository.
            </p>
          </Section>
        </div>
      </div>
    </article>
  );
}
