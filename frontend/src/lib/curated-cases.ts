/**
 * Curated Case Library registry (R6B) — editorial curation metadata only.
 *
 * Five real, representative archived events (one per role), selected in R6A to
 * show the RANGE of outcomes a reviewer should expect — not a best-of and not
 * proof.  This module carries only editorial framing (role, why-selected,
 * caveats) plus the event id; the live event payload, returns, event-study, and
 * scored outcome are read from the existing backend via the dossier surface the
 * card links to.  No fabricated returns or mechanism fields.
 *
 * Outcomes were derived read-only from the archive: 166 saved events, 81 with
 * market data scored (19 any-supporting / 35 contradicted / 27 unresolved).
 * These are descriptive archive denominators, separate from the closed
 * Phase 1 / Phase 2 FDR pools.
 *
 * Copy carries no buy/sell/long/short/alpha/signal/trade framing and no
 * proof/confirmed/validated-as-success framing.
 */

export type CaseRole =
  | "strong-support"
  | "contradiction"
  | "unresolved"
  | "data-limited"
  | "mechanism-rich";

export interface CuratedCase {
  /** Archive event id — the card links to /share/{eventId}. */
  eventId: number;
  /** Deterministic effective mechanism family (family_inference.resolve_effective_family). */
  family: string;
  role: CaseRole;
  /** Human-facing role label shown on the card. */
  roleLabel: string;
  /** Event headline (verbatim from the archive). */
  headline: string;
  /** One-line mechanism note; editorial where the payload carries none. */
  mechanism: string;
  /** Honest outcome category — never a success verdict. */
  outcome: string;
  /** Event-study availability note. */
  eventStudyNote: string;
  whySelected: string;
  demonstrates: string;
  doesNotProve: string;
  caveat: string;
  /**
   * False when the event has no stored raw market-check returns — the dossier's
   * affected-asset line is blank and the event-study readout carries the
   * quantitative read.  Surfaced as an honest-missingness annotation.
   */
  rawReturnsAvailable: boolean;
}

export const CURATED_CASES: CuratedCase[] = [
  {
    eventId: 105,
    family: "commodity_squeeze",
    role: "strong-support",
    roleLabel: "Strong support",
    headline: "OPEC extends voluntary oil output cuts through next quarter",
    mechanism:
      "Voluntary supply cuts tighten crude; energy producers and refiners firm while airlines and freight carry the cost.",
    outcome: "Any-supporting — tape-direction agreement across the scored names (ratio 0.75).",
    eventStudyNote: "Event-study readout available (vs SPY, n = 1).",
    whySelected:
      "The cleanest multi-leg second-order transmission, with both raw event-window returns and an event-study readout.",
    demonstrates: "How a supply-policy thesis can show tape-direction agreement across several legs at once.",
    doesNotProve:
      "Tape-direction agreement is not benchmark-adjusted significance; the 5-day abnormal return was near zero and one leg disagreed.",
    caveat: "Descriptive read at n = 1 — agreement on the tape is not an established mechanism.",
    rawReturnsAvailable: true,
  },
  {
    eventId: 29,
    family: "commodity_squeeze",
    role: "contradiction",
    roleLabel: "Contradiction",
    headline: "Iran threatens to 'completely' close the Strait of Hormuz",
    mechanism:
      "Chokepoint-risk thesis: closure fears should lift crude and energy names and weigh on airlines.",
    outcome: "Contradicted — the directional read did not hold (ratio 0.00).",
    eventStudyNote: "Event-study readout available; the 5-day abnormal return was negative.",
    whySelected:
      "The canonical oil-shock thesis the tape rejected, on both the raw read and the benchmark-adjusted read.",
    demonstrates: "That an obvious-seeming geopolitical thesis can fail — the library is not a wall of agreement.",
    doesNotProve: "A single contradiction does not rule out the mechanism class; it is one event-window read.",
    caveat: "Descriptive read at n = 1; some names carry only a partial return series.",
    rawReturnsAvailable: true,
  },
  {
    eventId: 240,
    family: "tariff",
    role: "unresolved",
    roleLabel: "Unresolved",
    headline: "GM raises 2026 guidance amid a $500M tariff refund",
    mechanism:
      "A Section 232 steel and aluminium tariff refund accrues to automakers; steel names sit on the exposed side.",
    outcome: "Unresolved — no directional evidence was captured in the scoring window.",
    eventStudyNote: "Event-study readout available; raw market-check returns were not captured.",
    whySelected: "A real, recent tariff-channel thesis that stayed unresolved rather than being forced into a verdict.",
    demonstrates: "Honest unresolved — the scorer abstains when directional tape evidence is absent.",
    doesNotProve: "Absence of a read is evidence neither for nor against the thesis.",
    caveat: "Raw market-check returns are unavailable; the event-study readout carries the quantitative read.",
    rawReturnsAvailable: false,
  },
  {
    eventId: 300,
    family: "sanction",
    role: "data-limited",
    roleLabel: "Data-limited",
    headline: "US license requirement on NVIDIA A100/H100 exports to China",
    mechanism:
      "Export controls cut a single exposed name's China datacenter GPU sales (editorial note: the payload carries no mechanism summary for this anchor).",
    outcome: "Unresolved — a single name at n = 1 cannot be scored directionally.",
    eventStudyNote: "Event-study readout available; a sizeable negative abnormal return at 5 days.",
    whySelected:
      "A single-name historical anchor: scored unresolved precisely because the data is thin, yet the event-study still gives a descriptive read.",
    demonstrates: "Honest missingness — thin data is labelled, not dressed up.",
    doesNotProve: "One name's move is not a generalisable result.",
    caveat:
      "No mechanism summary or raw returns in the payload; the event-study readout carries the quantitative read, and the mechanism line here is editorial context for a public event.",
    rawReturnsAvailable: false,
  },
  {
    eventId: 238,
    family: "tariff",
    role: "mechanism-rich",
    roleLabel: "Mechanism-rich",
    headline: "China scraps tariffs on 53 African nations",
    mechanism:
      "A zero-tariff import channel favours lithium, cobalt and copper producers, with China demand proxies as second-order beneficiaries.",
    outcome: "Unresolved — the mechanism is articulated; the outcome is not resolved (dual role).",
    eventStudyNote: "Event-study readout available; raw market-check returns were not captured.",
    whySelected: "The richest articulated second-order commodity-channel mechanism, away from oil and geopolitics.",
    demonstrates: "A clean mechanism can be stated even when the outcome stays unresolved.",
    doesNotProve: "A well-formed mechanism is a hypothesis, not a result.",
    caveat:
      "Dual role (mechanism-rich and unresolved); raw returns are unavailable, so the event-study readout carries the quantitative read.",
    rawReturnsAvailable: false,
  },
];
