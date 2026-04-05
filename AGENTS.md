# AGENTS.md

## Project goal

Build and maintain a local-first research app that turns geopolitical, macro,
and policy headlines into structured event reviews. The current product path is
FastAPI plus two maintained clients: a React frontend and a Telegram bot, with
SQLite persistence, headline clustering, analysis, recent-event review, and
dated backtesting.

## Current product scope

- React app in `frontend/` served by Vite
- FastAPI backend in `api.py`
- Telegram bot in `telegram_bot.py`
- Live inbox from local JSON plus curated RSS feeds
- Progressive event analysis with stage, persistence, mechanism summary, watchlists, and streamed UI updates
- Market validation, macro context, recent events, notes, ratings, and backtest
- Local SQLite persistence plus two-layer news caching with refresh support
- Chat delivery for headline analysis plus `/brief` inbox summaries
- Lightweight eval runner for repeated sample checks

## Boundaries

- Keep the app local-first; no auth, multi-user sync, or hosted platform work unless explicitly requested
- No speculative architecture work during normal feature tasks
- No API or schema redesign unless the task actually requires it
- Keep frontend changes aligned with the existing visual system unless the task explicitly asks for redesign
- If something clearly belongs later, record it in `future_ideas.md` instead of partially building it

## Tool ownership

- `frontend/src/`: user-facing React UI, labels, empty states, loading/error copy, page-level presentation, progressive analysis states, and inbox refresh wiring
- `api.py`: FastAPI endpoints, streamed and non-streamed analysis flow, news cache bypass on refresh, and API-side orchestration
- `telegram_bot.py`: Telegram command handling, local API calls, brief delivery, and scheduled bot jobs
- `news_sources.py`: local inbox loading, RSS ingestion, normalization, relevance filtering, and clustering
- `classify.py`: deterministic stage and persistence classification
- `analyze_event.py`: mechanism extraction, ticker sanitization, mock fallback, and model configuration
- `market_check.py`: market validation, follow-up checks, and macro snapshot helpers
- `db.py`: SQLite schema, persistence, related-event lookup, and cache storage
- `main.py`: CLI helper flow for local use
- `app.py`: frozen legacy Streamlit reference; do not treat it as the maintained product surface
- `eval.py`: sample-set evaluation runner
- `README.md`, `.env.example`, `EVALUATION.md`, `future_ideas.md`: docs, setup, eval workflow, and scoped backlog

## Workflow expectations

- Prefer small, inspectable changes over broad refactors
- Preserve existing behavior unless the task explicitly asks for behavior changes
- Treat FastAPI, the React frontend, and the Telegram bot as the current maintained product surfaces
- For UI polish tasks, limit changes to copy, labels, and obvious presentation issues unless deeper work is requested
- For bot tasks, document commands and required env vars whenever setup changes
- For backend tasks, keep API, DB, and tests in sync
- Treat mock analysis output as a fallback path, not a production-quality result
- Prefer using the clustered source context already produced by the backend instead of rebuilding parallel headline logic in the UI

## Testing expectations

- Prefer built-in `unittest`
- Keep tests readable and targeted
- Use mocks instead of live network calls when practical
- Run `python -m unittest discover -s tests -v` after relevant backend or shared changes
- For frontend-only copy polish, also confirm `cd frontend && npm run dev` starts cleanly

## Code style

- Prefer plain functions and straightforward control flow
- Avoid unnecessary abstractions and classes
- Use clear names and short docstrings when helpful
- Keep files approachable for future contributors
