/**
 * Curated Case Library registry (R6B → expanded T8B) — editorial curation
 * metadata only.
 *
 * Fifteen real, representative archived events, selected in T8A to show the
 * RANGE of outcomes a reviewer should expect — not a best-of and not proof.
 * The slate is deliberately NOT distribution-proportional: it over-weights
 * contradictions and unresolved reads (the accepted corpus is any-supporting-
 * modal) so the library is not a wall of agreement — chosen for mechanism /
 * evidence clarity, not as a sample. It spans six deterministic mechanism
 * families, caps oil at 5 of 15 by theme, and discloses both directions of
 * missingness.  This
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
 * Outcomes were derived read-only from the archive and restated 2026-07-11
 * after the directional-evidence recovery (five-day directions back-computed
 * from already-cached bars for eight accepted events) and natural window
 * maturation. The live archive holds 180 saved events; the accepted
 * track-record corpus is 86 events after excluding 71 synthetic/test seed rows
 * flagged in event_hygiene (kept in the archive, never deleted). Two outcome
 * lenses, never merged: the Any-support OR-rule ledger reads 59 any-supporting
 * / 14 contradicted / 13 unresolved, and the directional-majority ledger
 * (validation_status_v2) reads 29 / 44 / 13 over the same 86 rows. Selection
 * roles below are FROZEN at T8A selection time and never follow later
 * outcomes; the outcome copy per case is current-archive data. These are
 * descriptive archive denominators, separate from the closed Phase 1 /
 * Phase 2 FDR pools.
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
    outcome:
      "Contradicted — all three recovered directional names moved against the thesis (ratio 0.00) under both lenses.",
    eventStudyNote: "Event-study readout available (vs SPY, n = 1).",
    whySelected:
      "A structural mechanism (cartel cohesion), not an acute shock — selected while the scorer honestly left it unresolved; the 2026-07-11 directional-evidence recovery resolved it against the thesis. Selection role retained, and the adverse resolution stays.",
    demonstrates: "A structural mechanism whose recovered read went against the thesis — recovery cuts both ways.",
    doesNotProve: "One adverse read does not rule out the mechanism class; it is a single event-window read.",
    caveat: "Descriptive read at n = 1; directions recovered 2026-07-11 from already-cached bars.",
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
      "Contradicting-majority under the directional-majority rule — three of four tagged names moved against the thesis (support ratio 0.25). The any-support OR-rule would count the single agreeing name, which is exactly why the two ledgers are kept separate.",
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
      "Contradicting-majority under the directional-majority rule — five of six tagged names moved against the thesis (support ratio 0.17); the any-support OR-rule would count the single agreeing name.",
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
    outcome:
      "Contradicting-majority under the directional-majority rule — two of three names moved against the thesis (support ratio 0.33); the any-support OR-rule would count the single agreeing name.",
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
    outcome:
      "Any-supporting under the OR-rule — all three directional names agreed (ratio 1.00) once the five-day window matured; the directional-majority read concurs.",
    eventStudyNote: "Event-study readout available; raw market-check returns were not captured.",
    whySelected:
      "A real, recent tariff-channel thesis selected while its scoring window was still open and the read unresolved; the window matured and the read resolved supporting. Selection role retained.",
    demonstrates: "Recent events start unresolved and resolve as their windows mature — the scorer abstains, then reads.",
    doesNotProve: "A matured supporting read is still one event-window read at n = 1.",
    caveat:
      "Raw market-check returns are unavailable; the event-study readout carries the quantitative read. Outcome restated 2026-07-11 after window maturation.",
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
    outcome:
      "Split read after window maturation: any-supporting under the OR-rule (2 of 4 names, ratio 0.50) but an exact 2-2 tie — contradicting-majority-or-tie under the directional-majority rule. The two lenses disagree on this case.",
    eventStudyNote: "Event-study readout available; raw market-check returns were not captured.",
    whySelected: "The richest articulated second-order commodity-channel mechanism, away from oil and geopolitics.",
    demonstrates: "A clean mechanism can be stated even when the two outcome lenses split on the read.",
    doesNotProve: "A tied read establishes neither direction; a well-formed mechanism is a hypothesis, not a result.",
    caveat:
      "Dual role (mechanism-rich); a live example of why the two ledgers differ — one agreeing name satisfies the OR-rule while the tie reads contradicting under the majority rule. Raw returns unavailable; outcome restated 2026-07-11.",
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
    outcome:
      "Any-supporting under the OR-rule — the single exposed name agreed with the thesis (ratio 1.00 on one tagged ticker); the directional-majority read rests on that same single name.",
    eventStudyNote: "Event-study readout available; a sizeable negative abnormal return at 5 days.",
    whySelected:
      "A single-name historical anchor selected for its honest thinness; the name's window later matured to a supporting read. Selection role retained — the read is still one name.",
    demonstrates: "Honest missingness — thin data is labelled, and a one-name resolved read is still thin.",
    doesNotProve:
      "One name's move is not a generalisable result — this is one of the archive's single-ticker decisive reads the validation-status calibration flags.",
    caveat:
      "No mechanism summary or raw returns in the payload; the event-study readout carries the quantitative read, and the mechanism line here is editorial context for a public event. Single tagged name; outcome restated 2026-07-11.",
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
    outcome:
      "Any-supporting under the OR-rule — all three recovered directional names agreed with the thesis (ratio 1.00); the directional-majority read concurs.",
    eventStudyNote: "Event-study readout available (vs SPY, n = 1).",
    whySelected:
      "A non-oil, multi-name sanction case that complements 300's single-name read — selected while its names were untagged; the 2026-07-11 directional-evidence recovery back-computed the directions from already-cached bars. Selection role retained.",
    demonstrates: "Sanction-channel breadth — and a measurement gap that, once repaired from cached data, resolved supporting.",
    doesNotProve: "A recovered directional read is still one event-window read at n = 1; it does not establish the sanction mechanism.",
    caveat: "Descriptive read at n = 1; directions recovered 2026-07-11 from already-cached bars.",
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
    outcome:
      "Any-supporting under the OR-rule (two of three names, ratio 0.67) once the window matured; supporting-majority under the directional-majority rule.",
    eventStudyNote: "Event-study readout available; raw market-check returns were not captured.",
    whySelected:
      "The only policy_surprise (monetary) case — a rate-sensitivity cross-section away from commodities and tariffs, selected while unresolved; the window matured to a supporting read. Selection role retained.",
    demonstrates: "Family breadth into monetary policy; an unresolved read that matured rather than staying open.",
    doesNotProve: "A two-of-three read at n = 1 is thin; it does not establish the rate-sensitivity mechanism.",
    caveat:
      "Raw market-check returns are unavailable; the event-study readout carries the quantitative read. Outcome restated 2026-07-11 after window maturation.",
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
    outcome:
      "Any-supporting under the OR-rule — both defence names agreed with the thesis (ratio 1.00) after the recovery; the directional-majority read concurs.",
    eventStudyNote: "Event-study readout available (vs SPY, n = 1).",
    whySelected:
      "The least-thin ceasefire_deescalation case — included for family breadth while its two names were untagged; the 2026-07-11 recovery resolved both supporting. Selection role retained, with the thinness stated plainly.",
    demonstrates: "Family coverage, flagged as thin rather than dressed up — the recovered read is two names, not breadth.",
    doesNotProve: "Two supporting names at n = 1 cannot establish a directional read for the family.",
    caveat:
      "Thin (two names); mechanism line is editorial; the family has only two scored events in the archive. Directions recovered 2026-07-11 from already-cached bars.",
    rawReturnsAvailable: true,
  },
];
