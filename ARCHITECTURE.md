# Architecture Notes

This document explains the repo's reasoning flow in plain language. It is
meant to clarify how the project handles headlines without turning the design
into a large framework.

## Current product state

The maintained product path is now a React frontend backed by FastAPI, with
SQLite persistence, live inbox ingestion, progressive analysis, recent-event
review, and dated backtesting. The old Streamlit file remains in the repo only
as frozen historical reference and should not be read as the current UI plan.

## Historical context

- `V1.5`: backend engine plus an early Streamlit demo
- `V2`: live news ingestion plus an inbox-style review flow
- `V2.5`: React/FastAPI product surface and demo polish
- `V3`: OpenClaw and chat-style orchestration

## Workflow

### 1. Headline input

The workflow now starts from the live inbox or a pasted headline. The system
treats the headline as a compact description of an event rather than a full
article.

### 2. Event classification

The first pass assigns two labels:

- `stage`: where the event appears to sit in its lifecycle
- `persistence`: how durable the effects may be

These labels are simple heuristics. They help structure downstream reasoning,
but they are not meant to be a deep semantic model.

### 3. Hidden economic mechanism

The next step tries to identify the hidden economic mechanism behind the
headline. In practical terms, that means asking what changed, which actors or
assets may benefit, which may be hurt, and what belongs on a watchlist.

### 4. Watchlist generation

The mechanism step also produces a small list of assets to watch. The watchlist
is meant to make the output more concrete and easier to review.

### 5. Market validation

Market validation is a follow-up check on the watchlist. Its role is limited:
it is evidence, not proof. A supportive market read can strengthen the case
for a mechanism, but it does not confirm it. A weak or noisy read does not
necessarily invalidate the idea either.

### 6. Local persistence and review

The resulting record can be saved locally for later review, related-event
lookup, notes, ratings, and dated backtesting. This keeps the workflow
inspectable and lightweight.

## Interpretation guidance

- Classification is heuristic and should be judged directionally.
- Mechanism output is provisional and should be reviewed critically.
- Market validation is evidence, not proof.
- The overall workflow is designed for practical review, not formal prediction.
- The maintained app surface is FastAPI + React, not the legacy Streamlit file.

## Out of scope

- No RAG
- No dashboards
- No OpenClaw in the current phase
- No hosted multi-user platform in the current phase
