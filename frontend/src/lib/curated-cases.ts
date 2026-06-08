/**
 * Curated Case Library registry (R6B → expanded T8B) — editorial curation
 * metadata only.
 *
 * Fifteen real, representative archived events, selected in T8A to show the
 * RANGE of outcomes a reviewer should expect — not a best-of and not proof.
 * The slate is contradiction-led to mirror the scored archive (35 contradicted
 * is the modal real outcome), spans six deterministic mechanism families, caps
 * oil at 5 of 15 by theme, and discloses both directions of missingness.  This
 * module carries only editorial framing (role, why-selected, caveats) plus the
 * event id; the live event payload, returns, event-study, and scored outcome
 * are read from the existing backend via the dossier surface the card links to.
 * No fabricated returns or mechanism fields.
 *
 * `family` is the deterministic effective family
 * (family_inference.resolve_effective_family) AS THE BACKEND EMITS IT, verified
 * read-only via db._decode_event_row — never hand-relabelled.  Where the payload
 * carries no mechanism summary (84, 80, 214; 300 historically), the `mechanism`
 * line is explicitly marked editorial and derived only from headline /
 * what_changed / transmission text — never implied as a typed extraction.
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
  /** True when GET /events/{id}/event-study returns event_study_available. */
  eventStudyAvailable: boolean;
  /** Deterministic effective mechanism family (family_inference.resolve_effective_family). */
  family: string;
  role: CaseRole;
  /** Human-facing role label shown on the card. */
  roleLabel: string;
  /** Event headline (display form; lightly trimmed from the archive). */
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
   * quantitative read.  Surfaced as an honest-missingness annotation.  Note the
   * inverse case (#1): raw returns present but event-study unavailable — flagged
   * true here, with the missingness stated in `eventStudyNote`.
   */
  rawReturnsAvailable: boolean;
}

