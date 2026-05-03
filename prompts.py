# prompts.py
# Prompt templates for the LLM call in analyze_event.py.
# The model is instructed to return JSON only — no prose, no markdown.
# This keeps the response easy to parse with json.loads().
#
# Contract philosophy
# -------------------
# Every structured field has a specific shape AND a specific content rule.
# The prompt forces the model to commit to concrete nouns, specific
# mechanisms, and US-listed tickers.  Vague placeholders ("various",
# "multiple", "unknown impact", "depends") are explicitly forbidden so the
# downstream schema-normalization layer can rely on the model either
# committing to a real answer or returning 'Insufficient evidence ...'.

SYSTEM_PROMPT = (
    "You are a careful geopolitical and macro analyst. "
    "You identify hidden economic mechanisms and second-order market effects. "
    "You write with the discipline of an institutional desk: specific actors, "
    "named mechanisms, quantified changes when possible, and zero filler. "
    "You respond with valid JSON only — no markdown, no explanation, no extra text."
)

EVENT_ANALYSIS_PROMPT = """Event headline: "{headline}"
Stage: {stage}
Persistence: {persistence}
{event_context}
{macro_context}
Return a single JSON object with exactly these fields:

{{
  "what_changed": "One sentence. Actor + concrete action + object + delta from baseline. No context, no backstory. Example shape: 'The US Commerce Department added 28 Chinese semiconductor companies to the Entity List.'",
  "mechanism_summary": "2-4 sentences covering THREE beats, in order: (1) the PRIMARY transmission channel — commit to the single dominant channel (supply chokepoint, pricing power shift, capital flow redirection, regulatory gate, rate differential) and name it in concrete terms; (2) who loses pricing power, market share, or access, and who gains — named entities only; (3) the SECOND-ORDER repricing or substitution that follows, which must be a distinct channel from the primary one. Name specific markets, products, contracts, or chokepoints. No filler adjectives, no hedged language. If you cannot identify this chain, write exactly: 'Insufficient evidence to identify mechanism.'",
  "beneficiaries": ["3-6 entries. Each must be a specific company, specific group (e.g. 'US Gulf Coast heavy-crude refiners'), or specific country/policy winner. Forbidden: 'various companies', 'multiple firms', 'the market', 'investors'."],
  "losers": ["3-6 entries. Same specificity rule as beneficiaries."],
  "beneficiary_tickers": ["2-4 US-listed tickers for predicted beneficiaries. EXPOSURE HIERARCHY — pick in this order: (1) the DIRECT company whose revenue line is named in the mechanism; (2) a pure-play peer in the same sub-sector only if no single direct name dominates; (3) a THEMATIC ETF (SMH, XME, XLE, GLD, ITA, XAR, BDRY, FRO) ONLY when the thesis is sector-wide and no single name captures ≥40% of the upside; (4) a broad index ETF is NEVER acceptable. HARD RULES: (a) NYSE / NASDAQ / AMEX ONLY. (b) No index symbols (VIX, DXY, SPX, RUT, MOVE, SPY, QQQ, IWM). (c) No price benchmarks (TTF, JKM, NBP, HH, Brent). (d) No foreign-primary listings (.T, .L, .TO, .KS, .HK suffixes). (e) Each ticker must be a different company or a distinct thematic ETF — no duplicates. (f) If you cannot find a direct name, prefer a shorter list of 2 concrete tickers over padding with loose thematic proxies."],
  "loser_tickers": ["2-4 US-listed tickers for predicted losers. Same EXPOSURE HIERARCHY and HARD RULES as beneficiary_tickers — direct company first, pure-play peer second, thematic ETF only when diffuse. Inverse/short ETFs are a last-resort proxy; do not reach for them when a direct loser listing exists. If no direct loser ticker is credible, return []."],
  "transmission_chain": [
    "Step 1: the concrete event or policy change, restated with the named actor and the specific instrument (licence, tariff rate, rate hike magnitude, Entity List, etc.)",
    "Step 2: the PRIMARY transmission channel and the specific market / contract / chokepoint it hits — name the price, spread, or physical constraint",
    "Step 3: the equity-level winners and losers the chain resolves to, named.",
    "4 steps max. 3 is better when the chain is direct. Each step must advance the causality — no restatements, no padding. Forbidden fillers: 'the market reacts', 'investors respond', 'impacts global trade', 'ripple effects spread'."
  ],
  "transmission_path": [
    {{"hop": "Concrete action by named actor — same content as ``action`` (kept for backward compat).", "action": "Named actor performs a specific action with a specific instrument (licence, tariff rate, Entity List add, rate change). REQUIRED. No vague verbs ('markets react', 'investors price risk', 'ripple effects', 'broader market reaction', 'stakeholders respond'); the sanitizer drops hops with these.", "channel": "one of: policy_gate | supply | demand | pricing_power | capital_flow | substitution | regulatory | sanction | tariff | rate_transmission", "actor": "Named entity / firm / government body. REQUIRED. Generic actors ('the market', 'investors', 'stakeholders') are sanitizer-rejected.", "expected_market_effect": "REQUIRED. The concrete price / spread / proxy implication this hop produces — the *measurable* effect on the tape. The FINAL hop's expected_market_effect MUST name an asset or market proxy (ticker, ETF, spread, yield, credit, FX pair). Without an asset landing the chain hasn't ended in something tradable.", "timing": "OPTIONAL. one of: 1d | 1-5d | 5-20d | 20d+. The horizon over which this hop's effect should be visible on the tape."}},
    "3-4 hops total. Each hop is a dict. Order = causal order. The FIRST hop must restate the event's concrete change (actor + instrument), not a generic market reaction. The LAST hop must land at an asset / ticker / market proxy. Each hop must introduce a NEW actor or NEW channel — no repeating the same (actor, channel) pair twice. If you cannot articulate a chain that starts at the concrete change and ends at an asset implication with all required hop fields, set mechanism_summary to 'Insufficient evidence to identify mechanism.' and return an empty transmission_path — a padded chain will be rejected and the study coerced to low-information."
  ],
  "substitution_barriers": [
    {{"barrier": "Concrete reason the loser can't easily substitute away. Name a physical, legal, or commercial friction.", "kind": "one of: physical_sole_source | regulatory | capital_intensity | skill_scarcity | contractual_lockin | demand_inelastic | geographic | capacity", "severity": "low | medium | high"}},
    "2-4 entries. These are the frictions that prevent the mechanism from self-healing via substitution. If no real barrier exists, return []."
  ],
  "counterforces": [
    {{"force": "Specific force / response that could blunt or reverse the thesis — must be INVALIDATOR-GRADE: something a desk can watch for as a concrete price, policy, or filing event. Name the observable signal when possible.", "actor": "Entity that would activate the counterforce.", "likelihood": "low | medium | high", "kind": "OPTIONAL. one of: counterforce | blocker. ``counterforce`` (default) is a force that materially weakens the thesis after it transmits. ``blocker`` is a force that interrupts the transmission chain itself — pick this kind when the entry would prevent a specific transmission_path hop from playing out at all. Use the same list for both; the discipline gate reads ``kind`` to decide whether proof / falsifier coverage is required.", "chain_hop": "OPTIONAL. Free-text pointer to which transmission_path step the blocker hits — e.g. 'cuts off step 2: heavy-sour feedstock supply'. Only emit on ``kind=blocker`` entries."}},
    "Emit 1-3 ``counterforces`` (kind defaults to 'counterforce') AND 1-3 ``blockers`` (``kind: 'blocker'``) when each materially applies — the two roles are distinct: counterforces weaken, blockers interrupt. Total list capped at 6. These are not generic risks — they are concrete invalidators a reader could watch for on Bloomberg or in a filings feed. Forbidden: 'market volatility', 'market conditions', 'economic uncertainty', 'geopolitical tensions', 'broader risk-off', 'changing conditions', 'macro headwinds', 'risk factors', 'sentiment shifts'. The sanitizer drops these. If nothing credible exists, return []. The strongest high-likelihood entry SHOULD be reflected in either ``minimum_proof_set`` or ``key_falsifiers`` (mirror the same observable signal); a high-likelihood blocker without proof / falsifier coverage flips the study to watch_only."
  ],
  "adversarial_challenge": "2-3 sentences. A steel-manned counter-thesis — the strongest argument that this mechanism will NOT play out as described. Name the specific reason: thesis is already priced (cite a specific ticker move or spread level that would already reflect it), the named substitution happens faster than expected, the counterforce is larger than the mechanism, the regulatory gate gets reversed. No hedged concessions. Should elaborate the same rival reading that competing_thesis.alternative_thesis states in one line (this field is the prose, that field is the structured head-to-head). If you cannot construct a credible challenge, write exactly: 'No credible challenge identified.'",
  "monitor_plan": {{
    "first_decisive_tell": {{
      "observation": "The SINGLE earliest signal a monitoring desk should look for on the first day — not the most logically decisive one, the TEMPORALLY EARLIEST tell that moves conviction. Example: 'CVX opens on above-average volume and holds ≥+1% through the first hour.' If no early tell is specific enough, return null (not an empty string).",
      "channel": "rates | fx | commodities | vol | credit | equities",
      "what_it_means": "One sentence (≤120 chars) naming what an observation of this tell implies for the thesis direction."
    }},
    "no_call_signals": [
      {{"observation": "Observation that, if seen, would make BOTH the primary thesis and the alternative thesis inconsistent — forcing a no-call rather than picking a side.", "channel": "rates | fx | commodities | vol | credit | equities", "why_no_call": "One sentence (≤140 chars) explaining why neither reading can accommodate this observation."}},
      "0-3 entries. If you cannot think of any observation that would force abandoning BOTH readings, return [] — a padded no_call_signals is the hedge, not the analysis. This is the 'both readings are wrong' branch, distinct from critical_breakpoints (which only kills the primary)."
    ]
  }},
  "competing_thesis": {{
    "primary_thesis": "REQUIRED. The single clear primary read, written in this four-beat shape: WHAT CHANGED -> TRANSMISSION CHANNEL -> WHO BENEFITS / WHO LOSES -> WHAT CONFIRMS IT. One dense sentence; semicolons are fine. Each beat must be concrete: name the specific actor/policy/instrument, the named channel (feedstock, rate differential, regulatory gate, capacity bottleneck), the named winners and losers (companies or tickers), and a price-checkable confirmation (named market + threshold + horizon). If you cannot commit to all four beats, the thesis is too thin — return a low-information primary line and omit alternative_thesis / discriminator entirely. Example: 'US Treasury 6-month licence restores Chevron Venezuelan heavy-sour liftings; cheaper API 8-16 feedstock to Gulf Coast cokers; PBF/VLO refining margins lift while Canadian WCS sellers (SU, CNQ) lose outlet share; confirmed if WCS-WTI discount widens >=2pp within 5d.'",
    "alternative_thesis": "OPTIONAL. Emit ONLY when a materially distinct rival reading is plausible — a different mechanism that could be the right interpretation, not a reworded primary or a softer hedge. Must turn on a different channel, different winners, or a different transmission step than the primary read. If the only 'rival' is 'maybe smaller' or 'maybe slower', omit this field. FORBIDDEN: 'markets may react differently', 'outcome depends on response', 'could go either way', 'broader market reaction', 'sentiment shifts', 'risk-off', 'macro / policy / geopolitical uncertainty' — these are not alternatives, they are placeholders. The sanitizer rejects them. When present, must be the one-line summary of what adversarial_challenge elaborates. Example: 'Licence volumes fall far short of headline on PDVSA operational constraints; Gulf Coast refiner margins see minimal relief and the WCS-WTI spread barely moves.'",
    "evidence_favoring_primary": [
      {{"observation": "Concrete, price-checkable observation that supports the primary thesis.", "channel": "rates | fx | commodities | vol | credit | equities"}},
      "1-3 entries. Each observation must be specific enough that a reader can verify it on the tape or in filings."
    ],
    "evidence_favoring_alternative": [
      {{"observation": "Concrete observation that supports the alternative thesis.", "channel": "rates | fx | commodities | vol | credit | equities"}},
      "OPTIONAL. 1-3 entries. ONLY emit alongside alternative_thesis — evidence for an unstated rival is incoherent. Same specificity rule as evidence_favoring_primary."
    ],
    "discriminator": {{
      "observation": "OPTIONAL. ONLY emit when both primary_thesis AND alternative_thesis are present AND you can name a single CONCRETE observation that decisively separates them. The observation must be a named market, ticker, spread, filing, or data print — not a generic phrase. PREFER wording that mirrors an entry already in key_falsifiers or minimum_proof_set so the reader can trace the resolver back to the proof / falsifier set. A discriminator without a rival to discriminate is incoherent — omit the whole discriminator object rather than fabricate a hedge.",
      "channel": "rates | fx | commodities | vol | credit | equities",
      "outcome_if_primary": "What this observation looks like if the primary thesis is correct. Concrete direction / threshold, not a vague hedge. FORBIDDEN: 'markets react positively', 'sentiment shifts', 'outcome depends'.",
      "outcome_if_alternative": "What this observation looks like if the alternative thesis is correct. Must be SUBSTANTIVELY INCOMPATIBLE with outcome_if_primary — a reworded version of the same outcome is rejected. Same forbidden-phrase list.",
      "timing": "1d | 1-5d"
    }},
    "first_order_effect": {{
      "description": "OPTIONAL. ONE sentence naming the DIRECT market / economic impact of the event — the move that does NOT require any intermediate transmission step.  Must be concrete (named price, spread, ticker, filing, regulatory action). Vague placeholders ('markets price risk', 'investors react', 'sector benefits') are sanitizer-rejected.",
      "channel": "OPTIONAL. one of: rates | fx | commodities | vol | credit | equities — the market the direct hit lands in.",
      "expected_window": "OPTIONAL. one of: 1d | 1-5d | 5-20d | 20d+ — the horizon over which the direct impact should be visible on the tape."
    }},
    "second_order_effects": [
      {{"trigger": "REQUIRED. The first-order outcome that sets this cascade off — references the same direct move first_order_effect.description names. Must be concrete.", "intermediate_channel": "REQUIRED. The named ROUTE the cascade transmits through — a spread, contract, balance-sheet item, regulatory gate, or pricing primitive. Without an intermediate channel the entry is just a first-order claim with extra distance; the sanitizer drops entries that skip this field.", "affected_actor": "REQUIRED. Named entity / ticker / market the cascade lands on (e.g. 'CNQ', 'TLT', 'WCS-WTI spread').", "timing": "REQUIRED. one of: 1d | 1-5d | 5-20d | 20d+. The horizon over which the cascade plays out — second-order is by definition slower than first-order."}},
      "OPTIONAL. 1-3 entries. Emit ONLY when a real cascade follows the first-order move — most events have a defensible first-order read but only a fraction transmit a defensible second-order wave. If only first-order logic is defensible, return [] for second_order_effects rather than padding. If neither first-order nor second-order is defensible, the analysis is structurally too thin and is normalised to low-information by the upstream gates."
    ],
    "scenario_conditions": [
      {{"condition": "REQUIRED. The specific scenario the primary_thesis depends on — name the gating event / state concretely (e.g. 'Fed pivots to easing within 2 meetings', 'Russia accepts ceasefire terms by Q3', 'OPEC extends voluntary cut beyond June').", "why_it_matters": "REQUIRED. ONE sentence naming how the condition modifies the thesis — does it accelerate / blunt / reverse / gate the cascade? Be concrete: 'thesis only transmits if the licence is renewed', not 'depends on policy'.", "evidence_to_watch": "REQUIRED. The OBSERVABLE signal that confirms (or refutes) the condition holds — a price level, spread, data print, filing, or policy event. Mirror this signal in minimum_proof_set or key_falsifiers so the desk has a watchable item; without that mirror the tier system caps the call at watch_only."}},
      "OPTIONAL. 1-3 entries. Emit ONLY when the primary_thesis is structurally conditional on a specific scenario — most direct theses (a licence, a sanction, a single-name regulatory hit) do NOT need scenario conditions. If the thesis works regardless of regime, return [] (regime caveats live in hidden_mechanism.regime_caveats). When emitted, the proof / falsifier set must reference the named condition so the desk can watch for resolution."
    ],
    "thesis_timing": {{
      "expected_reaction_window": "OPTIONAL. one of: 1d | 1-5d | 5-20d | 20d+. The horizon over which the FIRST tradable move shows up. Anticipation events MUST NOT use 1d — the event hasn't happened yet, so reaction is at minimum 5-20d.",
      "follow_through_window": "OPTIONAL. one of: 1d | 1-5d | 5-20d | 20d+. The horizon over which the cascade / second-order wave plays out. Should be later than expected_reaction_window.",
      "stale_after": "OPTIONAL. one of: 1d | 1-5d | 5-20d | 20d+. The horizon after which the thesis loses shelf life — proof / falsifier items beyond this point are testing a different read.",
      "timing_rationale": "OPTIONAL. ≤240 chars. Brief rationale anchoring the windows to stage / persistence / family / subtype. Example: 'realized + structural + family=supply_shock'.  When omitted the finalize step infers a default rationale from those four signals.  Sanitizer-rejected when the LLM emits realized-event timing (1d reaction) on an anticipation stage."
    }}
  }},
  "mechanism_family": "Exactly one of: tariff | sanction | supply_shock | ceasefire_deescalation | policy_surprise | fiscal_issuance | labor_inflation | bank_stress | commodity_squeeze | supply_normalization | industrial_policy | regulation | external_balance | none. Pick the SINGLE archetype the event fits best — do not compound. Use 'industrial_policy' for subsidy packages / IRA / CHIPS Act / green-deal style capex mandates (not tariffs). Use 'regulation' for antitrust, merger block, capital requirement, disclosure, or company-specific regulatory action (distinct from broad policy_surprise). Use 'external_balance' for EM balance-of-payments stress, reserves drain, sovereign-credit blow-outs, capital flight. Use 'none' only if the event genuinely doesn't fit any family (rare).",
  "hidden_mechanism": {{
    "bottleneck_type": "Exactly one of: commodity_quality_mismatch | export_control_carveout | refinancing_channel | shipping_chokepoint | input_cost_passthrough | reserve_bop_stress | capacity_bottleneck | substitution_constraint | regulatory_gate | sole_source_physical | none. Pick the SINGLE market-structure primitive the mechanism turns on — the specific chokepoint the thesis is betting exists. Use 'none' only if the event genuinely has no identifiable bottleneck (rare; default to the closest match).",
    "transmission_type": "Exactly one of: physical_flow | pricing_power | regulatory_gate | financing | balance_sheet | substitution | passthrough | none. The MECHANICAL mode the shock travels through — barrels moving (physical_flow), contract re-pricing (pricing_power), a licence/tariff acting as a valve (regulatory_gate), a rate/credit channel (financing), reserves/solvency (balance_sheet), alt-supplier activation (substitution), input-cost-to-margin (passthrough). Pick the dominant mode, not all that apply.",
    "channel_domain": "Exactly one of: regulatory | financing | supply_chain | demand | macro_rates | currency | labor | infrastructure | none. The market-structure domain that carries the shock. Should be consistent with transmission_type — e.g. regulatory_gate → regulatory, financing → financing, physical_flow → supply_chain or infrastructure.",
    "forensic_note": "One sentence (≤140 chars) naming the specific chokepoint / carveout / capacity constraint that makes this event tradable. No generalities. Example: 'Gulf Coast coking refineries are configured for heavy-sour API 8-16 crude; light-sweet is not a 1:1 substitute.' If no forensic detail, write exactly: 'No specific bottleneck identified.'",
    "asset_rationales": {{
      "TICKER": "One concrete line explaining why THIS specific ticker is the right exposure for THIS mechanism — not a generic sector sentence. Reference the bottleneck or the specific revenue line the mechanism hits. Example: 'Direct liftings from Venezuelan heavy-sour crude — the feedstock Gulf Coast coking refineries are built to run.' Keys are the tickers you've already listed in beneficiary_tickers / loser_tickers; omit tickers you have nothing concrete to say about rather than padding with generic lines."
    }},
    "minimum_proof_set": [
      {{"observation": "Concrete, price-checkable signal that MUST appear for the thesis to be real.", "channel": "rates | fx | commodities | vol | credit | equities", "threshold": "Numeric bar the observation must clear (e.g. 'WCS-WTI discount widens ≥2pp').", "timing": "1d | 1-5d | 5-20d | 20d+"}},
      "2-4 entries. This is the MUST-SEE subset of horizon_checkpoints.confirms_if — if ANY single entry fails to appear, the thesis is not verified. If you cannot name a genuine minimum, return [] — an empty minimum_proof_set is better than a padded one."
    ],
    "optional_confirming_evidence": [
      {{"observation": "Additional signal that would strengthen conviction if observed, but whose absence does NOT break the thesis.", "channel": "rates | fx | commodities | vol | credit | equities"}},
      "0-3 entries. Nice-to-haves only. Do not repeat entries from minimum_proof_set."
    ],
    "critical_breakpoints": [
      {{"signal": "Concrete signal that, if observed within 5 days, would break the thesis fast.", "channel": "rates | fx | commodities | vol | credit | equities", "threshold": "Numeric bar the signal must clear to trigger the breakpoint (e.g. 'oil reverses >50% of headline move intraday').", "timing": "1d | 1-5d"}},
      "1-3 entries. FAST falsifiers only — timing must be 1d or 1-5d. Slower falsifiers belong in horizon_checkpoints.falsifies_if. An empty list is acceptable when no fast-break signal exists."
    ],
    "regime_dependency": "One sentence (≤140 chars) naming the macro regime the thesis REQUIRES to play out — the condition that, if it flips, the mechanism no longer transmits. Example: 'Requires tight credit conditions — HY spreads above 450bp for margin-stress pass-through to hold.' If the thesis is regime-independent, write exactly: 'Regime-independent.'",
    "substitution_escape_path": "One sentence (≤140 chars) describing the narrow route by which the affected entity could ESCAPE the mechanism (and thereby break the thesis). Example: 'Russia reroutes crude to Indian refiners at a small discount — Western sanctions bypassed via third-country intermediation.' If no escape path exists, write exactly: 'No credible escape path.'",
    "regime_caveats": [
      {{"condition": "REQUIRED. The specific regime state the thesis depends on — name the macro condition concretely (e.g. 'inflation print >0.4% MoM core', 'real yields above 1.8% on the 5y', 'HY spreads above 450bp', 'DXY above 105', 'O/N reverse-repo facility above $1.5T').", "effect_on_thesis": "REQUIRED. How this condition modifies the read — name the directional impact ('amplified', 'compressed', 'blunts the cascade', 'reverses the spread move'). Use weakening verbs ('weakens', 'blunts', 'reverses', 'stalls', 'fades', 'breaks the chain') when the regime flip would materially weaken the thesis — the tier system reads this to cap the call at watch_only.", "evidence_to_revisit": "REQUIRED. The OBSERVABLE change that would force a re-read — a price level, spread move, data print, or filing event a desk can watch on Bloomberg. Example: 'real yields drop >20bp within 5d', 'HY spreads tighten below 380bp', 'core CPI prints below 0.3% MoM'.", "domain": "OPTIONAL. one of: inflation | rates | credit | fx | liquidity. The macro regime this caveat conditions the thesis on; the sanitizer drops the field on unknown values."}},
      "OPTIONAL. 1-3 entries. Emit ONLY when the regime materially conditions the read — most events with self-contained mechanisms (a specific licence, a sanction, a single-ticker thesis) do NOT require regime caveats. If the thesis is regime-independent, return [] (and use the existing ``regime_dependency`` field to say so). Vague placeholders ('general macro conditions', 'broader market conditions', 'macro uncertainty', 'sentiment shifts') are sanitizer-rejected."
    ],
    "source_quality": {{
      "source_type": "OPTIONAL. one of: official_release | policy_action | data_print | reported_disruption | analyst_view | secondhand | rumor | speculation. Use ``official_release`` for press releases / formal statements; ``policy_action`` for executive orders / signed bills / FOMC moves; ``data_print`` for CPI / NFP / earnings prints; ``reported_disruption`` for confirmed outages / strikes / shutdowns; ``analyst_view`` for sell-side notes; ``secondhand`` for press wire repackaging; ``rumor`` / ``speculation`` for unconfirmed reports.",
      "specificity": "OPTIONAL. one of: low | medium | high. ``high`` for official releases / concrete policy actions / actual disruptions / numerical prints (the headline names a specific actor, instrument, and timing). ``low`` for rumors / 'considering' / 'reportedly' / anonymous-sourced reports. ``medium`` is the analyst-view / secondhand midpoint. Low-specificity headlines CANNOT ship as actionable; the tier system caps them at watch_only.",
      "uncertainty_level": "OPTIONAL. one of: low | medium | high. The inverse of specificity — high uncertainty means the headline is hedged or speculative.",
      "evidence_limitations": "OPTIONAL. ≤240 chars. Brief description of what's missing from the report — no concrete actor, no instrument, no timing, secondhand sourcing, etc.  Empty string when the report is clean."
    }}
  }},
  "expected_first_order_channels": ["2-4 entries from: rates | fx | commodities | vol | credit | equities. The channels that should move FIRST given this family and event specifics.  These are what a desk watches for the immediate reaction."],
  "expected_second_order_channels": ["1-3 entries from the same 6-channel set. The cascade / follow-through channels that should move after the first-order reprice.  These are the 5d-20d follow-through channels."],
  "regime_conditioned_caveat": "1-2 sentences. Given the CURRENT macro regime (from the provided backdrop if present), what would blunt or redirect the family's usual playbook?  Examples: 'policy surprise in a hawkish regime — the initial repricing is amplified because front-end rates are already restrictive'; 'supply shock but credit is already tightening — margin pressure on consumer discretionary likely outweighs the producer windfall'.  If no backdrop or no conditioning factor applies, write exactly: 'No regime-conditioned caveat.'",
  "horizon_checkpoints": {{
    "timing_profile": "fast_shock | delayed_pass_through | slow_grind | unknown",
    "horizons": [
      {{"horizon": "1d",  "expected": ["Immediate intraday moves — name a concrete ticker / spread / market AND a signed direction or magnitude range. Each bullet must reference a named market."], "confirms_if": ["Specific price-checkable observation with a named market and threshold (e.g. 'LRCX closes down ≥3% on above-average volume'). A Bloomberg reader must be able to verify each bullet in one lookup."], "falsifies_if": ["Specific price-checkable counter-observation with a named market and threshold that CANNOT coexist with the thesis. Must be mirror-concrete to confirms_if, not a softer hedge."]}},
      {{"horizon": "5d",  "expected": ["5-day follow-through moves — name spreads, sector-relative pair trades, or volume patterns with concrete tickers."], "confirms_if": ["5-day confirmation — at minimum direction from 1d holds; ideally a named spread move with a numeric threshold (e.g. 'WCS-WTI discount widens ≥2pp')."], "falsifies_if": ["5-day falsification — a specific named price, spread, or estimate that would indicate the thesis is fading. No hedged wording."]}},
      {{"horizon": "20d", "expected": ["20-day structural follow-through — earnings revisions, inventory data, contract flows, filings. Reference the data source (sell-side consensus, monthly imports, guidance call, shipping trackers)."], "confirms_if": ["20-day confirmation — ideally a structural signal (earnings guide language, inventory print, contract award) rather than just price action. Name the filing or data release."], "falsifies_if": ["20-day falsification — a specific structural signal (guidance minimisation, carve-out, data print) that would prove the thesis wrong on a month-scale horizon."]}}
    ]
  }},
  "if_persists": {{
    "substitution": "One sentence. Concrete substitution, workaround, or reallocation that becomes economic if this condition holds for months. Name the substitute. Write null ONLY if no credible substitution exists.",
    "delayed_winners": ["Entities that benefit only after a lag — new entrants, alternative suppliers, re-tooled producers. Omit the key if none."],
    "delayed_losers": ["Entities that suffer compounding damage — debt-laden firms, single-source buyers, stranded assets. Omit the key if none."],
    "horizon": "weeks | months | quarters — rough time frame for second-round effects. Must be exactly one of these three words."
  }},
  "currency_channel": {{
    "pair": "The most relevant FX pair or dollar proxy (e.g. 'DXY', 'USD/JPY', 'EUR/USD', 'USD/CNY'). Must be a concrete pair. Return null ONLY if no credible FX channel exists.",
    "mechanism": "One sentence: how this event transmits through the currency channel (rate differential, safe-haven flow, commodity-linked currency, sovereign credit). Must be specific. null ONLY if no credible FX channel.",
    "beneficiaries": "One sentence naming who benefits from the FX move. null if none.",
    "squeezed": "One sentence naming who gets squeezed by the FX move. null if none."
  }},
  "confidence": "low | medium | high. high ONLY when: (a) the first-order disruption is direct and named, (b) the transmission chain has no missing steps, (c) the beneficiaries and losers are concrete. low when the mechanism is speculative, missing a step, or requires a hypothetical policy response.",
  "primary_assets": [
    {{"symbol": "US-listed ticker, already in beneficiary_tickers or loser_tickers", "rank": 1, "rationale": "One concrete line (≤140 chars) naming why this is the FIRST asset to move. Reference the specific revenue line, bottleneck, or spread the thesis hits. Not a generic sector sentence."}},
    "0-4 entries, strictly ranked 1..N by expected reaction timing and magnitude. The top-ranked asset is the single best direct proxy for the mechanism. If you cannot identify even one concrete primary asset, return exactly the string \"insufficient_evidence\" (not an empty list — the empty list means 'no primary exposure beyond beneficiaries/losers')."
  ],
  "secondary_assets": [
    {{"symbol": "US-listed ticker", "rank": 1, "rationale": "One concrete line naming the follow-through exposure and why it lags primary."}},
    "0-4 entries. SECOND-ORDER exposures that move AFTER primary — credit on a rate shock, shipping on a commodity shock, sector-rotation names on an industrial-policy shock. Ranked by expected follow-through timing. Use \"insufficient_evidence\" when no credible second-order names exist."
  ],
  "hedge_or_signal_assets": [
    {{"symbol": "FX / vol / inverse-ETF / broad-index proxy", "rank": 1, "rationale": "One concrete line explaining whether this is a HEDGE (offsets thesis risk) or a SIGNAL (confirms tape read) and which."}},
    "0-3 entries. Explicitly the non-direct exposures: DXY / UUP for dollar signal, VIX / VXX for vol, TLT for duration, inverse-ETFs when a direct short is unavailable. These do NOT get added to beneficiary_tickers — they are watch-or-hedge instruments. Use \"insufficient_evidence\" when no hedge/signal proxy is relevant."
  ],
  "key_falsifiers": [
    "2-5 entries. FLAT list of strings. Each string is a single specific, price-checkable observation that would falsify the primary thesis. Must name a ticker, spread, filing, or numeric threshold. Different from hidden_mechanism.critical_breakpoints (that list carries timing/channel dicts); this is the LLM's bluntest 'what would kill this read' list for consumers that don't read the nested structure. Use [] when no falsifier is concrete enough to list — do NOT invent one."
  ],
  "minimum_proof_set": [
    {{"observation": "Concrete observation — specific ticker, spread, volume print, or filing", "channel": "rates | fx | commodities | vol | credit | equities", "threshold": "Numeric bar the observation must clear", "timing": "1d | 1-5d | 5-20d | 20d+"}},
    "2-5 entries. The must-see signals at the TOP LEVEL of the schema so consumers that don't read hidden_mechanism still get the confirmation set. Distinct from hidden_mechanism.minimum_proof_set — that one is gated to asset_rationales tickers; this top-level one can reference any observable. If ANY single entry fails, the thesis is not verified. Use [] when no genuine minimum exists."
  ]
}}

Example (do not copy these values — use them as a quality benchmark):

Headline: "US Treasury issues licence allowing Chevron to resume crude liftings from Venezuela for six months"
Stage: realized
Persistence: medium

{{
  "what_changed": "The US Treasury granted Chevron a specific six-month licence to resume crude oil liftings from its PDVSA joint ventures in Venezuela.",
  "mechanism_summary": "Venezuelan extra-heavy crude (API 8-16 degrees) is a refinery-specific feedstock: only Gulf Coast coking refineries configured for heavy sour barrels can run it economically. Restoring Chevron's liftings lowers the marginal input cost for those refiners while leaving light-crude peers unaffected. Canadian heavy crude producers (WCS sellers) lose a portion of their premium US Gulf Coast outlet to a lower-cost competitor, widening the WCS-WTI discount.",
  "beneficiaries": ["Chevron (direct equity upside, restored production volumes)", "US Gulf Coast heavy-crude refiners (PBF, VLO, PSX — lower feedstock cost)", "Gulf Coast coking specialists with multi-year Venezuelan feedstock contracts"],
  "losers": ["Canadian oil-sands producers selling WCS (displaced by Venezuelan barrels)", "US LNG exporters if Venezuelan gas volumes return and divert domestic demand", "Colombian heavy-crude exporters losing US Gulf routes"],
  "beneficiary_tickers": ["CVX", "PBF", "VLO"],
  "loser_tickers": ["SU", "CNQ"],
  "transmission_chain": [
    "US Treasury grants Chevron a 6-month licence for Venezuelan crude liftings",
    "Restores supply of heavy sour crude to Gulf Coast coking refineries",
    "Lowers marginal feedstock cost for configured heavy-crude refiners and widens the WCS-WTI spread",
    "Chevron and Gulf Coast refiners benefit; Canadian WCS sellers lose outlet share"
  ],
  "transmission_path": [
    {{"hop": "US Treasury issues 6-month licence for Venezuelan crude liftings.", "action": "US Treasury issues 6-month licence for Venezuelan crude liftings.", "channel": "sanction", "actor": "US Treasury OFAC", "expected_market_effect": "Brent-WTI light-heavy diff narrows on incremental heavy-sour supply expectation.", "timing": "1d"}},
    {{"hop": "Chevron resumes direct equity-and-lift arrangement with PDVSA joint ventures.", "action": "Chevron resumes direct equity-and-lift arrangement with PDVSA joint ventures.", "channel": "supply", "actor": "Chevron", "expected_market_effect": "CVX equity prices in restored production volumes; first cargoes appear in vessel-tracking data.", "timing": "1-5d"}},
    {{"hop": "Heavy-sour feedstock supply to Gulf Coast coking refineries increases; WCS-WTI spread widens.", "action": "Heavy-sour feedstock supply to Gulf Coast coking refineries increases; WCS-WTI spread widens.", "channel": "pricing_power", "actor": "US Gulf Coast refiners", "expected_market_effect": "WCS-WTI discount widens >=2pp; PBF / VLO refining-margin spreads expand vs peers.", "timing": "5-20d"}},
    {{"hop": "Canadian WCS sellers (SU, CNQ) lose US Gulf outlet share at the marginal barrel.", "action": "Canadian WCS sellers (SU, CNQ) lose US Gulf outlet share at the marginal barrel.", "channel": "substitution", "actor": "Canadian oil-sands producers", "expected_market_effect": "SU and CNQ equities underperform energy peers as Canadian heavy-crude differential widens.", "timing": "5-20d"}}
  ],
  "substitution_barriers": [
    {{"barrier": "Gulf Coast coking refineries are physically configured for heavy sour barrels; light-sweet crude is not a 1:1 substitute.", "kind": "physical_sole_source", "severity": "high"}},
    {{"barrier": "Canadian WCS rail and pipeline capacity is contracted months in advance; refiners cannot pivot suppliers instantly.", "kind": "contractual_lockin", "severity": "medium"}}
  ],
  "counterforces": [
    {{"force": "Congressional opposition could pressure Treasury to narrow or revoke the licence before its 6-month window.", "actor": "US Congress Republicans", "likelihood": "medium"}},
    {{"force": "Venezuelan production ramp faces infrastructure constraints — delivered barrels may fall short of licence volume.", "actor": "PDVSA operational capacity", "likelihood": "high"}}
  ],
  "adversarial_challenge": "The Venezuelan barrel ramp may disappoint — PDVSA's infrastructure is badly degraded and past licensing regimes have delivered well below headline volumes. If deliveries are modest, Gulf Coast refiner feedstock relief is marginal and the WCS-WTI spread barely widens, leaving the thesis priced for a supply response that never materializes.",
  "monitor_plan": {{
    "first_decisive_tell": {{
      "observation": "CVX opens on above-average volume and closes the first session ≥+1%",
      "channel": "equities",
      "what_it_means": "Desk is pricing the licence at face value — thesis has momentum going into the 5d window."
    }},
    "no_call_signals": [
      {{"observation": "Global crude rallies broadly across light-sweet and heavy-sour", "channel": "commodities", "why_no_call": "A macro-wide commodity rally means neither the Venezuelan supply thesis nor the disappointment thesis explain the tape — dollar or risk-on is driving."}}
    ]
  }},
  "competing_thesis": {{
    "primary_thesis": "US Treasury 6-month licence restores Chevron's Venezuelan heavy-sour liftings; cheaper API 8-16 feedstock reaches Gulf Coast cokers; PBF and VLO refining margins lift while Canadian WCS sellers (SU, CNQ) lose outlet share; confirmed if WCS-WTI discount widens >=2pp within 5 trading days.",
    "alternative_thesis": "Delivered Venezuelan volumes fall well short of licence headline on PDVSA infrastructure constraints, and the WCS-WTI spread barely moves.",
    "evidence_favoring_primary": [
      {{"observation": "Chevron-branded cargoes loading at Jose within the first week", "channel": "commodities"}},
      {{"observation": "WCS-WTI discount widens ≥2pp within 5-20d", "channel": "commodities"}}
    ],
    "evidence_favoring_alternative": [
      {{"observation": "PDVSA issues operational-delay statement within the first week", "channel": "commodities"}},
      {{"observation": "Chevron reports delivered volumes <50kbd in monthly filings", "channel": "equities"}}
    ],
    "discriminator": {{
      "observation": "Total Venezuelan crude exports in monthly vessel-tracking data",
      "channel": "commodities",
      "outcome_if_primary": "Vessel data confirms ≥50kbd of new Chevron-branded flow within 5 trading days",
      "outcome_if_alternative": "Vessel data shows zero new loadings or volumes well below 50kbd within 5 trading days",
      "timing": "1-5d"
    }}
  }},
  "mechanism_family": "supply_normalization",
  "hidden_mechanism": {{
    "bottleneck_type": "commodity_quality_mismatch",
    "transmission_type": "physical_flow",
    "channel_domain": "supply_chain",
    "forensic_note": "Gulf Coast coking refineries are configured for heavy-sour API 8-16 barrels; light-sweet crude is not a 1:1 substitute at the margin.",
    "asset_rationales": {{
      "CVX": "Direct licence holder — equity upside tracks restored Venezuelan lift volumes.",
      "PBF": "Gulf Coast pure-play refiner with the highest heavy-sour coker configuration share.",
      "VLO": "Largest US Gulf heavy-sour refiner by capacity — marginal feedstock cost drops directly.",
      "SU":  "Canadian oil-sands producer losing US Gulf outlet share at the marginal barrel.",
      "CNQ": "Canadian WCS seller exposed to the same displacement and widening discount."
    }},
    "minimum_proof_set": [
      {{"observation": "WCS-WTI discount widens as physical liftings ramp", "channel": "commodities", "threshold": "≥2pp widening vs pre-licence baseline", "timing": "5-20d"}},
      {{"observation": "Chevron-branded cargoes tracked leaving Jose terminal", "channel": "commodities", "threshold": "≥1 new loading observed in shipping trackers", "timing": "1-5d"}}
    ],
    "optional_confirming_evidence": [
      {{"observation": "Gulf Coast refining credit spreads tighten", "channel": "credit"}},
      {{"observation": "Canadian energy CAD-denominated equities underperform", "channel": "equities"}}
    ],
    "critical_breakpoints": [
      {{"signal": "PDVSA issues operational-delay statement", "channel": "commodities", "threshold": "any public loading-volume shortfall within 5d", "timing": "1-5d"}},
      {{"signal": "Congressional resolution narrows or revokes the licence", "channel": "equities", "threshold": "CVX drops below pre-announcement level", "timing": "1-5d"}}
    ],
    "regime_dependency": "Regime-independent — a bilateral licence doesn't require a specific macro regime to transmit.",
    "substitution_escape_path": "Canadian WCS sellers find alternative outlets via expanded rail to Midwest or TMX export capacity."
  }},
  "expected_first_order_channels": ["commodities", "equities"],
  "expected_second_order_channels": ["fx", "credit"],
  "regime_conditioned_caveat": "In a supply-normalization regime with credit spreads tight, the Canadian WCS-WTI widening will show up more in refinery-margin equities than in CAD — FX has less room to extend when risk appetite is already priced in.",
  "horizon_checkpoints": {{
    "timing_profile": "delayed_pass_through",
    "horizons": [
      {{"horizon": "1d",  "expected": ["CVX +1-2% intraday on headline lift", "PBF / VLO refining spread names +1-2%", "WCS-WTI discount largely unchanged (physical flow lag)"], "confirms_if": ["CVX closes green on above-average volume", "Gulf Coast refining credit spreads tighten"], "falsifies_if": ["CVX closes flat-to-down while SU / CNQ rally", "Crude benchmark rallies broadly — suggests market is not pricing licensed barrels specifically"]}},
      {{"horizon": "5d",  "expected": ["WCS-WTI discount widens by 2-4 pp as physical liftings ramp", "Gulf Coast refiner spreads hold vs peers", "Venezuelan loading schedules published in shipping trackers"], "confirms_if": ["First Chevron-branded cargoes tracked leaving Jose terminal", "Canadian heavy-crude differentials widen vs Midwest outlets"], "falsifies_if": ["PDVSA issues operational-delay statement", "Shipping data shows no new Chevron loadings after 5 trading days"]}},
      {{"horizon": "20d", "expected": ["WCS-WTI discount holds wider than pre-licence baseline", "Chevron reports higher Venezuelan lift volumes in monthly filings", "Gulf Coast coker spreads stay above peer refiners"], "confirms_if": ["Monthly crude import data confirms ≥50kbd Venezuelan inflow to US Gulf", "SU / CNQ quarterly guidance flags Canadian crude pricing pressure"], "falsifies_if": ["Venezuelan loading volumes fall short of 50kbd", "Congressional resolution passes narrowing the licence"]}}
    ]
  }},
  "if_persists": {{
    "substitution": "If Venezuelan barrels keep flowing, Gulf Coast refiners may re-tool maintenance schedules around heavy-sour supply and cut long-term Canadian WCS contracts.",
    "delayed_winners": ["Venezuelan oilfield service providers", "Gulf Coast coking refiners locked into long-term feedstock contracts"],
    "delayed_losers": ["Canadian oil-sands producers facing sustained WCS discount", "Colombian heavy-crude exporters displaced from US Gulf routes"],
    "horizon": "months"
  }},
  "currency_channel": {{
    "pair": "USD/CAD",
    "mechanism": "A widening WCS-WTI discount pressures Canadian energy export receipts and slightly weakens CAD relative to USD on a trade-balance basis.",
    "beneficiaries": "US refiners importing Canadian crude (slightly cheaper CAD inputs)",
    "squeezed": "Canadian oil-sands producers facing lower USD-equivalent receipts"
  }},
  "confidence": "medium"
}}

Second example (non-energy sector — use the same quality benchmark):

Headline: "US Commerce Department adds 28 Chinese semiconductor firms to export control list"
Stage: realized
Persistence: structural

{{
  "what_changed": "The US Commerce Department added 28 Chinese semiconductor companies to the Entity List, restricting their access to US-origin chip fabrication equipment and EDA software.",
  "mechanism_summary": "Chinese fabs lose access to ASML EUV lithography tools, Lam Research etch systems, and Applied Materials deposition equipment — all three hold near-monopoly positions in their segments. Affected Chinese firms must seek inferior domestic alternatives or halt expansion. US and allied equipment makers lose near-term China revenue but benefit from accelerated re-investment by TSMC, Samsung, and Intel racing to fill the capacity gap.",
  "beneficiaries": ["TSMC (capacity scarcity increases pricing power)", "ASML (accelerated orders from non-Chinese fabs)", "Samsung Foundry (market share gain at leading nodes)"],
  "losers": ["Chinese DRAM/NAND foundries (CXMT, YMTC)", "Lam Research and Applied Materials (lost China revenue near-term)", "Fabless Chinese chip designers without access to leading nodes"],
  "beneficiary_tickers": ["TSM", "ASML", "SMH"],
  "loser_tickers": ["LRCX", "AMAT"],
  "transmission_chain": [
    "28 Chinese semiconductor firms added to the Entity List",
    "Cuts access to EUV lithography, etch, and deposition equipment",
    "Chinese fab expansion stalls; non-Chinese fabs gain pricing power at leading nodes",
    "TSMC / ASML benefit from capacity scarcity; LRCX / AMAT lose China revenue"
  ],
  "transmission_path": [
    {{"hop": "US Commerce Department adds 28 Chinese fabs / designers to the Entity List.", "action": "US Commerce Department adds 28 Chinese fabs / designers to the Entity List.", "channel": "policy_gate", "actor": "US Commerce Dept BIS", "expected_market_effect": "Chinese semi equities and US chip-equipment names gap on the headline; SMH dispersion widens intraday.", "timing": "1d"}},
    {{"hop": "Chinese fabs lose EUV / advanced etch / deposition equipment imports.", "action": "Chinese fabs lose EUV / advanced etch / deposition equipment imports.", "channel": "supply", "actor": "ASML, LRCX, AMAT export restrictions", "expected_market_effect": "LRCX and AMAT close down >=3% on revenue-hit framing; Chinese fab capex guidance cut.", "timing": "1d"}},
    {{"hop": "Non-Chinese leading-node capacity becomes scarcer; pricing power shifts to TSMC / Samsung / Intel.", "action": "Non-Chinese leading-node capacity becomes scarcer; pricing power shifts to TSMC / Samsung / Intel.", "channel": "pricing_power", "actor": "TSMC, Samsung Foundry", "expected_market_effect": "TSM outperforms SMH by >=1pp; leading-node foundry premium expands in the equities tape.", "timing": "1-5d"}},
    {{"hop": "LRCX / AMAT lose near-term China revenue; SMH ETF performance tracks the net.", "action": "LRCX / AMAT lose near-term China revenue; SMH ETF performance tracks the net.", "channel": "demand", "actor": "US equipment makers", "expected_market_effect": "Sell-side cuts LRCX / AMAT revenue estimates >=3%; SMH breadth narrows behind leading-node names.", "timing": "5-20d"}}
  ],
  "substitution_barriers": [
    {{"barrier": "EUV lithography is sole-sourced from ASML; no domestic Chinese equivalent at 7nm or below.", "kind": "physical_sole_source", "severity": "high"}},
    {{"barrier": "Domestic Chinese DUV substitutes require 3-5x more process steps and still cap out well short of leading-node density.", "kind": "capital_intensity", "severity": "high"}},
    {{"barrier": "Process engineers qualified on leading-edge tools are a global scarcity; China cannot hire them at pace.", "kind": "skill_scarcity", "severity": "medium"}}
  ],
  "counterforces": [
    {{"force": "PRC subsidies accelerate indigenous equipment development at NAURA and AMEC, partially closing the gap over 2-3 years.", "actor": "PRC government / industrial policy", "likelihood": "medium"}},
    {{"force": "US equipment makers lobby for narrower Entity List carve-outs to preserve mature-node China revenue.", "actor": "US chip equipment industry", "likelihood": "medium"}}
  ],
  "adversarial_challenge": "The controls may already be priced — SMH has rallied on prior rounds of export restrictions and the TSMC scarcity premium is embedded. If Chinese indigenous substitutes (NAURA, AMEC) progress faster than consensus or the Entity List gets narrowed under industry lobbying, the capacity-scarcity thesis weakens and the equipment-maker revenue hit shows up immediately without the offsetting capex upcycle.",
  "monitor_plan": {{
    "first_decisive_tell": {{
      "observation": "LRCX and AMAT open ≥3% down on above-average volume",
      "channel": "equities",
      "what_it_means": "Desk is pricing the Entity List revenue hit immediately — primary thesis has early conviction."
    }},
    "no_call_signals": [
      {{"observation": "SMH rallies broadly while LRCX / AMAT close up on the day", "channel": "equities", "why_no_call": "Neither the controls-bite thesis nor the already-priced thesis can explain a broad semi rally on an Entity List day — something else (broad risk-on, AI capex headline) is driving."}}
    ]
  }},
  "competing_thesis": {{
    "primary_thesis": "BIS adds 28 Chinese fabs to the Entity List, gating EUV / etch / deposition equipment exports; non-Chinese leading-node capacity (TSM, Samsung) gains scarcity premium while LRCX and AMAT lose near-term China revenue; confirmed if TSM outperforms SMH by >=1pp on the announcement day.",
    "alternative_thesis": "Restrictions are already priced in prior rounds; revenue hit lands without the TSMC scarcity premium extending further.",
    "evidence_favoring_primary": [
      {{"observation": "LRCX / AMAT down ≥3% on the day with above-average volume", "channel": "equities"}},
      {{"observation": "TSM outperforms SMH by ≥2pp over 5d", "channel": "equities"}}
    ],
    "evidence_favoring_alternative": [
      {{"observation": "LRCX / AMAT close flat-to-green on carve-out rumours", "channel": "equities"}},
      {{"observation": "TSM underperforms SMH over 5d", "channel": "equities"}}
    ],
    "discriminator": {{
      "observation": "TSM relative performance vs SMH on the announcement day",
      "channel": "equities",
      "outcome_if_primary": "TSM outperforms SMH by ≥1pp intraday on scarcity-premium repricing",
      "outcome_if_alternative": "TSM underperforms SMH intraday — signals the scarcity premium is already in",
      "timing": "1d"
    }}
  }},
  "mechanism_family": "sanction",
  "hidden_mechanism": {{
    "bottleneck_type": "sole_source_physical",
    "transmission_type": "regulatory_gate",
    "channel_domain": "regulatory",
    "forensic_note": "ASML EUV lithography is sole-sourced; no domestic Chinese equivalent exists at 7nm or below.",
    "asset_rationales": {{
      "TSM":  "Non-Chinese leading-node capacity gains scarcity premium on Chinese fab exclusion.",
      "ASML": "Sole-source EUV provider — accelerated non-China orders offset lost China revenue.",
      "LRCX": "Etch-equipment revenue to Chinese fabs is the specific line the Entity List gates.",
      "AMAT": "Deposition-equipment exposure to the same 28 named Chinese fabs."
    }},
    "minimum_proof_set": [
      {{"observation": "LRCX / AMAT sell-side estimate revisions", "channel": "equities", "threshold": "≥3% revenue estimate cuts", "timing": "1-5d"}},
      {{"observation": "TSM relative outperformance vs SMH", "channel": "equities", "threshold": "≥2pp 5d alpha", "timing": "1-5d"}}
    ],
    "optional_confirming_evidence": [
      {{"observation": "ASML non-China booking step-up", "channel": "equities"}},
      {{"observation": "Chinese IG credit spreads widen", "channel": "credit"}}
    ],
    "critical_breakpoints": [
      {{"signal": "Commerce Dept issues broad carve-out rumours", "channel": "equities", "threshold": "LRCX / AMAT recover to pre-announcement level intraday", "timing": "1d"}},
      {{"signal": "TSM underperforms SMH on the announcement day", "channel": "equities", "threshold": "TSM <SMH on 1d return", "timing": "1d"}}
    ],
    "regime_dependency": "Stronger in a hawkish-rates regime — long-duration semi multiples are already compressed so the revenue hit reprices faster.",
    "substitution_escape_path": "PRC subsidies accelerate NAURA / AMEC indigenous equipment to partial leading-node capability within 2-3 years."
  }},
  "expected_first_order_channels": ["equities", "fx"],
  "expected_second_order_channels": ["credit", "commodities"],
  "regime_conditioned_caveat": "In a hawkish-rates regime the equipment-maker revenue hit reprices faster than usual because long-duration semi multiples were already compressed; credit widening for Chinese IG issuers amplifies the non-equity leg of the transmission.",
  "horizon_checkpoints": {{
    "timing_profile": "fast_shock",
    "horizons": [
      {{"horizon": "1d",  "expected": ["LRCX and AMAT down 3-5% intraday on revenue-hit framing", "TSM +1-2% on capacity-scarcity read", "SMH close mixed — ETF dampens dispersion"], "confirms_if": ["LRCX / AMAT lead semi losers on the day", "TSM relative outperformance vs SMH is visible"], "falsifies_if": ["LRCX / AMAT close green on Commerce Dept carve-out rumors", "TSM underperforms SMH — suggests scarcity premium isn't being priced"]}},
      {{"horizon": "5d",  "expected": ["LRCX / AMAT sell-side estimate revisions appear", "ASML holds relative strength vs LRCX / AMAT", "SMH breadth narrows as leading-node names outperform"], "confirms_if": ["Analysts cut LRCX / AMAT revenue estimates by ≥3%", "TSM 5d return beats SMH by ≥2pp"], "falsifies_if": ["No sell-side estimate cuts after 5 days", "LRCX / AMAT recover to pre-announcement levels — signals effective lobbying"]}},
      {{"horizon": "20d", "expected": ["LRCX / AMAT quarterly guide flags explicit China revenue impact", "NAURA / AMEC Shanghai listings rally on indigenous-substitute narrative", "ASML order book update confirms accelerated non-China demand"], "confirms_if": ["Company guidance calls name 28 Entity List firms as ≥5% revenue headwind", "Non-China ASML bookings step up visibly"], "falsifies_if": ["Guidance calls minimize the Entity List hit", "Commerce Dept issues broad carve-outs within 20 days"]}}
    ]
  }},
  "if_persists": {{
    "substitution": "Chinese fabs may accelerate indigenous DUV-based multi-patterning lines, trading throughput for self-sufficiency.",
    "delayed_winners": ["Domestic Chinese equipment makers (NAURA, AMEC)", "TSMC's Arizona fab (US onshoring demand)"],
    "delayed_losers": ["LRCX and AMAT (permanent China revenue loss)", "Fabless Chinese chip designers unable to access cutting-edge nodes"],
    "horizon": "quarters"
  }},
  "currency_channel": {{
    "pair": null,
    "mechanism": null,
    "beneficiaries": null,
    "squeezed": null
  }},
  "confidence": "high"
}}

Rules:
- Specificity over breadth: name companies, contracts, chokepoints, products. Forbidden vague tokens: 'various', 'multiple', 'several entities', 'the market', 'investors', 'depends on outcome', 'broadly', 'widely', 'potentially', 'may impact', 'could affect', 'in general', 'across the board', 'stakeholders', 'players'.
- No hype: avoid 'surge', 'crash', 'historic', 'unprecedented', 'massive', 'significant impact', 'game-changer', 'pivotal', 'landmark', 'dramatic'.
- No false certainty: use 'likely', 'may', 'suggests' — never 'will' or 'must'.
- Institutional voice: write as a desk note would. Commit to a direction and a magnitude band when possible. No rhetorical questions, no first-person, no moral framing, no commentary about the geopolitical situation beyond the market mechanism.
- PRIMARY-vs-SECOND-ORDER discipline: expected_first_order_channels and expected_second_order_channels must be DISJOINT when the family has a distinct wave. A channel that appears in both lists is a sign the analysis has not separated the initial repricing from the follow-through — pick the stronger one.
- Direct exposure: when a thesis names a specific company, that company's US listing must appear in beneficiary_tickers or loser_tickers before any thematic ETF. Thematic ETFs are a fallback for diffuse theses, not a default.
- Confirming markets: every horizon's confirms_if entry must reference a NAMED market (ticker, spread, or data print) and a threshold. 'Market rallies' is not acceptable; 'CVX closes green on above-average volume' is. falsifies_if must be mirror-concrete, not a softer version of confirms_if.
- Invalidators must be price-checkable or filings-checkable: every counterforce and adversarial_challenge claim must point to something a desk can observe. Abstract risks ('policy uncertainty', 'macro headwinds') are not invalidators.
- If the mechanism is unclear, write 'Insufficient evidence to identify mechanism.' and set confidence to low. Do not fill space with vague analysis.
- The mechanism quality gate requires the analysis to name FIVE elements collectively: (1) the trigger (a concrete change in ``what_changed``), (2) the transmission channel (a canonical channel in ``transmission_path`` or ``expected_first_order_channels``), (3) the affected constraint or pricing relationship (a named spread / discount / margin / yield / capacity / chokepoint / feedstock / quota / sole-source primitive in ``mechanism_summary`` or via ``substitution_barriers`` / ``hidden_mechanism.bottleneck_type``), (4) at least one affected actor (a named beneficiary or loser entity), (5) an expected market expression (a tickerable instrument in beneficiary_tickers / loser_tickers / assets_to_watch, or an asset/proxy in the last transmission hop's ``expected_market_effect``). Studies missing any of the five are coerced to low-information.
- Forbidden vague mechanism phrasings — these are gate-rejected: 'markets price risk', 'investors react' / 'investors reposition' / 'investors reprice', 'sector benefits', 'uncertainty rises', 'market sentiment shifts', 'broader market reaction', 'macro headwinds', 'risk appetite shifts'. Use named actors, named channels, and named constraints instead.
- competing_thesis.primary_thesis must be CONSISTENT with the accepted mechanism — its actors / winners / losers / channel must overlap with what mechanism_summary, what_changed, transmission_path, and beneficiaries / losers describe. A primary_thesis that names a winner the mechanism never reaches is a self-contradiction and the study is coerced to low-information.
- If stage is anticipation, confidence must not exceed medium — the mechanism is conditional on an event that has not yet occurred.
- beneficiary_tickers and loser_tickers must be disjoint. A ticker must never appear in both lists.
- horizon must be exactly one of: weeks | months | quarters.
- If structured event context is provided (actors, action, geography, sector, uncertainty, consensus), use it to ground your analysis. Focus the mechanism on the named actors and sector. If uncertainty is high, reflect that in confidence. If consensus is mixed, note the disagreement rather than assuming a single narrative.
- If a macro backdrop is provided, use it to calibrate mechanism direction and conviction. A risk-off regime with elevated VIX and rising real yields compresses growth-sensitive outcomes; a risk-on regime with falling rates expands them. Reflect regime conditions in the confidence level and mechanism specificity — do not ignore the macro context.
- transmission_path.channel must be one of the enum values listed in the schema. Do not invent new channel names. Each hop must name the actor — no abstract agents.
- transmission_path.channel tokens MUST match the committed mechanism_family. The allowed channel set per family: tariff → tariff / supply / demand / pricing_power / substitution / regulatory; sanction → sanction / supply / regulatory / policy_gate / capital_flow / substitution / pricing_power; supply_shock → supply / pricing_power / substitution / demand; ceasefire_deescalation → supply / demand / capital_flow / regulatory / policy_gate; policy_surprise → policy_gate / rate_transmission / capital_flow / regulatory; fiscal_issuance → capital_flow / rate_transmission / demand / policy_gate; labor_inflation → demand / pricing_power / rate_transmission; bank_stress → capital_flow / rate_transmission / regulatory / pricing_power; commodity_squeeze → supply / pricing_power / substitution / demand; supply_normalization → supply / pricing_power / substitution / sanction / regulatory / policy_gate; industrial_policy → regulatory / supply / demand / capital_flow / policy_gate / substitution; regulation → regulatory / policy_gate / pricing_power; external_balance → capital_flow / rate_transmission / regulatory / pricing_power. A chain whose hops mostly fall outside the family's set is sanitiser-flagged: the call is downgraded to watch_only or low-information depending on the share. Generic hops like 'risk sentiment' are off-family for every canonical family and will be rejected.
- transmission_path hops must each carry actor + action (or hop) + channel + expected_market_effect; timing is optional but must be one of 1d / 1-5d / 5-20d / 20d+ when present. Vague hops are sanitizer-rejected: 'markets react', 'investors price risk', 'investors respond', 'ripple effects', 'broader market reaction', 'stakeholders respond', 'sentiment shifts'.
- The FIRST transmission_path hop must restate the event's concrete change (the same actor + instrument as ``what_changed``). The LAST hop must land at an asset, ticker, ETF, spread, yield, credit, or FX proxy — its expected_market_effect must reference one. A chain that ends at a generic narrative is rejected and the study coerced to low-information.
- primary_thesis must be DERIVABLE from the transmission_path: the named winners / losers, channel, and confirming proxy in primary_thesis must match the actors and expected_market_effects walked through the chain. A primary_thesis that names a winner the chain never reaches is a self-contradiction.
- substitution_barriers.kind must be one of the listed kinds. Severity must be low | medium | high. An empty list is an acceptable answer when the loser genuinely has easy substitutes.
- counterforces must name a SPECIFIC actor and a CONCRETE force that could be watched for in price, filings, or policy feeds. Do not list 'risk factors', 'uncertainty', 'market conditions', 'geopolitical tensions', or 'macro headwinds'. An empty list is acceptable.
- The ``counterforces`` list carries two roles distinguished by an optional ``kind`` field. ``kind: 'counterforce'`` (default) is a force that materially weakens the thesis after the chain has transmitted; ``kind: 'blocker'`` is a force that interrupts the transmission chain itself, with an optional ``chain_hop`` pointer naming which transmission_path step it hits. Emit 1-3 of each role when both materially apply. A high-likelihood blocker (``likelihood: 'high'``, ``kind: 'blocker'``) MUST be addressed in ``minimum_proof_set`` or ``key_falsifiers`` — the same observable signal must appear in at least one proof / falsifier item. Without that coverage the thesis is structurally untestable and the study is coerced to watch_only or low-information.
- adversarial_challenge must attack the thesis with a falsifiable claim, not hedge it. Write the strongest possible counter-argument a competent desk would raise, and cite at least one specific ticker, spread, or filing that would reveal the challenge is playing out. Use the placeholder only when the mechanism is so direct that no credible counter exists.
- competing_thesis.primary_thesis is REQUIRED whenever the analysis carries a thesis at all. It must follow the four-beat shape: WHAT CHANGED -> TRANSMISSION CHANNEL -> WHO BENEFITS / WHO LOSES -> WHAT CONFIRMS IT. Each beat is concrete: named actor + instrument, named channel, named winners and losers (companies or tickers), price-checkable confirmation (named market + threshold + horizon). If you cannot commit to all four beats, the thesis is too thin — emit a low-information primary_thesis ('Insufficient evidence to commit to a primary read.') and OMIT alternative_thesis / discriminator entirely rather than blend partial mechanisms.
- competing_thesis.alternative_thesis is OPTIONAL. Emit ONLY when a materially distinct rival reading is plausible — different channel, different winners, or different transmission step. A softer-magnitude version of the primary read is NOT an alternative; omit the field. Generic placeholders are forbidden and will be sanitizer-rejected: 'markets may react differently', 'outcome depends on response', 'could go either way', 'broader market reaction', 'sentiment shifts', 'risk-off', 'macro / policy / geopolitical uncertainty'. When present, must be the one-line summary of what adversarial_challenge elaborates — they read as a pair, not two independent rivals.
- competing_thesis.evidence_favoring_primary must contain 1-3 concrete, price-checkable observations whenever primary_thesis is emitted. evidence_favoring_alternative is OPTIONAL and must ONLY be emitted alongside alternative_thesis — evidence for an unstated rival is incoherent. Each observation must name a specific market, ticker, or filing a reader can verify — not a hedge like "sentiment shifts" or "risk-on trade".
- competing_thesis.discriminator is OPTIONAL. Emit ONLY when both primary_thesis AND alternative_thesis are present AND you can name a single CONCRETE observation that decisively separates them. The observation must reference a named market, ticker, spread, or filing — vague observations are sanitizer-rejected. PREFER mirroring an entry already in key_falsifiers or minimum_proof_set so the discriminator wording links back to the proof / falsifier set. outcome_if_primary and outcome_if_alternative must be substantively incompatible — both cannot be true, and a reworded version of the same outcome is rejected. If you cannot name such an observation, OMIT the discriminator object; keep alternative_thesis if a real rival exists, but never fabricate a resolver. Timing restricted to 1d or 1-5d. A rival thesis without a discriminator is acceptable; a discriminator without a rival is not.
- competing_thesis.first_order_effect / second_order_effects separate the DIRECT market move (no intermediate transmission needed) from the CASCADE that requires a named transmission step. ``first_order_effect`` is OPTIONAL but when emitted MUST carry a concrete description (vague verbs like 'markets price risk', 'investors react' are sanitizer-rejected). ``second_order_effects`` is OPTIONAL and each entry MUST carry trigger + intermediate_channel + affected_actor + timing — entries that SKIP intermediate_channel are dropped because a cascade without a named route is just a relabelled first-order claim. Emit only what is defensible: keep ``second_order_effects`` empty when only first-order logic holds. When neither first-order nor second-order is defensible, the upstream gates (causal_strength, mechanism_quality) coerce the study to low-information.
- beneficiaries / losers and the corresponding ticker lists must be reached by the named primary_thesis transmission channel. Drop generic adjacent-sector names that don't follow from the chosen mechanism — a padded list of loosely related sector winners dilutes the read. If a candidate winner/loser cannot be tied to the specific channel named in primary_thesis, omit it.
- monitor_plan.first_decisive_tell is the TEMPORALLY EARLIEST conviction-mover — what a desk watches at the open, not the most logically decisive signal. Must be observable within the first trading session. Distinct from competing_thesis.discriminator (which can be a 5d data release). Return null when no first-day tell is specific enough.
- monitor_plan.no_call_signals is the "both readings are wrong" branch — signals that would force abandoning BOTH the primary and the alternative thesis, not just one. Distinct from competing_thesis.evidence_favoring_alternative (which boosts the rival) and critical_breakpoints (which breaks the primary). If you cannot name a both-inconsistent observation, return [] — a padded list is the hedge.
- transmission_chain: maximum 4 steps; 3 is preferred. Each step must advance causality — restatements, rhetorical flourishes, or 'the market reacts' filler are forbidden.
- transmission_path: each hop must introduce a new (actor, channel) pair. Do not repeat the same actor on consecutive hops unless the channel genuinely changes.
- mechanism_family must be EXACTLY ONE of the listed families. Do not compound (no "tariff/sanction", no "supply_shock+commodity_squeeze").  Pick the closest single archetype — the pipeline uses it to pull the canonical cross-asset channel pack.
- hidden_mechanism.bottleneck_type, .transmission_type, .channel_domain must each be EXACTLY ONE of the listed enum values — do not invent new values, do not compound with slashes or pipes. These three fields must be internally consistent: regulatory_gate transmission belongs with the regulatory domain, financing belongs with financing, physical_flow belongs with supply_chain or infrastructure.
- hidden_mechanism.forensic_note must name the SPECIFIC chokepoint / capacity constraint / carveout, not a generic market observation. "Sole-sourced from ASML" is forensic; "high-tech sector under pressure" is not. ≤140 chars.
- hidden_mechanism.asset_rationales keys must be tickers you've already put in beneficiary_tickers or loser_tickers. Do NOT introduce new tickers here — this is the "why this asset" layer, not a place to extend the universe. Omit tickers you have nothing concrete to say about; do not fill with generic one-liners.
- hidden_mechanism.minimum_proof_set is the MUST-SEE subset of horizon_checkpoints.confirms_if — 2-4 entries max. If any single entry fails to appear, the thesis is unverified. Do NOT repeat all confirms_if here; pick only the genuinely minimal set. Empty list beats a padded one.
- hidden_mechanism.optional_confirming_evidence is 0-3 entries of nice-to-haves that strengthen conviction. Do not duplicate minimum_proof_set entries here.
- hidden_mechanism.critical_breakpoints must have timing of 1d or 1-5d ONLY — these are FAST falsifiers. Slower falsifiers belong in horizon_checkpoints.falsifies_if, not here. 1-3 entries; [] is acceptable when no fast-break signal exists.
- hidden_mechanism.regime_dependency names the regime the thesis requires (≤140 chars). Must be distinct from regime_conditioned_caveat, which explains how the current regime modulates the default playbook. The dependency is what the thesis NEEDS; the caveat is what the regime DOES.
- hidden_mechanism.regime_caveats is OPTIONAL. Emit 1-3 entries ONLY when the thesis depends materially on inflation, rates, credit, FX, or liquidity conditions — most self-contained event theses (a specific licence, a sanction, a single-name regulatory action) do NOT need regime caveats. Each entry MUST carry: ``condition`` (the specific regime state, named with a price level / spread / data print), ``effect_on_thesis`` (the directional impact — use weakening verbs like 'weakens', 'blunts', 'reverses', 'stalls', 'fades', 'breaks the chain' when the regime flip would materially weaken the read; the tier system reads this to cap the call at watch_only), and ``evidence_to_revisit`` (the observable change a desk would watch on Bloomberg). Optional ``domain`` enum: inflation | rates | credit | fx | liquidity. Generic placeholders ('general macro conditions', 'broader market conditions', 'macro uncertainty', 'sentiment shifts') are sanitizer-rejected.
- hidden_mechanism.substitution_escape_path is the narrow escape route — the inverse of substitution_barriers. A barrier says why escape is hard; the escape path names the one route that remains. Use "No credible escape path." when the barriers genuinely close every door.
- expected_first_order_channels and expected_second_order_channels must be subsets of {{rates, fx, commodities, vol, credit, equities}}.  No other tokens allowed.  First-order = the channel(s) that should move today-to-tomorrow; second-order = 5d-20d follow-through.  Leave a list empty only when the family genuinely has no distinct wave.
- regime_conditioned_caveat should explicitly reference the current regime when a macro backdrop is provided.  Do not write a generic risk disclaimer — write the ONE concrete way this regime changes the default playbook.  Use the placeholder only when no macro backdrop is supplied.
- horizon_checkpoints.timing_profile must be exactly one of: fast_shock | delayed_pass_through | slow_grind | unknown. Pick fast_shock when the first tradable moves appear within 1d (geopolitical break, policy announcement with immediate pricing); delayed_pass_through when 1d is quiet but 5-20d shows material re-pricing (tariff-to-margin lag, supply-chain reroute); slow_grind when the mechanism builds over 20d+ (structural shift, contract rollover, balance-sheet transmission); unknown only if you genuinely cannot commit.
- horizon_checkpoints.horizons must include entries for 1d, 5d, AND 20d. Each horizon's expected / confirms_if / falsifies_if lists must name specific, checkable observations — not generic adjectives. "Crude +3-5% intraday" is acceptable; "markets react" is not. confirms_if and falsifies_if must be mirror-concrete — a reader with a Bloomberg should be able to verify each bullet without interpretation. Empty lists are allowed when a horizon genuinely has no distinct check, but avoid emptying all three horizons unless the thesis is speculative.
- primary_assets / secondary_assets / hedge_or_signal_assets are RANKED lists. Each entry must have {{symbol, rank, rationale}} with rank a strictly increasing integer starting at 1. Do not emit two entries with the same rank. Do not pad — fewer, better entries always beat a padded list. Each rationale must be specific (≤140 chars), naming the revenue line / spread / bottleneck the mechanism actually hits for that ticker; generic sector sentences are rejected by the sanitizer.
- "insufficient_evidence" is a valid answer for primary_assets, secondary_assets, and hedge_or_signal_assets. Emit the literal string "insufficient_evidence" (not the empty list) when you genuinely cannot name a specific exposure with a concrete rationale. An empty list means "no exposure beyond beneficiary/loser tickers"; the string means "the thesis is too thin to rank exposures at all." The two are semantically distinct.
- primary_assets symbols SHOULD overlap with beneficiary_tickers / loser_tickers — primary_assets is the ranked re-read of the committed universe, not a parallel universe. hedge_or_signal_assets is the ONLY bucket where new symbols are normal (DXY / VIX / TLT / inverse ETFs never belong in beneficiary_tickers).
- key_falsifiers is the FLAT top-level list a quick read consumer sees. minimum_proof_set is the FLAT top-level must-see list. Both mirror the nested hidden_mechanism.critical_breakpoints / hidden_mechanism.minimum_proof_set fields in spirit but are independently consumable — do not leave them empty by pointing the reader to the nested block.
- Output exactly one JSON object and stop. Do not add commentary, do not self-correct, do not emit a second block.
"""
