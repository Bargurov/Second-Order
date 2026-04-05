# Future Ideas

Use this file only for real later-stage work. If something belongs in the
current app, tests, or docs, it should be fixed in the repo instead of parked
here.

## V3 Later

1. WhatsApp and OpenClaw delivery surfaces once the Telegram path is fully settled.
2. Richer alerting beyond threshold pings, including more contextual watchlist move summaries.
3. Daily brief evolution toward cleaner morning synthesis, stronger ranking, and better recurring delivery controls.

## Analytical Depth Features

### V2.5/V3 candidates

1. Transmission Chain Visualization
   Parse the mechanism into a visual flow diagram (`event → channel → channel → ticker`). The data already exists in `mechanism_summary`, and this can become a signature demo feature.
2. Substitution & Second-Round Effects
   Add an "If This Persists" prompt enhancement so the LLM surfaces substitution effects at 6+ months. This should highlight elasticity and long-run versus short-run dynamics.
3. Real Yield & Breakeven Inflation Context
   Add TIPS yield and breakeven inflation to the macro strip, then flag cases where an analysis claims an event is inflationary but breakevens have not moved. This helps demonstrate nominal versus real-rate awareness.
4. Currency Transmission Channel
   Show the most relevant currency pair for each event, such as `USD/RUB` for energy shocks, `USD/CNY` for trade-war pressure, or local FX versus `DXY` for EM stress. This connects FX, commodities, and equities more explicitly.

### V3 candidates

5. Monetary Policy Sensitivity Overlay
   Flag when an event's mechanism reinforces or conflicts with the current Fed direction, such as fiscal stimulus landing into a hawkish backdrop and creating a headwind warning.
6. Inventory & Supply Chain Position
   Surface relevant inventory levels such as EIA gas storage, crude inventories, or LME copper stock so supply events can be judged against actual buffer conditions.

### Post-V3 / requires archive depth

7. Cross-Event Correlation Map
   Detect when two active Market Movers share affected tickers or sectors and flag compounding effects. This becomes much more useful once the archive has deeper event history.
8. Contagion Risk Indicator
   Show adjacent sectors or regions at risk of spillover and map them to watchlist ETFs such as `EUFN`, `EZU`, and `EMB`. This is best after the OpenClaw delivery layer exists.
9. Suppress noisy Yahoo Finance warnings
   yfinance prints "possibly delisted" and "Failed downloads" to stderr for tickers that are valid but have no data for the requested date range. These are non-fatal and clutter the server log. Options: redirect yfinance logging to a file, filter known-harmless patterns, or switch to a proper market data provider (Polygon/Tiingo) that returns structured errors.
