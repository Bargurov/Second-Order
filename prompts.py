# prompts.py
# Prompt templates for the LLM call in analyze_event.py.
# The model is instructed to return JSON only — no prose, no markdown.
# This keeps the response easy to parse with json.loads().

SYSTEM_PROMPT = (
    "You are a careful geopolitical and macro analyst. "
    "You identify hidden economic mechanisms and second-order market effects. "
    "You respond with valid JSON only — no markdown, no explanation, no extra text."
)

EVENT_ANALYSIS_PROMPT = """Event headline: "{headline}"
Stage: {stage}
Persistence: {persistence}
{event_context}
Return a single JSON object with exactly these fields:

{{
  "what_changed": "One sentence. The concrete policy, action, or shift — not context or background.",
  "mechanism_summary": "2-3 sentences. Name the specific market, price relationship, or capital flow this event disrupts. Who loses supply or pricing power? What substitution or repricing follows? If you cannot identify a clear mechanism, write exactly: 'Insufficient evidence to identify mechanism.'",
  "beneficiaries": ["Specific companies, countries, or ETFs — not broad sectors. E.g. 'US LNG exporters', 'TSMC', 'Saudi Aramco'"],
  "losers": ["Same standard. E.g. 'European auto OEMs dependent on Russian palladium', 'Chinese DRAM foundries'"],
  "beneficiary_tickers": ["2-3 US-listed tickers for predicted beneficiaries. NYSE or NASDAQ only. No index symbols (VIX, DXY), no price benchmarks (TTF, JKM, NBP), no foreign-listed single stocks (.T, .L, .TO suffixes). Use a US-listed ETF proxy if needed (e.g. SMH, XME, XLE, GLD)."],
  "loser_tickers": ["2-3 US-listed tickers for predicted losers. Same rules as beneficiary_tickers."],
  "transmission_chain": [
    "Step 1: the concrete event or policy change",
    "Step 2: the transmission channel (e.g. supply disruption, pricing power shift, capital reallocation)",
    "Step 3: the affected market, price, or constraint",
    "Step 4: who wins and who loses"
  ],
  "confidence": "low | medium | high — high only if the causal chain is direct and specific; low if speculative or if mechanism is unclear"
}}

Example (do not copy these values — use them as a quality benchmark):

Headline: "US Treasury issues licence allowing Chevron to resume crude liftings from Venezuela for six months"
Stage: realized
Persistence: medium

{{
  "what_changed": "The US Treasury granted Chevron a specific six-month licence to resume crude oil liftings from its PDVSA joint ventures in Venezuela.",
  "mechanism_summary": "Venezuelan extra-heavy crude (API 8–16°) is a refinery-specific feedstock: only Gulf Coast coking refineries configured for heavy sour barrels can run it economically. Restoring Chevron's liftings lowers the marginal input cost for those refiners while leaving light-crude peers unaffected. Canadian heavy crude producers (WCS sellers) lose a portion of their premium US Gulf Coast outlet to a lower-cost competitor.",
  "beneficiaries": ["Chevron (direct equity upside, restored production volumes)", "US Gulf Coast heavy-crude refiners (PBF, VLO, PSX — lower feedstock cost)"],
  "losers": ["Canadian oil-sands producers selling WCS (displaced by Venezuelan barrels)", "US LNG exporters if Venezuelan gas volumes return and divert domestic demand"],
  "beneficiary_tickers": ["CVX", "PBF", "VLO"],
  "loser_tickers": ["SU", "CNQ"],
  "transmission_chain": [
    "US Treasury grants Chevron a 6-month licence for Venezuelan crude liftings",
    "Restores supply of heavy sour crude to Gulf Coast coking refineries",
    "Lowers marginal feedstock cost for configured heavy-crude refiners",
    "Chevron and Gulf Coast refiners benefit; Canadian WCS sellers lose outlet share"
  ],
  "confidence": "medium"
}}

Second example (non-energy sector — use the same quality benchmark):

Headline: "US Commerce Department adds 28 Chinese semiconductor firms to export control list"
Stage: realized
Persistence: structural

{{
  "what_changed": "The US Commerce Department added 28 Chinese semiconductor companies to the Entity List, restricting their access to US-origin chip fabrication equipment and EDA software.",
  "mechanism_summary": "Chinese fabs lose access to ASML EUV lithography tools, Lam Research etch systems, and Applied Materials deposition equipment — all three hold near-monopoly positions in their segments. Affected Chinese firms must seek inferior domestic alternatives or halt expansion. US/allied equipment makers lose revenue from China orders but benefit from accelerated investment by non-Chinese fabs (TSMC, Samsung, Intel) racing to fill the capacity gap.",
  "beneficiaries": ["TSMC (capacity scarcity increases pricing power)", "ASML (accelerated orders from non-Chinese fabs)", "US defense semiconductor supply chain"],
  "losers": ["Chinese DRAM/NAND foundries (CXMT, YMTC)", "Lam Research and Applied Materials (lost China revenue near-term)"],
  "beneficiary_tickers": ["TSM", "ASML", "SMH"],
  "loser_tickers": ["LRCX", "AMAT"],
  "transmission_chain": [
    "28 Chinese semiconductor firms added to Entity List",
    "Cuts access to EUV lithography, etch, and deposition equipment",
    "Chinese fab expansion stalls; non-Chinese fabs gain pricing power",
    "TSMC/ASML benefit from capacity scarcity; LRCX/AMAT lose China revenue"
  ],
  "confidence": "high"
}}

Rules:
- No hype: avoid 'surge', 'crash', 'historic', 'unprecedented', 'massive', 'significant impact'.
- No false certainty: use 'likely', 'may', 'suggests' — never 'will' or 'must'.
- If the mechanism is unclear, write 'Insufficient evidence to identify mechanism.' and set confidence to low. Do not fill space with vague analysis.
- If stage is anticipation, confidence must not exceed medium — the mechanism is conditional on an event that has not yet occurred.
- If structured event context is provided (actors, action, geography, sector, uncertainty, consensus), use it to ground your analysis. Focus the mechanism on the named actors and sector. If uncertainty is high, reflect that in confidence. If consensus is mixed, note the disagreement rather than assuming a single narrative.
- Output exactly one JSON object and stop. Do not add commentary, do not self-correct, do not emit a second block.
"""