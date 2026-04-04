# Future Ideas

## Purpose / How To Use This File

This file is for future ideas only. Completed work, current V1.5 tasks, and
small fixes that belong in the current code, tests, or docs do not belong
here.

## Not For V1.5

- If a feature is out of scope for the current phase, record it here instead of building it now.
- If a task belongs in V1.5, it should live in the active repo work, not in this file.
- The current V1.5 app works, but UI polish belongs to a later roadmap stage rather than the current backend-focused phase.

## Roadmap Stages

- `V1.5`: backend engine plus a basic Streamlit demo
- `V2`: news ingestion plus an inbox-style review flow
- `V2.5`: UI/UX rework and polish for demo quality
- `V3`: OpenClaw and chat-style orchestration

## V2 Priorities

1. **Event-date anchored market check**
   Tie market validation to the event date instead of only using current prices.
2. **Ticker-validity pre-check**
   Add a more durable ticker validation step before market-check downloads.
3. **Curated per-company knowledge files**
   Add small reference files for recurring companies and entities that matter to interpretation.
4. **FRED integration**
   Add macro data support for rate, inflation, and policy-sensitive event analysis.
5. **LLM-based classification**
   Replace or augment keyword classification with model-based stage/persistence classification.

## Robustness Improvements (from V1.5 audit)

1. **Retry / exponential backoff on API calls**
   `analyze_event.py` makes one attempt; a transient 500 or rate-limit error
   crashes straight to the mock fallback. Add 1-2 retries with short backoff.

2. **Graceful RSS timeout handling**
   `load_rss()` in `news_sources.py` has no per-feed timeout. A slow or hanging
   feed blocks the entire inbox refresh. Add a short timeout (e.g. 5 s).

3. **Structured error display in Streamlit**
   When the LLM returns unparseable JSON or the API key is missing, the UI
   silently shows mock data. Surface a clear warning banner so the user knows
   the result is a placeholder.

4. **`_clean_assets` edge case: non-list, non-string input**
   If the LLM returns an integer or nested object for a ticker field, the
   coercion to list currently only handles `str`. Add a broader type guard.

5. **Rate-limit awareness for yfinance**
   Rapid sequential `yfinance.download()` calls can trigger throttling. Consider
   batching tickers into a single download call where possible.