# Second Order

Second Order is a local research workflow for turning geopolitical and
policy headlines into structured event reviews. It pulls headlines into a news
inbox, fuses overlapping coverage into a single event candidate, classifies the
event lifecycle, extracts a provisional economic mechanism, and checks whether
market moves provide directional evidence rather than proof.

The current V1.5 product includes a basic Streamlit app, a SQLite research
archive, and a cheap evaluation loop built around canary runs. It is designed
for manual research and demo use: useful enough to inspect real flows end to
end, while still small enough to iterate on quickly.

## Current Workflow

1. Load headlines from a local inbox file and curated RSS feeds.
2. Cluster and fuse overlapping headlines into one event candidate.
3. Classify the event stage and persistence.
4. Extract a provisional mechanism summary plus beneficiary and loser tickers.
5. Run direction-aware market validation in current-price mode or optional
   event-date anchored mode.
6. Save the result to SQLite for later review in the app.

## Key Features

- Streamlit demo UI with a news inbox and recent-events view
- Multi-source headline ingestion from local JSON and RSS
- Headline clustering and simple source-aware event fusion
- Event lifecycle classification (`stage`, `persistence`)
- Hidden economic mechanism extraction with ticker sanitization
- Direction-aware market validation with optional event-date anchoring
- SQLite archive with saved events, `event_date`, and structured market tickers
- Evaluation runner with canary, `--ids`, and `--limit` options

## Quick Start

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
streamlit run app.py
```

### React Frontend

```powershell
cd frontend
npm install
npm run dev          # starts on http://localhost:5173
```

The Vite dev server proxies `/api/*` to the FastAPI backend at `localhost:8000`.
Start the backend first:

```powershell
python -m uvicorn api:app --reload
```

### Optional local runs

```powershell
python main.py
python eval.py --preset canary
python eval.py
```

If `ANTHROPIC_API_KEY` is not set, the analysis step falls back to a mock
response instead of failing.

## Project Layout

- `frontend/`: React + TypeScript + shadcn/ui dashboard (Vite dev server)
- `api.py`: FastAPI layer over the backend engine
- `app.py`: Streamlit app with the inbox, fused event review, analysis view, and recent saved events
- `news_sources.py`: local JSON + RSS ingestion, normalization, and headline clustering
- `classify.py`: event stage and persistence classification
- `analyze_event.py`: mechanism extraction, ticker sanitization, and fallback behavior
- `market_check.py`: direction-aware market validation in current-price or event-date mode
- `db.py`: SQLite schema and persistence helpers
- `eval.py`: sample-set evaluation runner
- `sample_events.json`: reusable evaluation set with expected labels

## Tests

```powershell
python -m unittest discover -s tests -v
```

## Scope And Limitations

- The Streamlit app works end to end, but it is still a basic demo rather than a polished product UI.
- Classification and mechanism extraction remain heuristic or provisional in important places.
- Market validation should be treated as supporting evidence, not confirmation.
- The system is local-first and does not yet include schedulers, orchestration, or broader V2/V3 platform features.

## Roadmap

- `V1.5`: backend engine plus a basic Streamlit demo
- `V2`: news ingestion plus an inbox-style review flow
- `V2.5`: UI/UX rework and polish for demo quality
- `V3`: OpenClaw and chat-style orchestration

Future upgrades and out-of-scope ideas are tracked in
[future_ideas.md](future_ideas.md).
