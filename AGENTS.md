# AGENTS.md

## Project goal

Build and maintain Second Order as a local-first research product for
geopolitical, macro, and policy headlines. The current maintained workflow is
FastAPI plus two clients: the React app and the Telegram bot.

## Current product scope

- React app in `frontend/`
- FastAPI backend in `api.py`
- Telegram bot in `telegram_bot.py`
- Live clustered inbox from local JSON plus curated RSS feeds
- Progressive analysis (`/analyze` + `/analyze/stream`)
- Market validation, macro overlays, market-context flow, movers, archive, backtest, and export
- SQLite persistence plus cache layers for news and market data
- Evaluation runner in `eval.py`

## Boundaries

- Keep the app local-first unless the task explicitly requests hosted/platform work
- Do not treat `app.py` as a maintained product surface
- Avoid speculative architecture work during normal tasks
- Do not redesign APIs, schemas, or UI structure unless the task requires it
- If work clearly belongs later, record it in `future_ideas.md` instead of partially building it

## File ownership

- `frontend/src/`: React UI, page presentation, labels/copy, loading/error states, and client-side flow
- `api.py`: FastAPI routes, streaming analysis, export, market-context endpoints, movers endpoints, cache bypass on refresh
- `telegram_bot.py`: Telegram commands, bot-side delivery flow, `/brief`, and scheduled jobs
- `news_sources.py`, `news_cluster_store.py`: headline ingestion, normalization, clustering, and persisted news cache
- `classify.py`: deterministic stage/persistence classification
- `analyze_event.py`, `prompts.py`: model prompt flow, mechanism extraction, sanitization, fallback behavior
- `market_check.py`, `market_context.py`, `market_data.py`, `market_snapshots.py`, `price_cache.py`, `movers_cache.py`: market validation, overlays, provider access, warm caches, and movers support
- `db.py`, `events_export.py`: archive schema, persistence, related events, and export helpers
- `eval.py`, `EVALUATION.md`: sample-set eval flow and review guidance
- `README.md`, `.env.example`, `.gitignore`, `future_ideas.md`: setup, config, hygiene, and scoped backlog

## Workflow expectations

- Prefer small, inspectable changes over broad refactors
- Preserve current behavior unless the task explicitly asks for a behavior change
- Keep docs/config aligned with the real maintained product path
- For bot or API setup changes, update `README.md`, `.env.example`, and `requirements.txt` in the same pass when dependencies or config keys change
- For backend/shared changes, keep tests in sync
- For frontend polish tasks, stay within presentation and UX unless deeper product work is requested

## Testing expectations

- Prefer built-in `unittest`
- Keep tests targeted and readable
- Use mocks instead of live network calls when practical
- When setup or dependency files change, verify `python -m pip install -r requirements.txt` still reflects the real imports used by the app/tests
- Run `python -m unittest discover -s tests -v` after backend or shared changes
- For frontend-only work, also confirm `cd frontend && npm run dev` starts cleanly when feasible

## Code style

- Prefer plain functions and straightforward control flow
- Avoid unnecessary abstractions and classes
- Use clear names and short docstrings where they help
- Keep files approachable for future contributors