export const CURATED_CASES: CuratedCase[] = [
  // ── commodity_squeeze (4) — oil capped at 5/15 by theme (incl. #72) ──────────
  {
    eventId: 105,
    eventStudyAvailable: true,
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
    eventStudyAvailable: true,
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
    eventId: 85,
    eventStudyAvailable: true,
    family: "commodity_squeeze",
    role: "contradiction",
    roleLabel: "Contradiction",
    headline: "Saudi Arabia restores full East-West pipeline capacity to 7M bpd",
    mechanism:
      "Restoring the Hormuz-bypassing East-West line to 7M bpd removes a supply-disruption premium; refiners and oil consumers ease while disruption-positioned tanker names give back gains.",
    outcome:
      "Contradicted — the directional read did not hold (ratio 0.00); all four tagged names moved against the squeeze thesis.",
    eventStudyNote: "Event-study readout available (vs SPY, n = 1).",
    whySelected:
      "A counter-mechanism oil case: added capacity that bypasses the chokepoint should loosen the squeeze — and the directional read still did not hold.",
    demonstrates: "Even a clean supply-loosening mechanism can fail the event-window read.",
    doesNotProve: "One contradiction does not rule out the mechanism class; it is a single event-window read.",
    caveat: "Descriptive read at n = 1.",
    rawReturnsAvailable: true,
  },
  {
    eventId: 215,
    eventStudyAvailable: true,
    family: "commodity_squeeze",
    role: "unresolved",
    roleLabel: "Unresolved",
    headline: "UAE departs OPEC, reshaping the alliance behind oil prices",
    mechanism:
      "A structural cartel-cohesion shift rather than a price shock: the UAE's exit erodes OPEC spare-capacity discipline, with the energy majors as the watched names.",
    outcome: "Unresolved — no directional tape evidence was captured in the scoring window (no tagged names).",
    eventStudyNote: "Event-study readout available (vs SPY, n = 1).",
    whySelected:
      "A structural mechanism (cartel cohesion), not an acute shock — and one the scorer honestly left unresolved.",
    demonstrates: "Mechanism breadth beyond acute shocks, with an honest unresolved outcome.",
    doesNotProve: "Absence of a captured read is evidence neither for nor against the thesis.",
    caveat: "Descriptive read at n = 1; the affected names carry no directional tag.",
    rawReturnsAvailable: true,
  },
  // ── supply_shock (1) — oil-refining in this corpus, disclosed ────────────────
  {
    eventId: 72,
    eventStudyAvailable: true,
    family: "supply_shock",
    role: "contradiction",
    roleLabel: "Contradiction",
    headline: "China directs independent refiners to hold fuel output amid war disruption",
    mechanism:
      "Forcing teapot refiners to hold domestic output cuts Chinese product exports, tightening global gasoline, diesel and jet balances; US and European refiners sit on the firming side.",
    outcome:
      "Contradicted — the directional read did not hold (ratio 0.25); three of four tagged names moved against the thesis.",
    eventStudyNote: "Event-study readout available (vs SPY, n = 1).",
    whySelected:
      "The lone supply_shock family case, and a humbling one — a coherent refined-product tightening thesis the tape mostly rejected.",
    demonstrates: "Family breadth with an honest contradiction; in this corpus supply_shock overlaps the oil complex.",
    doesNotProve: "A single contradiction does not rule out the mechanism class.",
    caveat: "Descriptive read at n = 1; supply_shock and the oil complex overlap here.",
    rawReturnsAvailable: true,
  },
  // ── tariff (6) — the largest non-oil family in the slate ─────────────────────
  {
    eventId: 84,
    eventStudyAvailable: true,
    family: "tariff",
    role: "strong-support",
    roleLabel: "Strong support",
    headline: "USTR implements a reciprocal tariff calculation framework",
    mechanism:
      "Editorial note: the payload carries no mechanism summary. From the event text, reciprocal tariffs raise import costs and shield domestic producers, with importers and large retailers on the exposed side.",
    outcome: "Any-supporting — tape-direction agreement across a majority of the tagged names (ratio 0.60).",
    eventStudyNote: "Event-study readout available (vs SPY, n = 1).",
    whySelected: "A non-oil any-supporting tariff case carrying both a domestic-producer and an importer leg.",
    demonstrates: "Tape-direction agreement can appear in a policy channel, not only the oil complex.",
    doesNotProve: "Tape-direction agreement is not benchmark-adjusted significance; two of five names disagreed.",
    caveat: "Mechanism line is editorial (the payload carries no summary); descriptive read at n = 1.",
    rawReturnsAvailable: true,
  },
  {
    eventId: 1,
    eventStudyAvailable: true,
    family: "tariff",
    role: "strong-support",
    roleLabel: "Strong support",
    headline: "US weighs new tariffs on Chinese electric-vehicle imports",
    mechanism:
      "Tariffs narrow the price gap Chinese EV makers (BYD, NIO, XPeng) hold over US and European rivals; domestic automakers and EV-ecosystem names sit on the benefiting side.",
    outcome:
      "Any-supporting, but thin — agreement on the single directional name captured (ratio 1.00 on one tagged ticker).",
    eventStudyNote:
      "Event-study readout available (vs SPY, n = 1) — its names were backfilled by the V2C coverage repair.",
    whySelected:
      "A non-oil tariff read scored any-supporting on a single directional name; the V2C coverage repair backfilled its names, so it now also carries an event-study readout.",
    demonstrates: "A thin single-name read that the coverage repair made event-study-readable.",
    doesNotProve: "One directional name is still the thinnest of the supporting cases; an event-study readout does not make it generalisable.",
    caveat: "Single tagged name; descriptive read at n = 1.",
    rawReturnsAvailable: true,
  },
  {
    eventId: 94,
    eventStudyAvailable: true,
    family: "tariff",
    role: "contradiction",
    roleLabel: "Contradiction",
    headline: "How the US–EU pact wards off escalation but raises prices",
    mechanism:
      "Selective tariffs plus preferential transatlantic channels protect some US and EU sectors and raise barriers to third-country imports; Asian exporters sit on the exposed side.",
    outcome:
      "Contradicted — the directional read did not hold (ratio 0.17); five of six tagged names moved against the thesis.",
    eventStudyNote: "Event-study readout available (vs SPY, n = 1).",
    whySelected:
      "A non-oil tariff contradiction with a rich, articulated mechanism — a well-reasoned thesis the tape rejected.",
    demonstrates: "Mechanism depth and a failed read are not mutually exclusive.",
    doesNotProve: "One event-window contradiction does not settle the mechanism.",
    caveat: "Display headline lightly trimmed; descriptive read at n = 1.",
    rawReturnsAvailable: true,
  },
  {
    eventId: 80,
    eventStudyAvailable: true,
    family: "tariff",
    role: "contradiction",
    roleLabel: "Contradiction",
    headline: "US–Ecuador reciprocal commerce agreement",
    mechanism:
      "Editorial note: the payload carries no mechanism summary. From the event text, mutual tariff reductions favour US and Ecuadorian commodity exporters over third-country competitors.",
    outcome: "Contradicted — the directional read did not hold (ratio 0.33).",
    eventStudyNote: "Event-study readout available (vs SPY, n = 1).",
    whySelected: "A thin but real non-oil tariff contradiction, included so the contradictions are not all oil.",
    demonstrates: "A small, all-beneficiary case can still read as a contradiction.",
    doesNotProve: "Thin cross-section (three beneficiary names, no exposed leg) limits what a single read shows.",
    caveat: "Mechanism line is editorial; thin cross-section; descriptive read at n = 1.",
    rawReturnsAvailable: true,
  },
  {
    eventId: 240,
    eventStudyAvailable: true,
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
    eventId: 238,
    eventStudyAvailable: true,
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
  // ── sanction (2) ─────────────────────────────────────────────────────────────
  {
    eventId: 300,
    eventStudyAvailable: true,
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
    eventId: 211,
    eventStudyAvailable: true,
    family: "sanction",
    role: "unresolved",
    roleLabel: "Unresolved",
    headline: "China warns 'price must be paid' after US House approves Xinjiang sanctions",
    mechanism:
      "Sanctions gate US banking and technology services to listed Chinese entities, with Beijing flagging counter-measures; solar (polysilicon) and China-exposed names are the watched legs.",
    outcome: "Unresolved — no directional tape evidence was captured in the window (no tagged names).",
    eventStudyNote: "Event-study readout available (vs SPY, n = 1).",
    whySelected: "A non-oil, multi-name sanction case that complements 300's single-name read.",
    demonstrates: "Sanction-channel breadth beyond a single exposed ticker.",
    doesNotProve: "Absence of a captured read is evidence neither way.",
    caveat: "Descriptive read at n = 1; the names carry no directional tag.",
    rawReturnsAvailable: true,
  },
  // ── policy_surprise (1) — monetary, the only one in the corpus ───────────────
  {
    eventId: 239,
    eventStudyAvailable: true,
    family: "policy_surprise",
    role: "unresolved",
    roleLabel: "Unresolved",
    headline: "Powell says he'll stay on the Fed board as rates hold at 5.25–5.50%",
    mechanism:
      "A higher-for-longer rate read: Fed-independence framing supports banks and regional lenders while pressuring duration-sensitive REITs and Treasuries.",
    outcome: "Unresolved — no directional tape evidence was captured in the window.",
    eventStudyNote: "Event-study readout available; raw market-check returns were not captured.",
    whySelected:
      "The only policy_surprise (monetary) case — a rate-sensitivity cross-section away from commodities and tariffs.",
    demonstrates: "Family breadth into monetary policy, with an honest unresolved outcome.",
    doesNotProve: "Absence of a captured read is evidence neither way.",
    caveat: "Raw market-check returns are unavailable; the event-study readout carries the quantitative read.",
    rawReturnsAvailable: false,
  },
  // ── ceasefire_deescalation (1) — irreducibly thin, flagged ───────────────────
  {
    eventId: 214,
    eventStudyAvailable: true,
    family: "ceasefire_deescalation",
    role: "unresolved",
    roleLabel: "Unresolved",
    headline: "Middle East peace talks stall amid Hormuz tensions and Lebanon ceasefire violations",
    mechanism:
      "Editorial note: the payload carries no mechanism summary. From the event text, stalled de-escalation lifts regional risk premia, with the defence primes (LMT, RTX) as the watched names.",
    outcome: "Unresolved — no directional tape evidence was captured; only two defence names, both untagged.",
    eventStudyNote: "Event-study readout available (vs SPY, n = 1).",
    whySelected:
      "The least-thin ceasefire_deescalation case — included for family breadth, with the thinness stated plainly.",
    demonstrates: "Family coverage, flagged as thin rather than dressed up.",
    doesNotProve: "Two untagged names cannot establish a directional read.",
    caveat: "Thin (two names); mechanism line is editorial; the family has only two scored events in the archive.",
    rawReturnsAvailable: true,
  },
];
