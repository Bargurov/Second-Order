# Geo Mechanism Project

Geo Mechanism Project is a small local research workflow for turning a headline
into a structured event review. It classifies the event, extracts a provisional
economic mechanism, proposes beneficiary and loser tickers, and checks whether
market moves provide directional evidence rather than proof.

The current V1.5 implementation includes both a command-line flow and a small
Streamlit UI. It supports optional event dates for anchored market validation,
stores reviewed events in SQLite, and keeps evaluation cheap through canary
runs while reserving full evals for milestone checks. The current app works,
but the UI is still intentionally rough and closer to a basic demo than a
polished product experience.

## Quick Start

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python main.py
python eval.py --preset canary
streamlit run app.py
```

If `ANTHROPIC_API_KEY` is not set, the analysis step falls back to a mock
response instead of failing.

## Example Workflow

1. Paste a headline into `main.py` or the Streamlit app.
2. Classify the event stage and persistence.
3. Extract a provisional mechanism summary plus beneficiary and loser tickers.
4. Run direction-aware market validation on those tickers using either current-price mode or an optional event-date anchored mode.
5. Save the event record to SQLite in `events.db` and review recent saved events from the Streamlit UI if needed.

## Architecture

- `app.py`: Streamlit UI with optional event date input and a recent-events view
- `main.py`: CLI entry point and workflow orchestration
- `classify.py`: stage and persistence classification helpers
- `analyze_event.py`: mechanism extraction, ticker sanitization, and fallback behavior
- `market_check.py`: direction-aware market validation for beneficiary and loser tickers, in current-price or event-date anchored mode
- `db.py`: local SQLite setup and persistence helpers for schema version 3, including `event_date` and `market_tickers`
- `eval.py`: sample-set evaluation runner with canary, `--ids`, and `--limit` options
- `sample_events.json`: reusable evaluation headlines with expected labels

## Limitations

- Classification remains heuristic unless a model-based upgrade is added later.
- Market validation is still lightweight and should be treated as supporting evidence, not proof.
- The mechanism step is provisional and may return simplified reasoning.
- The project is intentionally small and does not yet include broader V2/V3 features.

## Roadmap

- `V1.5`: backend engine plus a basic Streamlit demo
- `V2`: news ingestion plus an inbox-style review flow
- `V2.5`: UI/UX rework and polish for demo quality
- `V3`: OpenClaw and chat-style orchestration

## Future Work

Future upgrades and out-of-scope ideas are tracked in
[future_ideas.md](future_ideas.md).
