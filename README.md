# Second Order

Second Order is a local-first geopolitical and macro research app. The current
product is a FastAPI backend with two maintained client surfaces:

- a React app for live inbox review, progressive analysis, archive/backtest work, and export
- a Telegram bot for direct headline analysis, `/brief`, and optional scheduled delivery

The system is designed for analyst workflows: ingest live headlines, cluster
overlapping coverage, run classify -> analysis -> market stages, layer in macro
and market-context overlays, save the result locally, and revisit dated events.

## Current Capabilities

- Live inbox from `news_inbox.json` plus curated RSS sources
- Source-preserving clustering and manual refresh via `/news/refresh`
- Progressive analysis through `/analyze/stream`
- Stage, persistence, mechanism summary, watchlists, and transmission-chain style analysis output
- Market validation plus macro and market-context overlays
- Recent events archive, related-event linking, and dated backtests
- Export of saved events as JSON or CSV via `/events/export`
- Movers and stress/context endpoints for current market state
- Telegram delivery for headline analysis and live-inbox briefing
- Layered caching:
  - news cache: in-memory hot cache + SQLite persistence
  - price/ticker cache for market data
  - optional snapshot warmer for liquid market benchmarks

## Run Locally

### 1. Backend

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m uvicorn api:app --reload
```

API base URL: `http://127.0.0.1:8000`

### 2. React Frontend

```powershell
cd frontend
npm install
npm run dev
```

Vite runs at `http://localhost:5173` and proxies `/api/*` to the backend.

### 3. Telegram Bot

From the repo root, after the backend is running:

```powershell
python telegram_bot.py
```

The bot uses `SECOND_ORDER_API_URL` to call the local FastAPI service.

## Deploy

For a minimal public API deploy on Render, use `render.yaml`.
Set `ANTHROPIC_API_KEY` only if you want real model output in the deployed app; otherwise the API still boots with mock-analysis fallback. Render injects `PORT` automatically.

## Configuration

Copy `.env.example` to `.env` for local use and keep `.env` untracked. Real current keys are:

- `ANTHROPIC_API_KEY`
- `ANTHROPIC_MODEL`
- `CORS_ALLOWED_ORIGINS`
- `TELEGRAM_BOT_TOKEN`
- `SECOND_ORDER_API_URL`
- `DAILY_BRIEF_ENABLED`
- `DAILY_BRIEF_CHAT_ID`
- `DAILY_BRIEF_TIME`
- `WATCHLIST_ENABLED`
- `WATCHLIST_CHAT_ID`
- `WATCHLIST_INTERVAL_MIN`
- `WATCHLIST_THRESHOLD_PCT`
- `MARKET_DATA_PROVIDER`
- `POLYGON_API_KEY`
- `MARKET_SNAPSHOTS_ENABLED`
- `MARKET_SNAPSHOTS_INTERVAL`

If `ANTHROPIC_API_KEY` is missing, analysis falls back to mock output for local
UI and testing flows. Mock analyses are not saved.

## Telegram Commands

- `/start`: intro and usage hint
- `/help`: command summary
- `/brief`: top clustered headlines with current market-context block
- plain text or forwarded headline: run the analysis pipeline and return a compact summary

## Typical Flow

1. Start FastAPI.
2. Start the React app and/or Telegram bot.
3. Review the inbox, refresh feeds when needed, and open a candidate event.
4. Run progressive analysis and inspect mechanism, watchlists, market validation, and macro overlays.
5. Save the event, review related follow-ups, and revisit it in Backtest later.
6. Export saved events from the archive when needed.

## Key Files

- `frontend/`: React + TypeScript app
- `api.py`: FastAPI surface and orchestration
- `telegram_bot.py`: Telegram client surface and scheduled jobs
- `news_sources.py`: inbox loading, RSS ingestion, normalization, clustering
- `db.py`: SQLite persistence and cache storage
- `market_check.py`, `market_context.py`, `market_data.py`, `price_cache.py`, `market_snapshots.py`: market validation, overlays, provider access, and warm caches
- `eval.py`: sample-set evaluation runner

## Evaluation

Quick canary run:

```powershell
python eval.py --preset canary
```

Model comparison example:

```powershell
python eval.py --preset canary --model claude-haiku-4-5-20251001
python eval.py --preset canary --model claude-sonnet-4-20250514
```

See [EVALUATION.md](EVALUATION.md) for the current eval flow and limits.

## Test

From the repo root:

```powershell
python -m unittest discover -s tests -v
```

## Scope

- Local-first research support, not automated trading
- Heuristic classification and market validation remain analyst-support tools
- FastAPI, the React app, and the Telegram bot are the maintained product paths

Later-stage work belongs in [future_ideas.md](future_ideas.md).
