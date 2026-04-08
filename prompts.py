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
Return a single JSON object with exactly these fields:

{{
  "what_changed": "One sentence. Actor + concrete action + object + delta from baseline. No context, no backstory. Example shape: 'The US Commerce Department added 28 Chinese semiconductor companies to the Entity List.'",
  "mechanism_summary": "2-4 sentences covering THREE beats, in order: (1) the first-order disruption — what supply, demand, pricing relationship, or capital flow is directly affected; (2) who loses pricing power, market share, or access, and who gains; (3) the secondary repricing or substitution that follows. Name specific markets, products, contracts, or chokepoints. No filler adjectives. If you cannot identify this chain, write exactly: 'Insufficient evidence to identify mechanism.'",
  "beneficiaries": ["3-6 entries. Each must be a specific company, specific group (e.g. 'US Gulf Coast heavy-crude refiners'), or specific country/policy winner. Forbidden: 'various companies', 'multiple firms', 'the market', 'investors'."],
  "losers": ["3-6 entries. Same specificity rule as beneficiaries."],
  "beneficiary_tickers": ["2-4 US-listed tickers for predicted beneficiaries. HARD RULES: (a) NYSE / NASDAQ / AMEX ONLY. (b) No index symbols (VIX, DXY, SPX, RUT, MOVE). (c) No price benchmarks (TTF, JKM, NBP, HH, Brent). (d) No foreign-primary listings (.T, .L, .TO, .KS, .HK suffixes). (e) If a direct company lacks a reliable US listing, use a US-listed ETF proxy instead (SMH, XME, XLE, GLD, ITA, XAR, BDRY, FRO). (f) Each ticker must be a different company or a thematic ETF — no duplicates."],
  "loser_tickers": ["2-4 US-listed tickers for predicted losers. Same hard rules as beneficiary_tickers. If no direct loser ticker is credible, return [] — the pipeline will pick an inverse/short ETF proxy."],
  "transmission_chain": [
    "Step 1: the concrete event or policy change, restated with the actor",
    "Step 2: the transmission channel — supply disruption, pricing power shift, capital reallocation, regulatory gate, etc.",
    "Step 3: the affected market, price, contract, or physical constraint",
    "Step 4: the specific winners and losers named in beneficiaries / losers"
  ],
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
  "confidence": "low | medium | high. high ONLY when: (a) the first-order disruption is direct and named, (b) the transmission chain has no missing steps, (c) the beneficiaries and losers are concrete. low when the mechanism is speculative, missing a step, or requires a hypothetical policy response."
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
- Specificity over breadth: name companies, contracts, chokepoints, products. Never 'various', 'multiple', 'several entities', 'the market', 'investors', 'depends on outcome'.
- No hype: avoid 'surge', 'crash', 'historic', 'unprecedented', 'massive', 'significant impact'.
- No false certainty: use 'likely', 'may', 'suggests' — never 'will' or 'must'.
- If the mechanism is unclear, write 'Insufficient evidence to identify mechanism.' and set confidence to low. Do not fill space with vague analysis.
- If stage is anticipation, confidence must not exceed medium — the mechanism is conditional on an event that has not yet occurred.
- beneficiary_tickers and loser_tickers must be disjoint. A ticker must never appear in both lists.
- horizon must be exactly one of: weeks | months | quarters.
- If structured event context is provided (actors, action, geography, sector, uncertainty, consensus), use it to ground your analysis. Focus the mechanism on the named actors and sector. If uncertainty is high, reflect that in confidence. If consensus is mixed, note the disagreement rather than assuming a single narrative.
- Output exactly one JSON object and stop. Do not add commentary, do not self-correct, do not emit a second block.
"""
