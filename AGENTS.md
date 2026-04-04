# AGENTS.md

## Project goal

Build a small command-line workflow that turns a pasted geopolitical or macro
headline into a first-pass event record by classifying it, extracting a
provisional mechanism, running a lightweight market check, and saving the
result locally.

## V1 scope

- Accept one pasted headline at a time
- Classify `stage` with simple keyword logic
- Classify `persistence` with simple keyword logic
- Produce a provisional mechanism summary and asset watchlist
- Run a lightweight market-validation step
- Save results to a local database

## Boundaries

- No OpenClaw yet
- No RAG yet
- No dashboards yet
- No frontend code
- If something belongs in V2/V3, write it in `future_ideas.md` instead of building it now

## File responsibilities

- `main.py`: command-line entry point and workflow orchestration
- `analyze_event.py`: mechanism extraction and fallback behavior
- `market_check.py`: lightweight market-validation logic
- `db.py`: local SQLite setup, save, and load helpers
- `prompts.py`: prompt text for future model calls
- `future_ideas.md`: parking lot for anything outside V1
- `README.md`: setup and usage instructions
- `AGENTS.md`: project rules for contributors
- `tests/test_classification.py`: smoke tests for stage and persistence classification
- `tests/test_db.py`: smoke tests for database init/save/load flow
- `tests/test_market_check.py`: smoke tests for market-check behavior

## Testing expectations

- Keep smoke tests small, readable, and easy to run
- Prefer built-in `unittest`
- Use mocks instead of real network calls when practical
- Run `python -m unittest discover -s tests -v` after relevant changes

## Beginner-friendly code

- Prefer plain functions and straightforward control flow
- Avoid unnecessary abstractions and classes
- Use clear names and short docstrings when helpful
- Keep changes small and easy to inspect
