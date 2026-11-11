// What the Method page documents, kept as data so tests can check it against real prepared output.
// The Method page explains implemented behavior; it defines no rule of its own.

import type { DossierVerdict, LegVerdict, Rules } from "./types";

/** The rules configuration this page documents. A test pins it to the rules recorded in a real evaluation. */
export const DOCUMENTED_RULES: Rules = {
  version: "0.5.0",
  upper: 0.8,
  lower: 0.2,
  reference_days: 250,
  min_windows: 120,
  estimation_days: 250,
  estimation_gap: 10,
  placebo_dates: 50,
};

const rank = (value: number) => value.toFixed(2);

/** Leg labels, in the order the scorer considers them. */
export const LEG_LABELS: { verdict: LegVerdict; meaning: string }[] = [
  { verdict: "supported",
    meaning: `The signed move is positive and its percentile rank is at least ${rank(DOCUMENTED_RULES.upper)}.` },
  { verdict: "contradicted",
    meaning: `The signed move is negative and its percentile rank is at most ${rank(DOCUMENTED_RULES.lower)}.` },
  { verdict: "inconclusive",
    meaning: "Scored, but neither condition holds. An extreme rank whose sign does not match the expected " +
             "direction is still inconclusive." },
  { verdict: "unavailable",
    meaning: `The data cannot support a score: for example a missing observation inside a required window, fewer ` +
             `than ${DOCUMENTED_RULES.min_windows} usable reference windows, or a calendar that does not cover the ` +
             "horizon. Research cases also require verified observation timestamps." },
  { verdict: "excluded",
    meaning: "The headline already reports this measured move and the scoring anchor coincides with the event " +
             "anchor, so a score would only restate the headline." },
  { verdict: "pending",
    meaning: "The scored window was incomplete when the evaluation ran: the score anchor had not been imported " +
             "(for daily yields, no observation dated after the freeze date), the horizon end was not yet in the " +
             "imported data, or the horizon had not elapsed at the evaluation clock." },
];

/** How a prospective case relates its freeze to its scored window. */
export const PROSPECTIVE_CLASS =
  "Frozen after publication at a real freeze time. For most observables the scored window starts after the " +
  "freeze, so its outcome was unknown when the hypothesis was written. An equity frozen outside a regular " +
  "session is scored from the preceding close, so extended-hours trading already visible at the freeze can " +
  "fall inside its scored window.";

/** Where each kind of leg starts its scored move. The registry assigns the policy, never the hypothesis. */
export const SCORE_ANCHORS: { applies: string; anchor: string }[] = [
  { applies: "Daily Treasury yields", anchor: "the first observation dated after the freeze date." },
  { applies: "Futures and other non-equity series", anchor: "the first observation after the freeze." },
  { applies: "Equities frozen during a regular session, its close included",
    anchor: "the first regular-session close after the freeze." },
  { applies: "Equities frozen outside a regular session",
    anchor: "the last regular-session close before the freeze. The score anchor then precedes the freeze and " +
            "can coincide with the event anchor, so extended-hours trading already visible at the freeze may be " +
            "part of the scored move." },
  { applies: "Replays",
    anchor: "the event anchor, under the simulated freeze at publication, so the whole initial reaction is " +
            "part of the scored move." },
];

/** The timeline draws only the cases whose score anchor follows the freeze. */
export const TIMELINE_SCOPE =
  "The timeline shows a prospective leg whose score anchor follows the freeze: daily yields, futures and other " +
  "non-equity series, and equities frozen during a regular session.";

/** What lies between the two anchors, case by case. */
export const UNSCORED_INTERVAL =
  "Everything between the event anchor and the score anchor is shown but not scored. When the score anchor " +
  "follows the freeze, that interval holds the publication-day reaction, and a late freeze measures only what " +
  "follows it. When the anchors coincide, as in every replay and in an equity frozen outside a regular session " +
  "with no session close between publication and freeze, nothing is left unscored: the initial reaction is part " +
  "of the scored move, and a leg whose headline already reports that move is excluded.";

/** Dossier labels: the Dossier follows its primary leg, with two qualified cases. */
export const DOSSIER_LABELS: { verdict: Exclude<DossierVerdict, LegVerdict>; meaning: string }[] = [
  { verdict: "mixed", meaning: "The primary leg is supported and a secondary leg is contradicted." },
  { verdict: "incomplete",
    meaning: "The primary leg is supported and secondary evidence is pending, unavailable or excluded." },
];

/** Whether the prepared index reports the rules version this page documents. */
export function rulesStatus(active: string | null): { matches: boolean | null; text: string } {
  if (active === null) {
    return { matches: null, text: `This page documents rules ${DOCUMENTED_RULES.version}. The prepared index is not ` +
                                  "loaded, so the active version is not shown." };
  }
  return active === DOCUMENTED_RULES.version
    ? { matches: true, text: `This page documents rules ${DOCUMENTED_RULES.version}, the version the prepared ` +
                             "index reports as active." }
    : { matches: false, text: `This page documents rules ${DOCUMENTED_RULES.version}, but the prepared index ` +
                              `reports ${active} as active. Each Dossier shows the rules recorded with its evaluation.` };
}
