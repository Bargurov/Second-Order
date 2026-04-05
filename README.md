# Second Order

Second Order is a local-first research app for turning geopolitical, macro,
and policy headlines into structured event reviews. The maintained product
surface is a FastAPI backend with two current clients: a React app for rich
manual research and a Telegram bot for lightweight chat-based delivery.

It is built for manual research and demo use: ingest live headlines, review a
fused event, run progressive analysis, inspect market evidence, save the
result, backtest dated events, and optionally push brief/alert-style output
through Telegram without needing any hosted platform services.

## What The App Does

- Live inbox from `news_inbox.json` plus curated RSS sources across policy, macro, energy, trade, and geopolitics
- Headline clustering so overlapping coverage becomes one review candidate
- Source-aware inbox reviews with corroborating coverage preserved across publishers
- Stage and persistence classification
- Anthropic-backed mechanism extraction with sanitized ticker watchlists
- Progressive analysis flow that renders classify, analysis, and market stages as they complete
- Direction-aware market validation with optional event-date anchoring
- Recent events archive with notes, ratings, and related-event linking
- Backtest view for saved events with event dates
- Markdown export from the analysis view
- Macro context strip for DXY, yields, VIX, and oil
- Telegram bot for direct headline analysis plus live-inbox briefing
- Two-layer news caching: in-memory hot cache plus SQLite persistence, with manual refresh bypassing cache
- Configurable Anthropic model for app runs and evals

## Current Run Path

### 1. Backend

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m uvicorn api:app --reload
```

The API starts at `http://127.0.0.1:8000`.

### 2. React Frontend

```powershell
cd frontend
npm install
npm run dev
```

The Vite dev server runs at `http://localhost:5173` and proxies `/api/*` to
the FastAPI backend on port `8000`.

### 3. Telegram Bot

Run the bot from the repo root after the FastAPI backend is already up:

```powershell
python telegram_bot.py
```

The bot calls the local API defined by `SECOND_ORDER_API_URL` and can be run
alongside the React app or on its own.

`FastAPI + React + Telegram bot` are the current maintained product paths. The
old Streamlit app is still kept in the repo as a frozen reference and is not
the maintained surface.

## Configuration

Copy `.env.example` to `.env` and fill in only what you need:

- `ANTHROPIC_API_KEY`: optional, required for real model-backed analysis
- `ANTHROPIC_MODEL`: optional override for the default Anthropic model
- `TELEGRAM_BOT_TOKEN`: required only if you want to run `telegram_bot.py`
- `SECOND_ORDER_API_URL`: API base URL used by the Telegram bot
- `DAILY_BRIEF_ENABLED`, `DAILY_BRIEF_CHAT_ID`, `DAILY_BRIEF_TIME`: optional scheduled morning brief
- `WATCHLIST_ENABLED`, `WATCHLIST_CHAT_ID`, `WATCHLIST_INTERVAL_MIN`, `WATCHLIST_THRESHOLD_PCT`: optional scheduled watchlist alerts

If `ANTHROPIC_API_KEY` is missing, analysis falls back to a mock response for
local UI and testing flows. Mock analyses are not saved to the archive.

## Telegram Bot Setup

### Required env vars

- `TELEGRAM_BOT_TOKEN`: create this with `@BotFather`
- `SECOND_ORDER_API_URL`: usually `http://127.0.0.1:8000` for local runs

### Optional bot env vars

- `DAILY_BRIEF_ENABLED=true` plus `DAILY_BRIEF_CHAT_ID` and `DAILY_BRIEF_TIME`
- `WATCHLIST_ENABLED=true` plus `WATCHLIST_CHAT_ID`, `WATCHLIST_INTERVAL_MIN`, and `WATCHLIST_THRESHOLD_PCT`

### Local run order

1. Create and populate `.env`.
2. Start `uvicorn` from the repo root.
3. Start the React frontend from `frontend/` if you want the browser UI.
4. Start the Telegram bot with `python telegram_bot.py`.

### Bot commands

- `/start`: intro and usage hint
- `/help`: command summary and output description
- `/brief`: top clustered headlines from the live inbox
- Plain text message or forwarded headline: run the analysis pipeline and return a compact summary

## Typical Workflow

1. Start the FastAPI backend.
2. Start the React frontend and/or Telegram bot depending on the client surface you want to use.
3. Review the live inbox fed by `news_inbox.json` and curated RSS sources, then force-refresh feeds from the UI when needed.
4. Open a headline in Analysis or send a headline to the Telegram bot.
5. Run analysis with or without an event date anchor and watch the classify, analysis, and market stages fill in progressively.
6. Inspect mechanism, watchlists, macro context, and market evidence.
7. Save the result into the archive.
8. Revisit dated events in Backtest to score later market follow-through.

## Key Files

- `frontend/`: React + TypeScript app
- `api.py`: FastAPI API surface used by the frontend
- `telegram_bot.py`: Telegram delivery surface for commands, briefs, and headline analysis
- `db.py`: SQLite schema, archive persistence, and news cache helpers
- `news_sources.py`: local inbox + RSS ingestion, normalization, and clustering
- `analyze_event.py`: mechanism extraction, sanitization, and fallback behavior
- `market_check.py`: market validation, follow-up checks, and macro context
- `eval.py`: repeatable sample-set evaluation runner
- `app.py`: frozen legacy Streamlit reference kept for historical context

## Evaluation

Use the sample set in `sample_events.json` to run quick checks:

```powershell
python eval.py --preset canary
python eval.py --model claude-haiku-4-5-20251001
python eval.py --preset canary --model claude-sonnet-4-20250514
```

Each run writes a timestamped `eval_output_*.json` file for manual review.
See [EVALUATION.md](EVALUATION.md) for the current flow, including canary model
comparison guidance.

## Scope And Limits

- The app is local-first and intended for research support, not automated trading.
- Classification and mechanism extraction are still heuristic in important places.
- Market validation is supporting evidence, not proof.
- Backtest, clustering, and directional tagging are analyst-support tools, not calibrated trading signals.
- FastAPI, the React app, and the Telegram bot are the maintained product paths.
- `app.py` remains in the repo as a frozen reference, not a current workflow surface.

Future upgrades and out-of-scope ideas are tracked in
[future_ideas.md](future_ideas.md).
